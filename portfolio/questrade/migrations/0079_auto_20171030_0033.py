# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-30 07:33
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0078_auto_20171030_0029'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='ActivityJson',
            new_name='QuestradeRawActivity',
        ),
    ]
