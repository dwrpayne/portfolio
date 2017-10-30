# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-10-30 07:25
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('grs', '0012_auto_20171030_0025'),
        ('questrade', '0076_remove_activity_action'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='exchangerate',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='exchangerate',
            name='currency',
        ),
        migrations.AlterUniqueTogether(
            name='holding',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='holding',
            name='account',
        ),
        migrations.RemoveField(
            model_name='holding',
            name='security',
        ),
        migrations.RemoveField(
            model_name='security',
            name='currency',
        ),
        migrations.AlterUniqueTogether(
            name='securityprice',
            unique_together=set([]),
        ),
        migrations.RemoveField(
            model_name='securityprice',
            name='security',
        ),
        migrations.AlterField(
            model_name='activity',
            name='cash',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_cash', to='finance.Security'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='security',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='dontaccess_security', to='finance.Security'),
        ),
        migrations.DeleteModel(
            name='Currency',
        ),
        migrations.DeleteModel(
            name='ExchangeRate',
        ),
        migrations.DeleteModel(
            name='Holding',
        ),
        migrations.DeleteModel(
            name='Security',
        ),
        migrations.DeleteModel(
            name='SecurityPrice',
        ),
    ]
