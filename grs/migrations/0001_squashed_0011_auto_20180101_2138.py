# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-07 06:50
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django.db.models.manager


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('datasource', '0002_auto_20171215_2037'),
        ('finance', '0001_squashed_0033_auto_20180104_1400')
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
                ('username', models.CharField(max_length=32)),
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
                ('symbol', models.CharField(default='ETP', max_length=100)),
                ('description', models.CharField(default=' ', max_length=256)),
            ],
            bases=('finance.baserawactivity',),
        ),
        migrations.AlterUniqueTogether(
            name='grsrawactivity',
            unique_together=set([]),
        ),
        migrations.AlterModelManagers(
            name='grsaccount',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AlterModelManagers(
            name='grsclient',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='GrsDataSource',
            fields=[
                ('datasourcemixin_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='datasource.DataSourceMixin')),
                ('symbol', models.CharField(max_length=32)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='grs.GrsClient')),
                ('plan_data', models.CharField(default='PLAN^53947^40823^MEMBR^DEFERRED+PROFIT+SHARING+PLAN', max_length=100)),
            ],
            options={
                'abstract': False,
            },
            bases=('datasource.datasourcemixin',),
        ),
        migrations.RemoveField(
            model_name='grsaccount',
            name='plan_data',
        ),
        migrations.AlterModelManagers(
            name='grsclient',
            managers=[
            ],
        ),
        migrations.AlterModelManagers(
            name='grsrawactivity',
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('base_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
