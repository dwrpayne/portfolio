# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-31 09:28
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0001_initial'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Account',
            new_name='QuestradeAccount',
        ),
        migrations.RenameModel(
            old_name='Client',
            new_name='QuestradeClient',
        ),
    ]
