# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:41
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0010_auto_20180116_2102'),
    ]

    operations = [
        migrations.DeleteModel(
            name='BaseClient',
        ),
    ]
