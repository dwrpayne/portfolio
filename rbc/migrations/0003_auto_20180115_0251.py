# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-15 10:51
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rbc', '0002_rbcrawactivity'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='rbcrawactivity',
            unique_together=set([]),
        ),
    ]
