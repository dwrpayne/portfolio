# Generated by Django 2.0.2 on 2018-02-26 08:22

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('virtbrokers', '0004_auto_20180218_1720'),
    ]

    operations = [
        migrations.RenameField(
            model_name='virtbrokersrawactivity',
            old_name='netAmount',
            new_name='net_amount',
        ),
    ]