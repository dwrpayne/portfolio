# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-22 20:40
from __future__ import unicode_literals

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0026_remove_security_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExchangeRate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency', models.CharField(max_length=3)),
                ('date', models.DateField(default=datetime.date.today)),
                ('price', models.DecimalField(decimal_places=6, max_digits=16)),
            ],
            options={
                'get_latest_by': 'date',
            },
        ),
        migrations.AlterField(
            model_name='security',
            name='type',
            field=models.CharField(choices=[('Stock', 'Stock'), ('Option', 'Option'), ('Bond', 'Bond'), ('Right', 'Right'), ('Gold', 'Gold'), ('MutualFund', 'MutualFund'), ('Index', 'Index')], max_length=12),
        ),
        migrations.AlterField(
            model_name='securityprice',
            name='price',
            field=models.DecimalField(decimal_places=2, max_digits=16),
        ),
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(fields=['currency', 'date'], name='questrade_e_currenc_8ba22e_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='exchangerate',
            unique_together=set([('currency', 'date')]),
        ),
    ]