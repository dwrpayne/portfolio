from django import forms
from django.core.mail import send_mail
from .models import AccountCsv, UserProfile, Allocation
from django.contrib.auth import get_user_model
from django.forms.models import inlineformset_factory, modelformset_factory
from django.forms.widgets import NumberInput, CheckboxSelectMultiple
from django.core.exceptions import ValidationError


class FeedbackForm(forms.Form):
    name = forms.CharField(widget=forms.HiddenInput(), max_length=100)
    email = forms.CharField(widget=forms.HiddenInput(), max_length=100)
    feedback = forms.CharField(label='', widget=forms.Textarea(attrs={'placeholder': 'Anything you want to tell me! Is something broken? Didn\'t do what you expected? Do you want to see a report of some kind? Is something confusing or misworded? Please let me know!'}))

    def send_email(self):
        user_email = self.cleaned_data['email']
        user_name = self.cleaned_data['name']
        feedback = self.cleaned_data['feedback']

        feedback_email = 'feedback@davidpayne.net'
        noreply_email = 'noreply@davidpayne.net'

        send_mail(subject='Feedback from ' + user_name,
                  message=feedback,
                  from_email=user_email,
                  recipient_list=[feedback_email])

        send_mail(subject='Thanks for your feedback, {}!'.format(user_name),
                  message='I appreciate you taking the time to send me this feedback!\n\n{}'.format(feedback),
                  from_email=noreply_email,
                  recipient_list=[user_email])


class UserForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']


ProfileInlineFormset = inlineformset_factory(get_user_model(), UserProfile, fields=(
    'phone', 'country'), can_delete=False)


class AccountCsvForm(forms.ModelForm):
    class Meta:
        model = AccountCsv
        fields = ['csvfile', 'account']
        labels = {'csvfile' : 'Please choose a file containing transaction history as downloaded from your brokerage.\n'
                              'The supported format is CSV.',
                  'account' : 'Select the account this file relates to, or leave blank to auto-detect:'
                  }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = self.fields['account'].queryset.for_user(user)


class AllocationForm(forms.ModelForm):
    class Meta:
        model = Allocation
        fields = ['securities', 'desired_pct']
        labels = {'securities': 'Select one or several securities.',
                  'desired_pct': 'The percentage of your portfolio to allocate to this group of securities: '}
        widgets = {'desired_pct': NumberInput(attrs={'min': 0, 'max': 100, 'width':50}),
                   'securities': CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['securities'].queryset = self.user.allocations.get_unallocated_securities()

    def clean_securities(self):
        securities = self.cleaned_data['securities']
        if self.user.allocations.filter(securities__in=securities):
            raise ValidationError('User already has an allocation for this security')
        return securities


class BaseAllocationFormSet(forms.BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return
        total = sum(form.cleaned_data['desired_pct'] for form in self.forms)
        if total > 100:
            raise forms.ValidationError("Total percentages must sum to less than 100. Yours totalled {}".format(total))



AllocationFormSet = modelformset_factory(Allocation,
                                         formset=BaseAllocationFormSet,
                                         fields=('desired_pct',),
                                         widgets = {'desired_pct': NumberInput(attrs={'min': 0, 'max': 100, 'width':50})},
                                         extra=0,
                                         can_delete=True)
