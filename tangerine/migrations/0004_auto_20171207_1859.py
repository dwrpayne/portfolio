# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-08 02:59
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tangerine', '0003_auto_20171108_2305'),
    ]

    operations = [
        migrations.RenameField(
            model_name='tangerinerawactivity',
            old_name='security',
            new_name='symbol',
        ),
    ]