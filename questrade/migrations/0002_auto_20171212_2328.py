# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-13 07:28
from __future__ import unicode_literals

from django.db import migrations
import django.db.models.manager


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelManagers(
            name='questradeaccount',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
