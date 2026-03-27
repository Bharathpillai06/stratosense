"""
Data assimilation module for the StratoSense atmospheric model.

Two levels of correction:
  Level 1 — Parameter update: derive Environmental Lapse Rate and dew-point
            lapse rate from the first stable balloon reading.
  Level 2 — Observation nudging: correct individual altitude levels where
            balloon observations diverge from the interpolated baseline,
            with weights that decay in both altitude distance and time.
"""

import math
from interpolation import compute_elr


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def calc_dewpoint_from_rh(temp_c, rh):
    """Inverse Magnus: dew point from temperature and relative humidity."""
    if rh is None or rh <= 0:
        return None
    a = 17.67
    b = 243.5
    alpha = (a * temp_c) / (b + temp_c) + math.log(rh / 100)
    return (b * alpha) / (a - alpha)


# ─── LEVEL 1: LAPSE RATE UPDATE ─────────────────────────────────────────────

def update_lapse_rates(surface, balloon_frames):
    """
    Derive real lapse rates from ground station + balloon.
    Uses the first stable balloon reading (500-3000 m AGL) to avoid
    surface boundary-layer noise and upper-level complications.

    Mutates and returns the surface dict with updated 'elr' and
    'dewpoint_lapse' keys.
    """
    elev = surface['elev_m']
    stable = [
        f for f in balloon_frames
        if f.get('alt') is not None
        and f.get('temp') is not None
        and f['alt'] > elev + 500
        and f['alt'] < elev + 3000
    ]
    if not stable:
        return surface

    ref = stable[0]

    elr = compute_elr(
        surface['temp_c'], elev, ref['temp'], ref['alt'])
    surface['elr'] = round(elr, 2)

    if ref.get('humidity') and surface.get('dewpoint_c') is not None:
        Td_ref = calc_dewpoint_from_rh(ref['temp'], ref['humidity'])
        if Td_ref is not None:
            delta_z_km = (ref['alt'] - elev) / 1000
            if delta_z_km > 0:
                dp_lapse = (surface['dewpoint_c'] - Td_ref) / delta_z_km
                surface['dewpoint_lapse'] = round(max(dp_lapse, 0.5), 2)

    return surface


# ─── LEVEL 2: OBSERVATION NUDGING ───────────────────────────────────────────

def assimilated_value(altitude_m, background_value,
                      balloon_obs, max_age_hours=6.0):
    """
    Correct an interpolated value using nearby balloon observations.

    balloon_obs: list of {alt, value, age_hours}
    Returns: (corrected_value, confidence)
    """
    if not balloon_obs:
        return background_value, 0.0

    nearby = [
        o for o in balloon_obs
        if abs(o['alt'] - altitude_m) < 1000
        and o['age_hours'] < max_age_hours
    ]

    if not nearby:
        return background_value, 0.0

    total_w = 0.0
    weighted_innov = 0.0
    for obs in nearby:
        w_space = math.exp(
            -(obs['alt'] - altitude_m) ** 2 / (2 * 500 ** 2))
        w_time = max(0.0, 1.0 - obs['age_hours'] / max_age_hours)
        w = w_space * w_time
        weighted_innov += w * (obs['value'] - background_value)
        total_w += w

    if total_w == 0:
        return background_value, 0.0

    correction = weighted_innov / total_w
    confidence = min(total_w, 1.0)
    return background_value + correction, confidence


def apply_observation_nudging(profile, balloon_frames, max_age_hours=4.0):
    """
    Walk the profile list and nudge temp / dewpoint at each level using
    nearby balloon observations.  Modifies the profile dicts in place.
    """
    if not balloon_frames:
        return

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    temp_obs = []
    humidity_obs = []
    for f in balloon_frames:
        if f.get('alt') is None:
            continue
        age_hours = 0.0
        dt_str = f.get('datetime')
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                age_hours = (now - dt).total_seconds() / 3600
            except (ValueError, TypeError):
                pass
        if f.get('temp') is not None:
            temp_obs.append({
                'alt': f['alt'], 'value': f['temp'],
                'age_hours': age_hours,
            })
        if f.get('humidity') is not None:
            td = calc_dewpoint_from_rh(f.get('temp', 0), f['humidity'])
            if td is not None:
                humidity_obs.append({
                    'alt': f['alt'], 'value': td,
                    'age_hours': age_hours,
                })

    for level in profile:
        alt = level['altitude_m']

        new_temp, t_conf = assimilated_value(
            alt, level['temp_c'], temp_obs, max_age_hours)
        if t_conf > 0:
            level['temp_c'] = round(new_temp, 2)
            level['source'] = 'assimilated'

        new_td, td_conf = assimilated_value(
            alt, level['dewpoint_c'], humidity_obs, max_age_hours)
        if td_conf > 0:
            level['dewpoint_c'] = round(new_td, 2)
            level['source'] = 'assimilated'
