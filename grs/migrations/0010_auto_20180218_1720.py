# Generated by Django 2.0.2 on 2018-02-19 01:20

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('grs', '0009_auto_20180118_0819'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='grsaccount',
            options={'base_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='grsdatasource',
            options={'base_manager_name': 'objects'},
        ),
        migrations.AlterModelOptions(
            name='grsrawactivity',
            options={'base_manager_name': 'objects'},
        ),
        migrations.AlterModelManagers(
            name='grsaccount',
            managers=[
            ],
        ),
        migrations.AlterModelManagers(
            name='grsrawactivity',
            managers=[
            ],
        ),
    ]
