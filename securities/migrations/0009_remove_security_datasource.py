# Generated by Django 2.0.2 on 2018-02-24 10:30

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('securities', '0008_auto_20180224_0136'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='security',
            name='datasource',
        ),
    ]
