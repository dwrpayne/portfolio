# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:11
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grs', '0004_auto_20180116_2207'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='grsclient',
            name='baseclient_ptr',
        ),
        migrations.RemoveField(
            model_name='grsclient',
            name='id2',
        ),
    ]
