# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-16 06:58
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('datasource', '0002_auto_20171215_2037'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='FakeDataSource',
            new_name='ConstantDataSource',
        ),
    ]