# Generated by Django 2.0.3 on 2020-11-21 23:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0031_auto_20181016_2317'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='costbasis',
            options={'get_latest_by': 'trade_date', 'ordering': ['security', 'trade_date', '-qty']},
        ),
    ]
