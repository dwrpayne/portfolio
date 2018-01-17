# -*- coding: utf-8 -*-
# Generated by Django 1.11.8 on 2018-01-17 06:43
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tangerine', '0004_auto_20180116_2237'),
    ]

    operations = [
        migrations.CreateModel(
            name='TangerineClient',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=32)),
                ('password', models.CharField(max_length=100)),
                ('securityq1', models.CharField(max_length=1000)),
                ('securitya1', models.CharField(max_length=100)),
                ('securityq2', models.CharField(max_length=1000)),
                ('securitya2', models.CharField(max_length=100)),
                ('securityq3', models.CharField(max_length=1000)),
                ('securitya3', models.CharField(max_length=100)),
            ],
        ),
    ]
