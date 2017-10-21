# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-16 04:16
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0008_auto_20171015_2053'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='activity',
            unique_together=set([('account', 'tradeDate', 'action', 'symbol', 'currency', 'qty', 'price', 'netAmount', 'type', 'description')]),
        ),
    ]
