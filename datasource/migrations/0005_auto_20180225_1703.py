# Generated by Django 2.0.2 on 2018-02-26 01:03

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('datasource', '0004_auto_20180225_1628'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlphaVantageCurrencySource',
            fields=[
                ('datasourcemixin_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='datasource.DataSourceMixin')),
                ('api_key', models.CharField(default='P38D2XH1GFHST85V', max_length=32)),
                ('from_symbol', models.CharField(max_length=32)),
                ('to_symbol', models.CharField(default='CAD', max_length=32)),
            ],
            options={
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=('datasource.datasourcemixin',),
        ),
        migrations.RemoveField(
            model_name='alphavantagestocksource',
            name='function',
        ),
    ]