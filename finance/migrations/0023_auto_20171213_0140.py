# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-13 09:40
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0022_remove_security_listingexchange'),
    ]

    operations = [
        migrations.CreateModel(
            name='Cash',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('finance.security',),
        ),
        migrations.CreateModel(
            name='MutualFund',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('finance.security',),
        ),
        migrations.CreateModel(
            name='Option',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('finance.security',),
        ),
        migrations.CreateModel(
            name='Stock',
            fields=[
            ],
            options={
                'proxy': True,
                'indexes': [],
            },
            bases=('finance.security',),
        ),
        migrations.AlterModelOptions(
            name='holdingdetail',
            options={'get_latest_by': 'day', 'managed': False, 'ordering': ['day']},
        ),
        migrations.AlterUniqueTogether(
            name='activity',
            unique_together=set([('raw', 'type')]),
        ),
        migrations.AlterModelTable(
            name='holdingdetail',
            table='financeview_holdingdetail',
        ),
    ]