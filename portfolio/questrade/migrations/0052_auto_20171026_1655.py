# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-26 23:55
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0051_auto_20171026_1647'),
    ]

    operations = [
        migrations.RenameField(
            model_name='security',
            old_name='security_currency',
            new_name='currency',
        ),
        migrations.RemoveField(
            model_name='holding',
            name='securitybase',
        ),
        migrations.DeleteModel(
            name='SecurityBase',
        ),
    ]
