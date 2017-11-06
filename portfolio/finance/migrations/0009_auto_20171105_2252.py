# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-06 06:52
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0008_delete_cash'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activity',
            name='security',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='finance.Security'),
        ),
    ]