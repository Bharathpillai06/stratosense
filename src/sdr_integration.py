"""
SDR data integration for StratoSense.

Provides /sdr/status to show whether the local Raspberry Pi + RTL-SDR
dongle is actively receiving a radiosonde, and compares the locally-
decoded telemetry against the global SondeHub feed.

When no Pi is connected the endpoint returns {receiving: false} — the
rest of the app continues to work from SondeHub data alone.
"""

import math
from flask import Blueprint, jsonify

sdr_bp = Blueprint('sdr', __name__)

SDR_LOG_PATH = '/tmp/radiosonde_auto_rx_latest.json'


def get_local_sdr_telemetry():
    """
    Read the latest frame written by radiosonde_auto_rx.
    Returns None when no Pi / no active reception.
    """
    import json
    try:
        with open(SDR_LOG_PATH) as f:
            data = json.load(f)
        if data.get('serial') and data.get('frames'):
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def get_sondehub_telemetry(serial):
    """Fetch the same balloon from the SondeHub global feed."""
    import requests
    try:
        resp = requests.get(
            f'http://localhost:8080/balloon/{serial}', timeout=5)
        if resp.ok:
            data = resp.json()
            return {'frames': data.get('path', [])}
    except Exception:
        pass
    return {'frames': []}


def compare_positions(local, sondehub):
    """
    Check whether the two latest positions are within 500 m of each other.
    Returns a dict with distance_m and a boolean match flag.
    """
    if not local or not sondehub:
        return {'match': False, 'distance_m': None}

    try:
        lat0, lon0 = math.radians(local['lat']), math.radians(local['lon'])
        lat1, lon1 = math.radians(sondehub['lat']), math.radians(sondehub['lon'])
        dlat = lat1 - lat0
        dlon = lon1 - lon0
        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat0) * math.cos(lat1) * math.sin(dlon / 2) ** 2)
        dist = 6371000 * 2 * math.asin(math.sqrt(a))
        return {'match': dist < 500, 'distance_m': round(dist, 1)}
    except (KeyError, TypeError):
        return {'match': False, 'distance_m': None}


@sdr_bp.route('/sdr/status')
def sdr_status():
    local_data = get_local_sdr_telemetry()
    if not local_data:
        return jsonify({'receiving': False})

    sondehub_data = get_sondehub_telemetry(local_data['serial'])

    local_latest = local_data.get('frames', [{}])[-1] if local_data.get('frames') else {}
    sh_latest = sondehub_data['frames'][-1] if sondehub_data['frames'] else {}

    return jsonify({
        'receiving': True,
        'serial': local_data['serial'],
        'frequency': local_data.get('frequency'),
        'local_frames': len(local_data.get('frames', [])),
        'sondehub_frames': len(sondehub_data['frames']),
        'position_match': compare_positions(local_latest, sh_latest),
        'feeds_into_model': True,
    })
