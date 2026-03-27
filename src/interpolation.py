"""
Vertical interpolation engine for the StratoSense atmospheric model.

Deterministic physics formulas that produce continuous atmospheric profiles
(temperature, pressure, humidity, wind, density altitude) as functions of
altitude, anchored by real-time surface observations.
"""

import math


# ─── TEMPERATURE ─────────────────────────────────────────────────────────────

def interpolate_temperature(altitude_m, surface_temp_c,
                            surface_elev_m, lapse_rate_c_per_km=6.5):
    """
    Lapse-rate interpolation for temperature.
    Falls back to ISA standard 6.5 C/km when no observed ELR is available.
    """
    delta_z_km = (altitude_m - surface_elev_m) / 1000
    return surface_temp_c - lapse_rate_c_per_km * delta_z_km


def compute_elr(surface_temp_c, surface_elev_m,
                balloon_temp_c, balloon_alt_m):
    """
    Derive the Environmental Lapse Rate from ground station
    + first stable balloon reading.
    """
    delta_z_km = (balloon_alt_m - surface_elev_m) / 1000
    if delta_z_km <= 0:
        return 6.5
    return (surface_temp_c - balloon_temp_c) / delta_z_km


# ─── PRESSURE ────────────────────────────────────────────────────────────────

def interpolate_pressure(altitude_m, surface_pressure_hpa,
                         surface_temp_c, surface_elev_m,
                         lapse_rate=6.5):
    """
    Barometric formula using T_avg (mean of surface and target temperature
    in Kelvin) for accuracy across the layer.
    """
    g = 9.80665
    M = 0.0289644
    R = 8.31447

    T_target_c = interpolate_temperature(
        altitude_m, surface_temp_c, surface_elev_m, lapse_rate)

    T_avg_K = ((surface_temp_c + T_target_c) / 2) + 273.15

    delta_z = altitude_m - surface_elev_m
    return surface_pressure_hpa * math.exp(
        -g * M * delta_z / (R * T_avg_K)
    )


# ─── HUMIDITY ────────────────────────────────────────────────────────────────

def interpolate_dewpoint(altitude_m, surface_dewpoint_c,
                         surface_elev_m, dewpoint_lapse=2.0):
    """
    Dew point lapse rate interpolation.
    Default 2 C/km is typical; balloon data can refine this.
    """
    delta_z_km = (altitude_m - surface_elev_m) / 1000
    return surface_dewpoint_c - dewpoint_lapse * delta_z_km


def calc_relative_humidity(temp_c, dewpoint_c):
    """
    August-Roche-Magnus approximation for RH from temperature and dew point.
    """
    a = 17.625
    b = 243.04
    exponent = (a * dewpoint_c / (b + dewpoint_c)) - (a * temp_c / (b + temp_c))
    exponent = max(min(exponent, 10), -10)
    rh = 100 * math.exp(exponent)
    return min(max(rh, 0), 100)


def interpolate_humidity(altitude_m, surface_temp_c,
                         surface_dewpoint_c, surface_elev_m,
                         temp_lapse=6.5, dewpoint_lapse=2.0):
    """
    Full humidity interpolation: dew point lapse + Magnus.
    """
    T_z = interpolate_temperature(
        altitude_m, surface_temp_c, surface_elev_m, temp_lapse)
    Td_z = interpolate_dewpoint(
        altitude_m, surface_dewpoint_c, surface_elev_m, dewpoint_lapse)
    return calc_relative_humidity(T_z, Td_z)


# ─── WIND ────────────────────────────────────────────────────────────────────

def interpolate_wind(altitude_m, surface_wind_ms,
                     surface_dir_deg, surface_elev_m):
    """
    Boundary layer (0-1500m AGL): logarithmic profile.
    Free atmosphere (1500m+ AGL): power law.
    Direction veers ~30 deg through the boundary layer (Ekman spiral).
    """
    z0 = 0.1
    z_ref = 10
    z_bl = 1500
    agl = max(altitude_m - surface_elev_m, 10)

    if agl <= z_bl:
        speed = surface_wind_ms * (
            math.log(agl / z0) / math.log(z_ref / z0))
        veer = 30 * (agl / z_bl)
        direction = (surface_dir_deg + veer) % 360
    else:
        speed_at_bl = surface_wind_ms * (
            math.log(z_bl / z0) / math.log(z_ref / z0))
        speed = speed_at_bl * (agl / z_bl) ** 0.2
        direction = (surface_dir_deg + 30) % 360

    return {'speed_ms': round(speed, 1),
            'direction_deg': round(direction, 1)}


# ─── DENSITY ALTITUDE ────────────────────────────────────────────────────────

def calc_vapor_pressure(dewpoint_c):
    """Actual vapor pressure from dew point (Magnus formula)."""
    td = max(dewpoint_c, -80.0)
    return 6.112 * math.exp(17.67 * td / (td + 243.5))


def calc_virtual_temperature(temp_c, dewpoint_c, pressure_hpa):
    """Virtual temperature in Kelvin, accounting for moisture."""
    e = calc_vapor_pressure(dewpoint_c)
    T_K = temp_c + 273.15
    return T_K / (1 - 0.378 * e / pressure_hpa)


def calc_air_density(pressure_hpa, virtual_temp_K):
    """Air density in kg/m^3."""
    R_specific = 287.05
    P_pa = pressure_hpa * 100
    return P_pa / (R_specific * virtual_temp_K)


def calc_density_altitude(pressure_hpa, temp_c, dewpoint_c):
    """
    Density altitude: the altitude in the standard atmosphere
    with the same air density as the current conditions.
    """
    T_virt = calc_virtual_temperature(temp_c, dewpoint_c, pressure_hpa)
    rho = calc_air_density(pressure_hpa, T_virt)

    rho_0 = 1.225
    H = 8500
    density_alt_m = -H * math.log(rho / rho_0)
    return round(density_alt_m, 1)


# ─── FULL PROFILE ────────────────────────────────────────────────────────────

def baseline_profile(altitude_m, surface):
    """
    Complete atmospheric state at a given altitude.

    surface dict keys:
        temp_c, dewpoint_c, pressure_hpa, elev_m,
        wind_speed_ms, wind_dir_deg,
        elr (optional), dewpoint_lapse (optional)
    """
    elr = surface.get('elr', 6.5)
    dp_lapse = surface.get('dewpoint_lapse', 2.0)

    T = interpolate_temperature(
        altitude_m, surface['temp_c'], surface['elev_m'], elr)
    P = interpolate_pressure(
        altitude_m, surface['pressure_hpa'],
        surface['temp_c'], surface['elev_m'], elr)
    Td = interpolate_dewpoint(
        altitude_m, surface['dewpoint_c'],
        surface['elev_m'], dp_lapse)
    RH = calc_relative_humidity(T, Td)
    wind = interpolate_wind(
        altitude_m, surface['wind_speed_ms'],
        surface['wind_dir_deg'], surface['elev_m'])
    T_virt = calc_virtual_temperature(T, Td, P)
    rho = calc_air_density(P, T_virt)
    density_alt = calc_density_altitude(P, T, Td)

    return {
        'altitude_m': altitude_m,
        'temp_c': round(T, 2),
        'dewpoint_c': round(Td, 2),
        'pressure_hpa': round(P, 2),
        'humidity_pct': round(RH, 1),
        'wind': wind,
        'virtual_temp_K': round(T_virt, 2),
        'air_density_kg_m3': round(rho, 4),
        'density_altitude_m': density_alt,
        'source': 'interpolated',
    }


def generate_full_profile(surface, max_alt=30000, step=100):
    """Sweep from surface elevation to max_alt in `step`-metre increments."""
    altitudes = range(int(surface['elev_m']), max_alt + 1, step)
    return [baseline_profile(alt, surface) for alt in altitudes]
