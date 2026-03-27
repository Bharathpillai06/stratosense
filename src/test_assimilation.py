"""
Focused test suite for assimilation.py — Level 1 (lapse rate update)
and Level 2 (observation nudging).

Tests verify:
  - Dewpoint inverse-Magnus roundtrip consistency
  - Lapse rate derivation from realistic balloon data
  - Spatial weighting (Gaussian, 500m scale)
  - Temporal decay (linear, configurable max_age)
  - Blending of multiple observations
  - Full-profile nudging with realistic balloon ascents
  - Decay back to baseline when data goes stale
  - Edge cases (missing fields, boundary-layer noise, extreme values)

Run with:  cd src && python -m pytest test_assimilation.py -v
"""

import pytest
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import assimilation as assim
import interpolation as interp


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def surface():
    return {
        'station_id': 'KCMH',
        'temp_c': 20.0,
        'dewpoint_c': 12.0,
        'pressure_hpa': 1013.25,
        'elev_m': 247,
        'wind_speed_ms': 4.0,
        'wind_dir_deg': 270,
    }


def make_balloon_ascent(n=50, surface_alt=247, surface_temp=20.0,
                        lapse=7.5, rh_surface=65, rh_decay=0.02,
                        age_minutes=10):
    """Generate a realistic balloon ascent with configurable parameters."""
    now = datetime.now(timezone.utc)
    frames = []
    for i in range(n):
        alt = surface_alt + 100 * i
        delta_km = (alt - surface_alt) / 1000
        temp = surface_temp - lapse * delta_km
        rh = max(5, rh_surface * math.exp(-rh_decay * delta_km))
        frames.append({
            'alt': alt,
            'temp': round(temp, 1),
            'humidity': round(rh, 1),
            'datetime': (now - timedelta(minutes=age_minutes + n - i)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'serial': 'T_TEST',
            'lat': 39.99,
            'lon': -83.01,
        })
    return frames


# ═══════════════════════════════════════════════════════════════════════════════
# DEWPOINT INVERSE-MAGNUS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDewpointFromRH:
    def test_roundtrip_with_magnus(self):
        """calc_dewpoint_from_rh should be the inverse of calc_relative_humidity."""
        for temp in [-10, 0, 15, 25, 35]:
            for rh in [20, 50, 80, 100]:
                td = assim.calc_dewpoint_from_rh(temp, rh)
                rh_back = interp.calc_relative_humidity(temp, td)
                assert abs(rh_back - rh) < 0.5, f"Roundtrip failed at T={temp}, RH={rh}"

    def test_known_values(self):
        td = assim.calc_dewpoint_from_rh(30.0, 50.0)
        assert 18 < td < 20

        td = assim.calc_dewpoint_from_rh(0.0, 100.0)
        assert abs(td - 0.0) < 0.5

    def test_low_rh(self):
        td = assim.calc_dewpoint_from_rh(35.0, 5.0)
        assert td < 0

    def test_cold_temperature(self):
        td = assim.calc_dewpoint_from_rh(-20.0, 60.0)
        assert td < -20.0

    def test_returns_none_for_invalid_rh(self):
        assert assim.calc_dewpoint_from_rh(20.0, None) is None
        assert assim.calc_dewpoint_from_rh(20.0, 0) is None
        assert assim.calc_dewpoint_from_rh(20.0, -10) is None


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 1 — LAPSE RATE UPDATE
# ═══════════════════════════════════════════════════════════════════════════════

class TestLapseRateUpdate:
    def test_derives_elr_from_balloon(self, surface):
        frames = make_balloon_ascent(lapse=7.5)
        result = assim.update_lapse_rates(dict(surface), frames)
        assert 'elr' in result
        assert 6.5 < result['elr'] < 9.0

    def test_elr_matches_actual_lapse(self, surface):
        """If balloon cools at exactly 8.0 C/km, derived ELR should be ~8.0."""
        frames = make_balloon_ascent(lapse=8.0, surface_temp=20.0)
        result = assim.update_lapse_rates(dict(surface), frames)
        assert abs(result['elr'] - 8.0) < 0.5

    def test_stable_atmosphere_low_elr(self, surface):
        frames = make_balloon_ascent(lapse=4.0)
        result = assim.update_lapse_rates(dict(surface), frames)
        assert result['elr'] < 5.0

    def test_unstable_atmosphere_high_elr(self, surface):
        frames = make_balloon_ascent(lapse=9.5)
        result = assim.update_lapse_rates(dict(surface), frames)
        assert result['elr'] > 9.0

    def test_derives_dewpoint_lapse(self, surface):
        frames = make_balloon_ascent(rh_surface=65, rh_decay=0.02)
        result = assim.update_lapse_rates(dict(surface), frames)
        assert 'dewpoint_lapse' in result
        assert result['dewpoint_lapse'] >= 0.5

    def test_ignores_boundary_layer_frames(self, surface):
        """Frames below 500m AGL should not be used (too noisy)."""
        low_only = [
            {'alt': 300, 'temp': 19.0, 'humidity': 70},
            {'alt': 400, 'temp': 18.0, 'humidity': 68},
            {'alt': 500, 'temp': 17.0, 'humidity': 66},
        ]
        result = assim.update_lapse_rates(dict(surface), low_only)
        assert 'elr' not in result

    def test_ignores_upper_level_frames(self, surface):
        """Frames above 3000m AGL should not be used."""
        high_only = [
            {'alt': 4000, 'temp': -10.0, 'humidity': 30},
            {'alt': 5000, 'temp': -20.0, 'humidity': 20},
        ]
        result = assim.update_lapse_rates(dict(surface), high_only)
        assert 'elr' not in result

    def test_uses_first_stable_frame(self, surface):
        """Should use the first frame in the 500-3000m AGL band."""
        frames = [
            {'alt': 300, 'temp': 19.0, 'humidity': 70},
            {'alt': 800, 'temp': 15.0, 'humidity': 60},
            {'alt': 1500, 'temp': 10.0, 'humidity': 45},
        ]
        result = assim.update_lapse_rates(dict(surface), frames)
        ref_alt = 800
        expected_elr = (20.0 - 15.0) / ((ref_alt - 247) / 1000)
        assert abs(result['elr'] - expected_elr) < 0.1

    def test_does_not_mutate_without_data(self, surface):
        original = dict(surface)
        result = assim.update_lapse_rates(dict(surface), [])
        assert 'elr' not in result
        assert result['temp_c'] == original['temp_c']

    def test_handles_frames_with_none_alt(self, surface):
        frames = [
            {'alt': None, 'temp': 10.0, 'humidity': 50},
            {'alt': 1000, 'temp': 10.0, 'humidity': 50},
        ]
        result = assim.update_lapse_rates(dict(surface), frames)
        assert 'elr' in result

    def test_no_humidity_skips_dewpoint_lapse(self, surface):
        frames = [{'alt': 1000, 'temp': 10.0}]
        result = assim.update_lapse_rates(dict(surface), frames)
        assert 'elr' in result
        assert 'dewpoint_lapse' not in result


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 2 — OBSERVATION NUDGING: SPATIAL WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpatialWeighting:
    def test_gaussian_peaks_at_exact_altitude(self):
        """Observation at exact altitude should have maximum weight."""
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 0.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs)
        assert abs(val - (-10.0)) < 0.01

    def test_weight_drops_with_distance(self):
        """Same obs value at increasing distances — correction should weaken."""
        corrections = []
        for offset in [0, 100, 300, 500, 800]:
            obs = [{'alt': 2000 + offset, 'value': -10.0, 'age_hours': 0.0}]
            val, _ = assim.assimilated_value(2000, -5.0, obs)
            corrections.append(abs(val - (-5.0)))
        for i in range(1, len(corrections)):
            assert corrections[i] <= corrections[i - 1] + 0.01

    def test_500m_scale_length(self):
        """At 500m offset, confidence should be exp(-0.5) ≈ 0.607 of the peak.
        (Single-obs correction is always full innovation; only confidence scales.)"""
        obs_exact = [{'alt': 2000, 'value': -10.0, 'age_hours': 0.0}]
        obs_500m = [{'alt': 2500, 'value': -10.0, 'age_hours': 0.0}]

        _, conf_exact = assim.assimilated_value(2000, -5.0, obs_exact)
        _, conf_500m = assim.assimilated_value(2000, -5.0, obs_500m)

        ratio = conf_500m / conf_exact
        expected_ratio = math.exp(-0.5)
        assert abs(ratio - expected_ratio) < 0.05

    def test_1000m_cutoff(self):
        """Observations >= 1000m away should have zero influence."""
        obs = [{'alt': 3000, 'value': -20.0, 'age_hours': 0.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs)
        assert val == -5.0
        assert conf == 0.0

    def test_just_inside_1000m(self):
        """Observation at 999m offset should still contribute."""
        obs = [{'alt': 2999, 'value': -20.0, 'age_hours': 0.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs)
        assert val != -5.0
        assert conf > 0


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 2 — OBSERVATION NUDGING: TEMPORAL DECAY
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemporalDecay:
    def test_fresh_obs_full_weight(self):
        """age_hours=0 should give full temporal weight."""
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 0.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs)
        assert abs(val - (-10.0)) < 0.01

    def test_half_life_confidence(self):
        """At half the max age, temporal weight = 0.5 so confidence = 0.5."""
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 3.0}]
        _, conf = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
        assert abs(conf - 0.5) < 0.05

    def test_confidence_decays_linearly(self):
        """Confidence at 1h, 2h, 3h intervals should decrease linearly."""
        confs = []
        for age in [1.0, 2.0, 3.0, 4.0, 5.0]:
            obs = [{'alt': 2000, 'value': -10.0, 'age_hours': age}]
            _, conf = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
            confs.append(conf)
        for i in range(1, len(confs)):
            assert confs[i] < confs[i - 1]
        expected = [(1 - age / 6.0) for age in [1.0, 2.0, 3.0, 4.0, 5.0]]
        for actual, exp in zip(confs, expected):
            assert abs(actual - exp) < 0.05

    def test_at_max_age_zero_correction(self):
        """At exactly max_age, temporal weight = 0."""
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 6.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
        assert val == -5.0
        assert conf == 0.0

    def test_beyond_max_age_ignored(self):
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 8.0}]
        val, conf = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
        assert val == -5.0
        assert conf == 0.0

    def test_custom_max_age(self):
        """Shorter max_age should cause lower confidence (faster decay)."""
        obs = [{'alt': 2000, 'value': -10.0, 'age_hours': 2.0}]
        _, conf_long = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
        _, conf_short = assim.assimilated_value(2000, -5.0, obs, max_age_hours=3.0)
        assert conf_short < conf_long


# ═══════════════════════════════════════════════════════════════════════════════
# LEVEL 2 — BLENDING MULTIPLE OBSERVATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestObsBlending:
    def test_symmetric_obs_average(self):
        """Two obs equidistant above/below should average their values."""
        obs = [
            {'alt': 1800, 'value': -6.0, 'age_hours': 0.0},
            {'alt': 2200, 'value': -14.0, 'age_hours': 0.0},
        ]
        val, _ = assim.assimilated_value(2000, -5.0, obs)
        assert abs(val - (-10.0)) < 0.5

    def test_closer_obs_has_more_influence(self):
        """Closer observation should dominate the blend."""
        obs = [
            {'alt': 2050, 'value': -12.0, 'age_hours': 0.0},
            {'alt': 2800, 'value': -20.0, 'age_hours': 0.0},
        ]
        val, _ = assim.assimilated_value(2000, -5.0, obs)
        assert val < -5.0
        assert abs(val - (-12.0)) < abs(val - (-20.0))

    def test_fresher_obs_has_more_influence(self):
        """Fresher observation should dominate the blend."""
        obs = [
            {'alt': 2000, 'value': -12.0, 'age_hours': 0.5},
            {'alt': 2000, 'value': -20.0, 'age_hours': 4.5},
        ]
        val, _ = assim.assimilated_value(2000, -5.0, obs, max_age_hours=6.0)
        assert abs(val - (-12.0)) < abs(val - (-20.0))

    def test_many_obs_converge(self):
        """Dense observations should push the result very close to their mean."""
        obs = [
            {'alt': 1950 + i * 10, 'value': -10.0, 'age_hours': 0.0}
            for i in range(10)
        ]
        val, conf = assim.assimilated_value(2000, -5.0, obs)
        assert abs(val - (-10.0)) < 0.5
        assert conf > 0.8

    def test_conflicting_obs(self):
        """Opposite observations at same distance should roughly cancel out."""
        obs = [
            {'alt': 1900, 'value': -10.0, 'age_hours': 0.0},
            {'alt': 2100, 'value': 0.0, 'age_hours': 0.0},
        ]
        val, _ = assim.assimilated_value(2000, -5.0, obs)
        assert abs(val - (-5.0)) < 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# FULL PROFILE NUDGING
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullProfileNudging:
    def test_nudges_near_balloon_altitudes(self, surface):
        """Levels close to balloon obs should change; far levels should not."""
        profile = interp.generate_full_profile(surface, max_alt=5000, step=500)
        balloon = make_balloon_ascent(n=20, age_minutes=5)

        original_high = profile[-1]['temp_c']
        assim.apply_observation_nudging(profile, balloon)

        near_balloon = [l for l in profile if 500 < l['altitude_m'] < 2500]
        assert any(l['source'] == 'assimilated' for l in near_balloon)

        assert profile[-1]['temp_c'] == original_high

    def test_nudges_dewpoint_too(self, surface):
        profile = interp.generate_full_profile(surface, max_alt=2000, step=500)
        original_dps = [l['dewpoint_c'] for l in profile]

        balloon = make_balloon_ascent(n=20, age_minutes=5)
        assim.apply_observation_nudging(profile, balloon)

        new_dps = [l['dewpoint_c'] for l in profile]
        assert new_dps != original_dps

    def test_stale_balloon_weaker_nudge(self, surface):
        profile_fresh = interp.generate_full_profile(surface, max_alt=2000, step=500)
        profile_stale = interp.generate_full_profile(surface, max_alt=2000, step=500)

        fresh_balloon = make_balloon_ascent(n=20, age_minutes=5)
        stale_balloon = make_balloon_ascent(n=20, age_minutes=200)

        assim.apply_observation_nudging(profile_fresh, fresh_balloon)
        assim.apply_observation_nudging(profile_stale, stale_balloon)

        fresh_assimilated = sum(1 for l in profile_fresh if l['source'] == 'assimilated')
        stale_assimilated = sum(1 for l in profile_stale if l['source'] == 'assimilated')
        assert fresh_assimilated >= stale_assimilated

    def test_very_old_balloon_no_nudge(self, surface):
        """Balloon from 5 hours ago should produce zero nudging (max_age=4h)."""
        profile = interp.generate_full_profile(surface, max_alt=2000, step=500)
        original_temps = [l['temp_c'] for l in profile]

        old_balloon = make_balloon_ascent(n=20, age_minutes=360)
        assim.apply_observation_nudging(profile, old_balloon, max_age_hours=4.0)

        new_temps = [l['temp_c'] for l in profile]
        assert new_temps == original_temps

    def test_frames_without_datetime_treated_as_fresh(self, surface):
        """Missing datetime means age_hours=0, which gives full weight."""
        profile = interp.generate_full_profile(surface, max_alt=2000, step=500)
        frames = [
            {'alt': 1000, 'temp': -5.0, 'humidity': 40},
        ]
        assim.apply_observation_nudging(profile, frames)
        level_1000 = next(l for l in profile if l['altitude_m'] == 1247)
        assert level_1000['source'] == 'assimilated'

    def test_frames_missing_alt_skipped(self, surface):
        profile = interp.generate_full_profile(surface, max_alt=1000, step=100)
        frames = [
            {'alt': None, 'temp': -5.0, 'humidity': 40, 'datetime': '2026-03-27T12:00:00Z'},
        ]
        original_temps = [l['temp_c'] for l in profile]
        assim.apply_observation_nudging(profile, frames)
        new_temps = [l['temp_c'] for l in profile]
        assert new_temps == original_temps

    def test_frames_missing_temp_and_humidity_skipped(self, surface):
        profile = interp.generate_full_profile(surface, max_alt=1000, step=100)
        frames = [
            {'alt': 800, 'datetime': '2026-03-27T12:00:00Z'},
        ]
        original_temps = [l['temp_c'] for l in profile]
        assim.apply_observation_nudging(profile, frames)
        new_temps = [l['temp_c'] for l in profile]
        assert new_temps == original_temps


# ═══════════════════════════════════════════════════════════════════════════════
# END-TO-END: LEVEL 1 + LEVEL 2 COMBINED
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    def test_full_pipeline_improves_profile(self, surface):
        """Lapse rate update + nudging together should bring the profile
        closer to the balloon observations than pure interpolation."""
        balloon = make_balloon_ascent(n=30, lapse=8.0, age_minutes=5)

        surface_updated = assim.update_lapse_rates(dict(surface), balloon)
        profile = interp.generate_full_profile(surface_updated, max_alt=3000, step=100)
        assim.apply_observation_nudging(profile, balloon)

        baseline = interp.generate_full_profile(surface, max_alt=3000, step=100)

        errors_assimilated = []
        errors_baseline = []
        for frame in balloon:
            alt = frame['alt']
            actual_temp = frame['temp']

            level_assim = min(profile, key=lambda l: abs(l['altitude_m'] - alt))
            level_base = min(baseline, key=lambda l: abs(l['altitude_m'] - alt))

            errors_assimilated.append(abs(level_assim['temp_c'] - actual_temp))
            errors_baseline.append(abs(level_base['temp_c'] - actual_temp))

        avg_err_assim = sum(errors_assimilated) / len(errors_assimilated)
        avg_err_base = sum(errors_baseline) / len(errors_baseline)
        assert avg_err_assim < avg_err_base

    def test_assimilation_then_fallback(self, surface):
        """After assimilation, if balloon goes stale, profile should revert
        to interpolated-only behavior."""
        fresh_balloon = make_balloon_ascent(n=20, lapse=8.0, age_minutes=5)
        surface_updated = assim.update_lapse_rates(dict(surface), fresh_balloon)
        profile_assim = interp.generate_full_profile(surface_updated, max_alt=2000, step=500)
        assim.apply_observation_nudging(profile_assim, fresh_balloon)

        stale_balloon = make_balloon_ascent(n=20, lapse=8.0, age_minutes=400)
        profile_stale = interp.generate_full_profile(dict(surface), max_alt=2000, step=500)
        assim.apply_observation_nudging(profile_stale, stale_balloon, max_age_hours=4.0)

        for level in profile_stale:
            assert level['source'] == 'interpolated'

    def test_level1_persists_longer_than_level2(self, surface):
        """ELR update should still be active even when nudging has decayed."""
        balloon = make_balloon_ascent(n=20, lapse=8.0, age_minutes=250)

        surface_updated = assim.update_lapse_rates(dict(surface), balloon)
        assert 'elr' in surface_updated
        assert abs(surface_updated['elr'] - 8.0) < 1.0

        profile = interp.generate_full_profile(surface_updated, max_alt=2000, step=500)
        assim.apply_observation_nudging(profile, balloon, max_age_hours=4.0)

        assert all(l['source'] == 'interpolated' for l in profile)

        profile_default = interp.generate_full_profile(dict(surface), max_alt=2000, step=500)
        assert profile[2]['temp_c'] != profile_default[2]['temp_c']


# ═══════════════════════════════════════════════════════════════════════════════
# PARSE TIMESERIES FOR ASSIMILATION (data_pipeline helper)
# ═══════════════════════════════════════════════════════════════════════════════

from data_pipeline import parse_timeseries_for_assimilation


def _synoptic_timeseries_response(n=10, elev='247'):
    """Build a realistic Synoptic v2 /stations/timeseries response."""
    now = datetime.now(timezone.utc)
    timestamps = [
        (now - timedelta(minutes=12 * i)).strftime('%Y-%m-%dT%H:%M:%S+0000')
        for i in range(n)
    ][::-1]

    return {
        'SUMMARY': {'RESPONSE_CODE': 1},
        'STATION': [{
            'STID': 'KCMH',
            'ELEVATION': elev,
            'OBSERVATIONS': {
                'date_time': timestamps,
                'air_temp_set_1': [20.0 + 0.1 * i for i in range(n)],
                'dew_point_temperature_set_1': [12.0 + 0.05 * i for i in range(n)],
                'sea_level_pressure_set_1': [1013.25] * n,
                'wind_speed_set_1': [3.0 + 0.1 * i for i in range(n)],
                'wind_direction_set_1': [225.0] * n,
            },
        }],
    }


class TestParseTimeseries:
    def test_parses_all_records(self):
        raw = _synoptic_timeseries_response(n=10)
        parsed = parse_timeseries_for_assimilation(raw)
        assert len(parsed) == 10

    def test_record_fields(self):
        raw = _synoptic_timeseries_response(n=3)
        parsed = parse_timeseries_for_assimilation(raw)
        rec = parsed[0]
        assert 'datetime_utc' in rec
        assert 'temp_c' in rec
        assert 'dewpoint_c' in rec
        assert 'pressure_hpa' in rec
        assert 'wind_speed_ms' in rec
        assert 'wind_dir_deg' in rec
        assert 'elev_m' in rec
        assert rec['elev_m'] == 247.0

    def test_preserves_temperature_values(self):
        raw = _synoptic_timeseries_response(n=5)
        parsed = parse_timeseries_for_assimilation(raw)
        assert parsed[0]['temp_c'] == 20.0
        assert parsed[4]['temp_c'] == pytest.approx(20.4, abs=0.01)

    def test_skips_records_with_null_temp(self):
        raw = _synoptic_timeseries_response(n=5)
        raw['STATION'][0]['OBSERVATIONS']['air_temp_set_1'][2] = None
        parsed = parse_timeseries_for_assimilation(raw)
        assert len(parsed) == 4

    def test_handles_missing_optional_vars(self):
        raw = _synoptic_timeseries_response(n=3)
        del raw['STATION'][0]['OBSERVATIONS']['dew_point_temperature_set_1']
        del raw['STATION'][0]['OBSERVATIONS']['wind_speed_set_1']
        parsed = parse_timeseries_for_assimilation(raw)
        assert len(parsed) == 3
        assert parsed[0]['dewpoint_c'] is None
        assert parsed[0]['wind_speed_ms'] is None

    def test_empty_response_returns_empty_list(self):
        assert parse_timeseries_for_assimilation({}) == []
        assert parse_timeseries_for_assimilation({'STATION': []}) == []
        assert parse_timeseries_for_assimilation(None) == []

    def test_no_timestamps_returns_empty_list(self):
        raw = _synoptic_timeseries_response(n=3)
        raw['STATION'][0]['OBSERVATIONS']['date_time'] = []
        assert parse_timeseries_for_assimilation(raw) == []

    def test_string_elevation_parsed(self):
        raw = _synoptic_timeseries_response(n=1, elev='305.5')
        parsed = parse_timeseries_for_assimilation(raw)
        assert parsed[0]['elev_m'] == 305.5


# ═══════════════════════════════════════════════════════════════════════════════
# SURFACE TIMESERIES → NUDGING INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestSurfaceTimeseriesNudging:
    """Verify that surface timeseries observations are correctly folded
    into the assimilation pipeline when combined with balloon data."""

    def test_surface_obs_nudge_ground_level(self, surface):
        """Surface timeseries frames should nudge the ground-level layer."""
        profile = interp.generate_full_profile(surface, max_alt=2000, step=500)

        surface_frames = [
            {'alt': 247, 'temp': 22.0, 'humidity': 70,
             'datetime': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
        ]

        original_ground = profile[0]['temp_c']
        assim.apply_observation_nudging(profile, surface_frames)
        assert profile[0]['temp_c'] != original_ground
        assert profile[0]['source'] == 'assimilated'

    def test_surface_obs_dont_affect_high_altitudes(self, surface):
        """Ground-level obs at 247m should not nudge levels > 1247m."""
        profile = interp.generate_full_profile(surface, max_alt=3000, step=500)

        surface_frames = [
            {'alt': 247, 'temp': 30.0, 'humidity': 90,
             'datetime': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
        ]

        high_levels = [l for l in profile if l['altitude_m'] > 1500]
        original_temps = [l['temp_c'] for l in high_levels]

        assim.apply_observation_nudging(profile, surface_frames)

        new_temps = [l['temp_c'] for l in high_levels]
        assert new_temps == original_temps

    def test_combined_balloon_and_surface_obs(self, surface):
        """Merging balloon + surface timeseries should nudge both
        ground and mid-level layers."""
        profile = interp.generate_full_profile(surface, max_alt=3000, step=500)

        balloon_frames = make_balloon_ascent(n=20, age_minutes=5)
        surface_frames = [
            {'alt': 247, 'temp': 22.0, 'humidity': 70,
             'datetime': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
            {'alt': 247, 'temp': 21.5, 'humidity': 68,
             'datetime': (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')},
        ]

        combined = balloon_frames + surface_frames
        assim.apply_observation_nudging(profile, combined)

        assimilated = [l for l in profile if l['source'] == 'assimilated']
        assert len(assimilated) >= 3

    def test_older_surface_obs_weaker_nudge(self, surface):
        """A 3-hour-old surface obs should nudge less than a fresh one."""
        now = datetime.now(timezone.utc)

        fresh_frames = [
            {'alt': 247, 'temp': 25.0, 'humidity': 80,
             'datetime': now.strftime('%Y-%m-%dT%H:%M:%SZ')},
        ]
        old_frames = [
            {'alt': 247, 'temp': 25.0, 'humidity': 80,
             'datetime': (now - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')},
        ]

        prof_fresh = interp.generate_full_profile(surface, max_alt=1000, step=100)
        prof_old = interp.generate_full_profile(surface, max_alt=1000, step=100)

        assim.apply_observation_nudging(prof_fresh, fresh_frames)
        assim.apply_observation_nudging(prof_old, old_frames)

        fresh_ground = prof_fresh[0]['temp_c']
        old_ground = prof_old[0]['temp_c']
        baseline_ground = surface['temp_c']

        assert abs(fresh_ground - 25.0) <= abs(old_ground - 25.0)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
