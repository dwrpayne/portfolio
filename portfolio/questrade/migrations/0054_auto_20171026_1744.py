# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-27 00:44
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0053_auto_20171026_1732'),
    ]

    operations = [
        migrations.AddField(
            model_name='activity',
            name='cash',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_cash', to='questrade.Security'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='security',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_security', to='questrade.Security'),
        ),
        migrations.AlterUniqueTogether(
            name='activity',
            unique_together=set([('account', 'tradeDate', 'action', 'security', 'cash', 'qty', 'price', 'netAmount', 'type', 'description')]),
        ),
    ]
