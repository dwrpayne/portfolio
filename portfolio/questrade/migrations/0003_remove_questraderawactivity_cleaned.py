# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-06 05:33
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0002_auto_20171031_0228'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='questraderawactivity',
            name='cleaned',
        ),
    ]