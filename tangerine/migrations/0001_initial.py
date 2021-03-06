# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-07 07:19
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django.db.models.manager


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TangerineAccount',
            fields=[
                ('baseaccount_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseAccount')),
                ('internal_display_name', models.CharField(max_length=100)),
                ('account_balance', models.DecimalField(decimal_places=6, max_digits=16)),
            ],
            options={
                'abstract': False,
            },
            bases=('finance.baseaccount',),
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='TangerineClient',
            fields=[
                ('baseclient_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseAccount')),
                ('username', models.CharField(max_length=32)),
                ('password', models.CharField(max_length=100)),
                ('securityq1', models.CharField(max_length=1000)),
                ('securitya1', models.CharField(max_length=100)),
                ('securityq2', models.CharField(max_length=1000)),
                ('securitya2', models.CharField(max_length=100)),
                ('securityq3', models.CharField(max_length=1000)),
                ('securitya3', models.CharField(max_length=100)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='TangerineRawActivity',
            fields=[
                ('baserawactivity_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseRawActivity')),
                ('day', models.DateField()),
                ('description', models.CharField(max_length=1000)),
                ('activity_id', models.CharField(max_length=32, unique=True)),
                ('type', models.CharField(max_length=32)),
                ('symbol', models.CharField(max_length=100)),
                ('qty', models.DecimalField(decimal_places=6, max_digits=16)),
                ('price', models.DecimalField(decimal_places=6, max_digits=16)),
            ],
            options={
                'abstract': False,
            },
            bases=('finance.baserawactivity',),
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
