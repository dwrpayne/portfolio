# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-31 03:30
from __future__ import unicode_literals

import datetime
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='Activity',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tradeDate', models.DateField()),
                ('description', models.CharField(max_length=1000)),
                ('qty', models.DecimalField(decimal_places=6, max_digits=16)),
                ('price', models.DecimalField(decimal_places=6, max_digits=16)),
                ('netAmount', models.DecimalField(decimal_places=2, max_digits=16)),
                ('type', models.CharField(choices=[('Deposit', 'Deposit'), ('Dividend', 'Dividend'), ('FX', 'FX'), ('Fee', 'Fee'), ('Interest', 'Interest'), ('Buy', 'Buy'), ('Sell', 'Sell'), ('Transfer', 'Transfer'), ('Withdrawal', 'Withdrawal'), ('Expiry', 'Expiry'), ('Journal', 'Journal'), ('NotImplemented', 'NotImplemented')], max_length=100)),
            ],
            options={
                'verbose_name_plural': 'Activities',
                'ordering': ['tradeDate'],
                'get_latest_by': 'tradeDate',
            },
        ),
        migrations.CreateModel(
            name='BaseAccount',
            fields=[
                ('type', models.CharField(max_length=100)),
                ('id', models.IntegerField(default=0, primary_key=True, serialize=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BaseClient',
            fields=[
                ('username', models.CharField(max_length=10, primary_key=True, serialize=False)),
                ('polymorphic_ctype', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_finance.baseclient_set+', to='contenttypes.ContentType')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BaseRawActivity',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rawactivities', to='finance.BaseAccount')),
                ('polymorphic_ctype', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_finance.baserawactivity_set+', to='contenttypes.ContentType')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Currency',
            fields=[
                ('lookupSymbol', models.CharField(blank=True, default=None, max_length=16, null=True)),
                ('lookupSource', models.CharField(blank=True, default=None, max_length=16, null=True)),
                ('lookupColumn', models.CharField(blank=True, default=None, max_length=10, null=True)),
                ('livePrice', models.DecimalField(decimal_places=6, default=0, max_digits=19)),
                ('code', models.CharField(max_length=3, primary_key=True, serialize=False)),
            ],
            options={
                'verbose_name_plural': 'Currencies',
            },
        ),
        migrations.CreateModel(
            name='ExchangeRate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField(default=datetime.date.today)),
                ('price', models.DecimalField(decimal_places=6, max_digits=19)),
                ('currency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rates', to='finance.Currency')),
            ],
            options={
                'get_latest_by': 'day',
            },
        ),
        migrations.CreateModel(
            name='Holding',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qty', models.DecimalField(decimal_places=6, max_digits=16)),
                ('startdate', models.DateField()),
                ('enddate', models.DateField(null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='finance.BaseAccount')),
            ],
            options={
                'get_latest_by': 'startdate',
            },
        ),
        migrations.CreateModel(
            name='Security',
            fields=[
                ('lookupSymbol', models.CharField(blank=True, default=None, max_length=16, null=True)),
                ('lookupSource', models.CharField(blank=True, default=None, max_length=16, null=True)),
                ('lookupColumn', models.CharField(blank=True, default=None, max_length=10, null=True)),
                ('livePrice', models.DecimalField(decimal_places=6, default=0, max_digits=19)),
                ('symbol', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('symbolid', models.BigIntegerField(default=0)),
                ('description', models.CharField(blank=True, default='', max_length=500, null=True)),
                ('type', models.CharField(choices=[('Stock', 'Stock'), ('Option', 'Option'), ('Cash', 'Cash'), ('MutualFund', 'MutualFund')], default='Stock', max_length=12)),
                ('listingExchange', models.CharField(blank=True, default='', max_length=20, null=True)),
                ('currency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='finance.Currency')),
            ],
            options={
                'verbose_name_plural': 'Securities',
            },
        ),
        migrations.CreateModel(
            name='SecurityPrice',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day', models.DateField(default=datetime.date.today)),
                ('price', models.DecimalField(decimal_places=6, max_digits=19)),
                ('security', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rates', to='finance.Security')),
            ],
            options={
                'get_latest_by': 'day',
            },
        ),
        migrations.AddField(
            model_name='holding',
            name='security',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='finance.Security'),
        ),
        migrations.AddField(
            model_name='baseaccount',
            name='client',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='accounts', to='finance.BaseClient'),
        ),
        migrations.AddField(
            model_name='baseaccount',
            name='polymorphic_ctype',
            field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='polymorphic_finance.baseaccount_set+', to='contenttypes.ContentType'),
        ),
        migrations.AddField(
            model_name='activity',
            name='account',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='finance.BaseAccount'),
        ),
        migrations.AddField(
            model_name='activity',
            name='cash',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_cash', to='finance.Security'),
        ),
        migrations.AddField(
            model_name='activity',
            name='raw',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='finance.BaseRawActivity'),
        ),
        migrations.AddField(
            model_name='activity',
            name='security',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_security', to='finance.Security'),
        ),
        migrations.AddIndex(
            model_name='securityprice',
            index=models.Index(fields=['security', 'day'], name='finance_sec_securit_6739f8_idx'),
        ),
        migrations.AddIndex(
            model_name='securityprice',
            index=models.Index(fields=['day'], name='finance_sec_day_ae2cb6_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='securityprice',
            unique_together=set([('security', 'day')]),
        ),
        migrations.AlterUniqueTogether(
            name='holding',
            unique_together=set([('account', 'security', 'startdate')]),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(fields=['currency', 'day'], name='finance_exc_currenc_33e39b_idx'),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(fields=['day'], name='finance_exc_day_cb0ed9_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='exchangerate',
            unique_together=set([('currency', 'day')]),
        ),
        migrations.AlterUniqueTogether(
            name='activity',
            unique_together=set([('account', 'tradeDate', 'security', 'cash', 'qty', 'price', 'netAmount', 'type', 'description')]),
        ),
    ]