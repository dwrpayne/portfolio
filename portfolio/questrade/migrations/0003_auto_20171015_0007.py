# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-15 07:07
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0002_auto_20171014_2357'),
    ]

    operations = [
        migrations.RenameField(
            model_name='exchangerate',
            old_name='basecurrency',
            new_name='currencypair',
        ),
        migrations.RemoveField(
            model_name='exchangerate',
            name='currency',
        ),
        migrations.AlterField(
            model_name='stockprice',
            name='symbol',
            field=models.CharField(max_length=100, unique_for_date='date'),
        ),
    ]