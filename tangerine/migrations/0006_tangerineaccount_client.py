# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:49
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tangerine', '0005_auto_20180116_2243'),
    ]

    operations = [
        migrations.AddField(
            model_name='tangerineaccount',
            name='client',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='tangerine.TangerineClient'),
        ),
    ]