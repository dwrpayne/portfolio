# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-31 03:30
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='GrsAccount',
            fields=[
                ('baseaccount_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseAccount')),
                ('plan_data', models.CharField(max_length=100)),
            ],
            options={
                'abstract': False,
            },
            bases=('finance.baseaccount',),
        ),
        migrations.CreateModel(
            name='GrsClient',
            fields=[
                ('baseclient_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseClient')),
                ('password', models.CharField(max_length=100)),
            ],
            options={
                'abstract': False,
            },
            bases=('finance.baseclient',),
        ),
        migrations.CreateModel(
            name='GrsRawActivity',
            fields=[
                ('baserawactivity_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseRawActivity')),
                ('day', models.DateField()),
                ('qty', models.DecimalField(decimal_places=6, max_digits=16)),
                ('price', models.DecimalField(decimal_places=6, max_digits=16)),
                ('security', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='finance.Security')),
            ],
            options={
                'abstract': False,
            },
            bases=('finance.baserawactivity',),
        ),
    ]