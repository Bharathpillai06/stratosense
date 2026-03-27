"""
Combined atmospheric profile generator and Flask routes.

Ties together interpolation + assimilation and exposes four endpoints:
  /atmosphere/profile          — full vertical profile, surface to 30 km
  /atmosphere/at/<altitude_m>  — single-altitude query for drone planning
  /atmosphere/density_altitude — current density altitude at ground level
  /atmosphere/status           — model mode, confidence, lapse rate source

Can run standalone (port 8081) for testing, or be registered as a Blueprint
on Person 1's Flask app via:
    from atmosphere import atmosphere_bp
    app.register_blueprint(atmosphere_bp)
"""

from flask import Blueprint, Flask, jsonify
from datetime import datetime, timezone
import os

from interpolation import (
    baseline_profile,
    generate_full_profile,
    calc_density_altitude,
)
from assimilation import update_lapse_rates, apply_observation_nudging

# ─── BLUEPRINT ───────────────────────────────────────────────────────────────

atmosphere_bp = Blueprint('atmosphere', __name__)

# ─── DATA ACCESS ─────────────────────────────────────────────────────────────
# These pull from Person 1's existing Synoptic + SondeHub integrations.
# When the data-gathering layer isn't available yet they fall back to
# hardcoded Columbus KCMH defaults so the model still runs.

_surface_cache = {
    'data': None,
    'fetched_at': None,
}

COLUMBUS_DEFAULTS = {
    'station_id': 'KCMH',
    'temp_c': 15.0,
    'dewpoint_c': 8.0,
    'pressure_hpa': 1013.25,
    'elev_m': 247,
    'wind_speed_ms': 3.0,
    'wind_dir_deg': 225,
}


def _parse_synoptic_obs(raw):
    """
    Extract surface dict from the Synoptic /v2/stations/latest response
    that Person 1's fetch_station_data() returns.
    """
    try:
        station = raw['STATION'][0]
        obs = station.get('OBSERVATIONS', {})

        temp = obs.get('air_temp_value_1', {}).get('value')
        dewpoint = obs.get('dew_point_temperature_value_1', {}).get('value')
        pressure = obs.get('sea_level_pressure_value_1', {}).get('value')
        wind_speed = obs.get('wind_speed_value_1', {}).get('value')
        wind_dir = obs.get('wind_direction_value_1', {}).get('value')
        elev = station.get('ELEVATION')

        if temp is None:
            return None

        return {
            'station_id': station.get('STID', 'KCMH'),
            'temp_c': float(temp),
            'dewpoint_c': float(dewpoint) if dewpoint is not None else float(temp) - 7,
            'pressure_hpa': float(pressure) if pressure is not None else 1013.25,
            'elev_m': float(elev) if elev is not None else 247,
            'wind_speed_ms': float(wind_speed) if wind_speed is not None else 3.0,
            'wind_dir_deg': float(wind_dir) if wind_dir is not None else 225,
        }
    except (KeyError, IndexError, TypeError):
        return None


def get_latest_surface_obs():
    """
    Try to fetch live surface data from Person 1's Synoptic endpoint.
    Falls back to hardcoded Columbus defaults.
    """
    import requests

    now = datetime.now(timezone.utc)

    if (_surface_cache['data'] is not None
            and _surface_cache['fetched_at'] is not None
            and (now - _surface_cache['fetched_at']).total_seconds() < 300):
        return dict(_surface_cache['data'])

    try:
        resp = requests.get(
            'http://localhost:8080/weather/KCMH', timeout=5)
        if resp.ok:
            parsed = _parse_synoptic_obs(resp.json())
            if parsed:
                _surface_cache['data'] = parsed
                _surface_cache['fetched_at'] = now
                return dict(parsed)
    except Exception:
        pass

    return dict(COLUMBUS_DEFAULTS)


def get_latest_balloon_data():
    """
    Grab the most recent balloon frames from Person 1's cache.
    Returns a list of frame dicts, or None if nothing recent.
    """
    import requests

    try:
        resp = requests.get(
            'http://localhost:8080/balloons', timeout=5)
        if not resp.ok:
            return None
        balloons = resp.json().get('balloons', [])
        if not balloons:
            return None

        nearest = min(
            balloons,
            key=lambda b: (
                (b.get('lat', 0) - 39.99) ** 2
                + (b.get('lon', 0) + 83.01) ** 2
            ),
        )

        serial = nearest.get('serial')
        if not serial:
            return None

        path_resp = requests.get(
            f'http://localhost:8080/balloon/{serial}', timeout=10)
        if not path_resp.ok:
            return None

        frames = path_resp.json().get('path', [])
        if frames:
            for f in frames:
                f['serial'] = serial
        return frames or None
    except Exception:
        return None


def calc_balloon_age(balloon):
    """Hours since the last frame in the balloon data."""
    if not balloon:
        return None
    try:
        last_dt = balloon[-1].get('datetime')
        if not last_dt:
            return None
        dt = datetime.fromisoformat(last_dt.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return round(age, 2)
    except (ValueError, TypeError, IndexError):
        return None


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@atmosphere_bp.route('/atmosphere/profile')
def atmosphere_profile():
    """Full atmospheric profile, surface to 30 km."""
    surface = get_latest_surface_obs()
    balloon = get_latest_balloon_data()

    if balloon:
        surface = update_lapse_rates(surface, balloon)

    profile = generate_full_profile(surface)

    if balloon:
        apply_observation_nudging(profile, balloon)

    age = calc_balloon_age(balloon)
    serial = balloon[0].get('serial') if balloon else None

    return jsonify({
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'surface_station': surface.get('station_id', 'KCMH'),
        'balloon_serial': serial,
        'balloon_age_hours': age,
        'assimilation_active': balloon is not None and age is not None and age < 6,
        'lapse_rate_source': (
            'observed' if surface.get('elr') is not None
            and surface.get('elr') != 6.5 else 'standard'),
        'elr_c_per_km': surface.get('elr', 6.5),
        'profile': profile,
    })


@atmosphere_bp.route('/atmosphere/at/<int:altitude_m>')
def atmosphere_at(altitude_m):
    """Single-altitude query for drone flight planning."""
    surface = get_latest_surface_obs()
    balloon = get_latest_balloon_data()
    if balloon:
        surface = update_lapse_rates(surface, balloon)
    level = baseline_profile(altitude_m, surface)
    return jsonify(level)


@atmosphere_bp.route('/atmosphere/density_altitude')
def density_altitude():
    """Current density altitude at ground level."""
    surface = get_latest_surface_obs()
    da = calc_density_altitude(
        surface['pressure_hpa'],
        surface['temp_c'],
        surface['dewpoint_c'],
    )
    return jsonify({
        'density_altitude_m': da,
        'density_altitude_ft': round(da * 3.281, 0),
        'conditions': {
            'temp_c': surface['temp_c'],
            'dewpoint_c': surface['dewpoint_c'],
            'pressure_hpa': surface['pressure_hpa'],
        },
    })


@atmosphere_bp.route('/atmosphere/status')
def atmosphere_status():
    """Model status for the dashboard header."""
    balloon = get_latest_balloon_data()
    age = calc_balloon_age(balloon)
    surface = get_latest_surface_obs()

    if balloon:
        surface = update_lapse_rates(surface, balloon)

    return jsonify({
        'mode': 'assimilated' if age is not None and age < 6 else 'interpolated',
        'balloon_age_hours': age,
        'lapse_rate_c_per_km': surface.get('elr', 6.5),
        'lapse_rate_source': 'observed' if surface.get('elr') else 'standard',
        'surface_station': surface.get('station_id', 'KCMH'),
        'confidence': (
            'high' if age is not None and age < 1
            else 'medium' if age is not None and age < 3
            else 'baseline'),
    })


# ─── STANDALONE SERVER ───────────────────────────────────────────────────────

if __name__ == '__main__':
    app = Flask(__name__)
    app.register_blueprint(atmosphere_bp)

    print('Starting atmospheric model server on port 8081...')
    print('Endpoints:')
    print('  GET /atmosphere/profile')
    print('  GET /atmosphere/at/<altitude_m>')
    print('  GET /atmosphere/density_altitude')
    print('  GET /atmosphere/status')
    app.run(host='0.0.0.0', port=8081, debug=True)
