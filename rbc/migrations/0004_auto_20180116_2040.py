# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 04:40
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0008_auto_20180116_2026'),
        ('rbc', '0003_auto_20180115_0251'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='rbcclient',
            name='baseclient_ptr',
        ),
        migrations.DeleteModel(
            name='RbcClient',
        ),
    ]
