# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-27 18:31
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0066_auto_20171027_1006'),
    ]

    operations = [
        migrations.AlterField(
            model_name='currency',
            name='lookupSource',
            field=models.CharField(blank=True, default=None, max_length=16, null=True),
        ),
        migrations.AlterField(
            model_name='security',
            name='lookupSource',
            field=models.CharField(blank=True, default=None, max_length=16, null=True),
        ),
    ]
