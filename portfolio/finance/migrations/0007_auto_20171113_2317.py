# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-14 07:17
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_baseaccount_taxable'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='exchangerate',
            index=models.Index(fields=['currency'], name='finance_exc_currenc_e3809c_idx'),
        ),
        migrations.AddIndex(
            model_name='securityprice',
            index=models.Index(fields=['security'], name='finance_sec_securit_84f6ab_idx'),
        ),
    ]