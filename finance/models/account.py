import datetime

from django.conf import settings
from django.db import models, transaction
from django.utils.functional import cached_property
from polymorphic.managers import PolymorphicManager
from polymorphic.models import PolymorphicModel
from polymorphic.query import PolymorphicQuerySet
from polymorphic.showfields import ShowFieldTypeAndContent

import utils.dates
from securities.models import Security


class BaseAccountQuerySet(PolymorphicQuerySet):
    def for_user(self, user):
        return self.filter(user=user) if user else self

    def SyncAllBalances(self):
        for account in self:
            account.SyncBalances()

    def SyncAllActivitiesAndRegenerate(self):
        for account in self:
            account.SyncAndRegenerate()


class BaseAccount(ShowFieldTypeAndContent, PolymorphicModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                             on_delete=models.CASCADE, related_name='accounts_for_user')
    type = models.CharField(max_length=100)
    account_id = models.CharField(max_length=100)
    taxable = models.BooleanField(default=True)
    display_name = models.CharField(max_length=100, default='')
    creation_date = models.DateField(default='2009-01-01')

    objects = PolymorphicManager.from_queryset(BaseAccountQuerySet)()

    activitySyncDateRange = 30

    class Meta:
        ordering = ['account_id']

    def __repr__(self):
        return "BaseAccount({},{},{})".format(self.user, self.account_id, self.type)

    def __str__(self):
        return self.display_name

    @cached_property
    def cur_cash_balance(self):
        query = self.holdingdetail_set.cash().today().total_values()
        if query:
            return query.first()[1]
        return 0

    @cached_property
    def cur_balance(self):
        return self.GetValueToday()

    @cached_property
    def yesterday_balance(self):
        return self.GetValueAtDate(datetime.date.today() - datetime.timedelta(days=1))

    @cached_property
    def today_balance_change(self):
        return self.cur_balance - self.yesterday_balance

    @cached_property
    def sync_from_date(self):
        last_activity = self.activities.newest_date()
        if last_activity:
            return last_activity + datetime.timedelta(days=1)
        return self.creation_date

    def SyncBalances(self):
        pass

    def import_activities(self, csv_file):
        activity_count = self.activities.all().count()


        self.import_from_csv(csv_file)
        if self.activities.all().count() > activity_count:
            self.RegenerateHoldings()

        Security.objects.Sync(False)

    def import_from_csv(self, csv_file):
        """
        Override this to enable transaction uploading from csv.
        Subclasses are expected to parse the csv and create the necessary BaseRawActivity subclasses.
        """
        pass

    def SyncAndRegenerate(self):
        activity_count = self.activities.all().count()

        if self.activitySyncDateRange:
            date_range = utils.dates.day_intervals(self.activitySyncDateRange, self.sync_from_date)
            print('Syncing all activities for {} in {} chunks.'.format(self, len(date_range)))

            for period in date_range:
                self.CreateActivities(period.start, period.end)

        if self.activities.all().count() > activity_count:
            self.RegenerateHoldings()

    def RegenerateActivities(self):
        self.activities.all().delete()
        with transaction.atomic():
            for raw in self.rawactivities.all():
                raw.CreateActivity()
        self.RegenerateHoldings()
        self.user.userprofile.RegenerateCostBasis()

    def RegenerateHoldings(self):
        self.holding_set.all().delete()
        for activity in self.activities.all():
            for security, qty_delta in activity.GetHoldingEffects().items():
                self.holding_set.add_effect(self, security, qty_delta, activity.tradeDate)
        self.holding_set.filter(qty=0).delete()

    def CreateActivities(self, start, end):
        """
        Retrieve raw activity data for the specified account and start/end period.
        Store it in the DB as a subclass of BaseRawActivity.
        Return the newly created raw instances.
        """
        return []

    def GetValueAtDate(self, date):
        result = self.holdingdetail_set.at_date(date).total_values().first()
        if result:
            return result[1]
        return 0

    def GetValueToday(self):
        return self.GetValueAtDate(datetime.date.today())


class AccountCsv(models.Model):
    def upload_path(self, filename):
        return 'accountcsv/{}/{}/{}.{}'.format(self.user.username,
                                               self.account.pk,
                                               datetime.date.today().isoformat(),
                                               filename.rsplit('.')[-1])

    csvfile = models.FileField(upload_to=upload_path)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    account = models.ForeignKey(BaseAccount, blank=True, on_delete=models.CASCADE)

    def find_matching_account(self):
        """
        :return: The account if it was automatched, None otherwise.
        """
        if not hasattr(self, 'account'):
            data = str(self.csvfile.read())
            self.account = sorted(self.user.userprofile.GetAccounts(),
                key=lambda a: data.count(a.pk))[-1]
            return self.account
        return None

