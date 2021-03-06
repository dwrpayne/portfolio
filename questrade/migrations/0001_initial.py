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
            name='QuestradeAccount',
            fields=[
                ('baseaccount_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseAccount')),
                ('curBalanceSynced', models.DecimalField(decimal_places=4, default=0, max_digits=19)),
                ('sodBalanceSynced', models.DecimalField(decimal_places=4, default=0, max_digits=19)),
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
            name='QuestradeActivityType',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('q_type', models.CharField(max_length=32)),
                ('q_action', models.CharField(max_length=32)),
                ('activity_type', models.CharField(max_length=32)),
            ],
        ),
        migrations.CreateModel(
            name='QuestradeClient',
            fields=[
                ('baseclient_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseAccount')),
                ('username', models.CharField(max_length=32)),
                ('refresh_token', models.CharField(max_length=100)),
                ('access_token', models.CharField(blank=True, max_length=100, null=True)),
                ('api_server', models.CharField(blank=True, max_length=100, null=True)),
                ('token_expiry', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='QuestradeRawActivity',
            fields=[
                ('baserawactivity_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='finance.BaseRawActivity')),
                ('jsonstr', models.CharField(max_length=1000)),
            ],
            options={
                'verbose_name_plural': 'Questrade Raw Activities',
            },
            bases=('finance.baserawactivity',),
        ),
        migrations.AlterUniqueTogether(
            name='questraderawactivity',
            unique_together=set([('baserawactivity_ptr', 'jsonstr')]),
        ),
    ]
