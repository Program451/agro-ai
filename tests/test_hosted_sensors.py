from datetime import datetime, timezone, timedelta
import json
from unittest.mock import Mock

import pytest
import requests

from backend import sensors


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(sensors, 'DB_PATH', tmp_path / 'sensors.sqlite3')
    monkeypatch.setattr(sensors, 'feed_checked_at', float('-inf'))
    monkeypatch.delenv('AGRO_SENSOR_FEED_URL', raising=False)


def packet(stamp, temperature=19.6):
    return {'received_at': stamp.isoformat(), 'reading': {
        'device_id': 'esp32-hosting', 'temperature_c': temperature,
        'humidity_pct': 35, 'pressure_hpa': 951.39, 'altitude_m': 528.25,
        'rain_raw': 2448, 'soil_raw': 0}}


def test_old_packets_stay_old_and_polling_does_not_duplicate():
    stamp = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    packets = [packet(stamp), packet(stamp + timedelta(seconds=5), 20)]
    assert sensors.import_hosted_samples(packets) == 2
    assert sensors.import_hosted_samples(packets) == 0
    data = sensors.latest_reading()
    assert data['status'] == 'stale' and data['age_seconds'] > 86400
    assert data['reading']['pressure_hpa'] == 951.39
    assert 'soil_raw' not in data['reading']
    # A late download of older rows must not replace the newest measurement.
    sensors.import_hosted_samples([packet(stamp - timedelta(days=1), 50)])
    assert sensors.latest_reading() == data


def test_hosting_context_uses_original_timezone_and_no_future_packets():
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(minutes=3)
    local = earlier.astimezone(timezone(timedelta(hours=5)))
    samples = [packet(local, 18), packet(now - timedelta(seconds=5), 20),
               packet(now + timedelta(minutes=10), 80)]
    assert sensors.import_hosted_samples(samples) == 2
    context = sensors.context_at(now)
    assert 'soil_raw' not in context['reading']
    assert context['status'] == 'live' and context['sample_count'] == 2
    assert context['trends']['temperature_c']['delta'] == 2
    assert sensors.context_at(earlier)['reading']['temperature_c'] == 18


def test_bad_data_is_not_imported_and_direct_esp32_still_wins():
    stamp = datetime.now(timezone.utc) - timedelta(hours=1)
    bad = packet(stamp); bad['reading']['pressure_hpa'] = 9.51
    unknown = packet(stamp); unknown['reading']['device_id'] = 'other'
    naive = packet(stamp.replace(tzinfo=None))
    assert sensors.import_hosted_samples([bad, unknown, naive, {}]) == 0
    sensors.save_reading(sensors.SensorReading(temperature_c=22, soil_raw=0))
    sensors.import_hosted_samples([packet(stamp)])
    assert sensors.latest_reading()['reading']['device_id'] == 'esp32'


def test_feed_sync_is_bounded_cached_and_does_not_send_tokens(monkeypatch):
    monkeypatch.setenv('AGRO_SENSOR_FEED_URL', 'https://station.example/sensor-feed.php')
    content = json.dumps({'source': 'hosting', 'samples': [
        packet(datetime.now(timezone.utc) - timedelta(seconds=10))]}).encode()
    response = Mock(status_code=200)
    response.iter_content.return_value = [content]
    manager = Mock()
    manager.__enter__ = Mock(return_value=response)
    manager.__exit__ = Mock(return_value=False)
    get = Mock(return_value=manager)
    monkeypatch.setattr(sensors.requests, 'get', get)
    assert 'soil_raw' not in sensors.latest_reading()['reading']
    sensors.context_at(datetime.now(timezone.utc))
    assert get.call_count == 1
    assert 'headers' not in get.call_args.kwargs
    assert get.call_args.kwargs['allow_redirects'] is False
    monkeypatch.setattr(sensors, 'feed_checked_at', float('-inf'))
    get.side_effect = requests.Timeout()
    assert sensors.latest_reading()['reading']['pressure_hpa'] == 951.39


def test_legacy_rows_do_not_expose_soil_or_duplicate_on_import():
    now = datetime.now(timezone.utc)
    packets = [packet(now - timedelta(minutes=3), 18), packet(now - timedelta(seconds=5), 20)]
    packets[0]['reading']['soil_raw'] = 3500
    packets[1]['reading']['rain_raw'] = 0
    # Simulate the database written before the uninstalled sensor was removed.
    with sensors.connect() as db:
        for sample in packets:
            db.execute('INSERT INTO readings(received_at,payload) VALUES (?,?)',
                       (sample['received_at'], json.dumps(sample['reading'])))
    assert sensors.import_hosted_samples(packets) == 0
    latest = sensors.latest_reading()['reading']
    assert 'soil_raw' not in latest and latest['rain_raw'] == 0
    context = sensors.context_at(now)
    assert context['sample_count'] == 2
    assert context['trends']['temperature_c']['delta'] == 2
    assert 'soil_raw' not in context['reading']
    assert 'soil_raw' not in context['units'] and 'soil_raw' not in context['trends']
    assert all('soil_raw' not in sample for sample in context['samples'])
