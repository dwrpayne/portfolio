# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-16 06:05
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('datasource', '0002_auto_20171215_2037'),
        ('grs', '0005_auto_20171214_0635'),
    ]

    operations = [
        migrations.CreateModel(
            name='GrsDataSource',
            fields=[
                ('datasourcemixin_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='datasource.DataSourceMixin')),
                ('symbol', models.CharField(max_length=32)),
                ('client', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='grs.GrsClient')),
            ],
            options={
                'abstract': False,
            },
            bases=('datasource.datasourcemixin',),
        ),
    ]