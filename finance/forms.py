from django import forms
from django.core.mail import send_mail

class FeedbackForm(forms.Form):
    name = forms.CharField(label='Your name', max_length=100)
    feedback = forms.CharField(label='Comments', widget=forms.Textarea(attrs={'placeholder': 'Anything you want to tell me! Is something broken? Didn\'t do what you expected? Do you want to see a report of some kind? Is something confusing or misworded? Please let me know!'}))

    def send_email(self):
        send_mail(subject='Feedback from ' + self.cleaned_data['name'],
                  message=self.cleaned_data['feedback'],
                  from_email='noreply@davidpayne.net',
                  recipient_list=['feedback@davidpayne.net'])



