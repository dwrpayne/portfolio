# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-30 07:29
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0077_auto_20171030_0025'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='activity',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='activity',
            name='account',
        ),
        migrations.RemoveField(
            model_name='activity',
            name='cash',
        ),
        migrations.RemoveField(
            model_name='activity',
            name='security',
        ),
        migrations.RemoveField(
            model_name='activity',
            name='sourcejson',
        ),
        migrations.DeleteModel(
            name='Activity',
        ),
    ]
