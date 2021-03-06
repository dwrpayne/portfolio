# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:49
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0007_auto_20180116_2243'),
    ]

    operations = [
        migrations.AddField(
            model_name='questradeaccount',
            name='client',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='questrade.QuestradeClient'),
        ),
        migrations.AddField(
            model_name='questradeoptiondatasource',
            name='client',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='questrade.QuestradeClient'),
            preserve_default=False,
        ),
    ]
