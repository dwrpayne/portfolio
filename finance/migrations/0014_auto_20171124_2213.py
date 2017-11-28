# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-25 06:13
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0013_auto_20171124_2205'),
    ]

    operations = [
        migrations.AlterField(
            model_name='allocation',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='allocations', to=settings.AUTH_USER_MODEL),
        ),
    ]