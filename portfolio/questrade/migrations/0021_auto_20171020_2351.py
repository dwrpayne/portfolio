# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-21 06:51
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('questrade', '0020_auto_20171019_0809'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='activity',
            name='cleansed',
        ),
        migrations.AddField(
            model_name='activity',
            name='sourcejson',
            field=models.CharField(default='', max_length=1000),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='activity',
            name='security',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='questrade.Security'),
        ),
        migrations.AlterField(
            model_name='security',
            name='symbol',
            field=models.CharField(max_length=100, unique=True),
        ),
    ]