# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 04:23
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finance', '0006_auto_20180115_0327'),
    ]

    operations = [
        migrations.AddField(
            model_name='baseaccount',
            name='user',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='accounts_for_user', to=settings.AUTH_USER_MODEL),
        ),
    ]
