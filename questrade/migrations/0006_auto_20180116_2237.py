# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:37
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0005_auto_20180116_2212'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='questradeaccount',
            name='client2',
        ),
        migrations.RemoveField(
            model_name='questradeoptiondatasource',
            name='client',
        ),
        migrations.DeleteModel(
            name='QuestradeClient',
        ),
    ]
