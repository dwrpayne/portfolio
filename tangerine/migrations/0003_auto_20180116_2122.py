# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 05:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tangerine', '0002_tangerineaccount_client2'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tangerineclient',
            name='baseclient_ptr',
        ),
        migrations.AddField(
            model_name='tangerineclient',
            name='id2',
            field=models.IntegerField(default=123, primary_key=True, serialize=False),
            preserve_default=False,
        ),
    ]
