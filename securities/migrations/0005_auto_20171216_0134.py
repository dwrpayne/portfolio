# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-16 09:34
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('securities', '0004_auto_20171215_2205'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='currency',
            name='datasource',
        ),
        migrations.AlterUniqueTogether(
            name='exchangerate',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='exchangerate',
            name='currency',
        ),
        migrations.RemoveField(
            model_name='security',
            name='currency',
        ),
        migrations.AddField(
            model_name='security',
            name='currency_id',
            field=models.CharField(default='XXX', max_length=3),
        ),
        migrations.DeleteModel(
            name='Currency',
        ),
        migrations.DeleteModel(
            name='ExchangeRate',
        ),
    ]