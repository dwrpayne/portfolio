# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 04:46
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tangerine', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tangerineaccount',
            name='client2',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='tangerine.TangerineClient'),
        ),
    ]
