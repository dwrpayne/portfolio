# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-30 07:59
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0081_auto_20171030_0052'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='BaseAccount_ptr',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='client',
            name='BaseClient_ptr',
            field=models.IntegerField(null=True),
        ),
    ]
