from django import forms
from django.core.mail import send_mail
from .models import AccountCsv

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


class AccountCsvForm(forms.ModelForm):
    class Meta:
        model = AccountCsv
        fields = ['csvfile', 'account']
        labels = {'csvfile' : 'Please choose a file containing transaction history.\n'
                              'The supported format is CSV.',
                  }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = self.fields['account'].queryset.for_user(user)
