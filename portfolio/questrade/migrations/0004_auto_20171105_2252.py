# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-06 06:52
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0003_remove_questraderawactivity_cleaned'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='questraderawactivity',
            options={'verbose_name_plural': 'Questrade Raw Activities'},
        ),
    ]