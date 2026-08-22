"""WGS84 to EPSG:5179 (KGD2002 / Unified CS), without pyproj.

The handler needs exactly one projection: turn a map click into the grid's
coordinate system so it can be indexed. pyproj does that, but it costs 17 MB
in the deployment package -- 8.7 MB of which is a PROJ data directory holding
transformation grids for the whole world -- and it ships compiled extensions
that must be built for Lambda's Linux runtime rather than a developer's Mac.

Transverse Mercator is closed-form, so a single projection is about forty
lines of arithmetic with no data files and no binaries. That removes the
dependency, removes the cross-compilation step, and removes a class of
deployment failure where the package builds locally and crashes in the cloud.

WGS84 and KGD2002 both use GRS80 and agree to within a few centimetres in
Korea, so no datum shift is applied; at a 100 m grid cell that is invisible.

Verified against pyproj across the country -- see tests in
scripts/verify_projection.py.
"""

from __future__ import annotations

import math

# GRS80, shared by WGS84 and KGD2002.
A = 6378137.0
INV_F = 298.257222101
F = 1.0 / INV_F
E2 = F * (2.0 - F)

# EPSG:5179 "Korea Unified Belt" parameters.
LAT_ORIGIN = math.radians(38.0)
LON_ORIGIN = math.radians(127.5)
K0 = 0.9996
FALSE_EASTING = 1_000_000.0
FALSE_NORTHING = 2_000_000.0

_E1 = E2 / (1.0 - E2)  # second eccentricity squared


def _meridian_arc(lat: float) -> float:
    """Distance along the meridian from the equator to `lat`, in metres."""
    n1 = 1.0 - E2 / 4.0 - 3.0 * E2**2 / 64.0 - 5.0 * E2**3 / 256.0
    n2 = 3.0 * E2 / 8.0 + 3.0 * E2**2 / 32.0 + 45.0 * E2**3 / 1024.0
    n3 = 15.0 * E2**2 / 256.0 + 45.0 * E2**3 / 1024.0
    n4 = 35.0 * E2**3 / 3072.0
    return A * (
        n1 * lat
        - n2 * math.sin(2.0 * lat)
        + n3 * math.sin(4.0 * lat)
        - n4 * math.sin(6.0 * lat)
    )


def wgs84_to_grid(lon_deg: float, lat_deg: float) -> tuple[float, float]:
    """Project longitude/latitude in degrees to EPSG:5179 metres."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    # Radius of curvature in the prime vertical.
    nu = A / math.sqrt(1.0 - E2 * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = _E1 * cos_lat * cos_lat
    a_term = (lon - LON_ORIGIN) * cos_lat

    m = _meridian_arc(lat)
    m0 = _meridian_arc(LAT_ORIGIN)

    easting = FALSE_EASTING + K0 * nu * (
        a_term
        + (1.0 - t + c) * a_term**3 / 6.0
        + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * _E1) * a_term**5 / 120.0
    )
    northing = FALSE_NORTHING + K0 * (
        m
        - m0
        + nu
        * tan_lat
        * (
            a_term**2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c * c) * a_term**4 / 24.0
            + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * _E1)
            * a_term**6
            / 720.0
        )
    )
    return easting, northing


def grid_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Inverse of `wgs84_to_grid`. Returns (lon_deg, lat_deg)."""
    x = easting - FALSE_EASTING
    y = northing - FALSE_NORTHING

    m = _meridian_arc(LAT_ORIGIN) + y / K0
    e1 = (1.0 - math.sqrt(1.0 - E2)) / (1.0 + math.sqrt(1.0 - E2))
    mu = m / (A * (1.0 - E2 / 4.0 - 3.0 * E2**2 / 64.0 - 5.0 * E2**3 / 256.0))

    phi1 = (
        mu
        + (3.0 * e1 / 2.0 - 27.0 * e1**3 / 32.0) * math.sin(2.0 * mu)
        + (21.0 * e1**2 / 16.0 - 55.0 * e1**4 / 32.0) * math.sin(4.0 * mu)
        + (151.0 * e1**3 / 96.0) * math.sin(6.0 * mu)
        + (1097.0 * e1**4 / 512.0) * math.sin(8.0 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    c1 = _E1 * cos_phi1 * cos_phi1
    t1 = tan_phi1 * tan_phi1
    n1 = A / math.sqrt(1.0 - E2 * sin_phi1 * sin_phi1)
    r1 = A * (1.0 - E2) / (1.0 - E2 * sin_phi1 * sin_phi1) ** 1.5
    d = x / (n1 * K0)

    lat = phi1 - (n1 * tan_phi1 / r1) * (
        d**2 / 2.0
        - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * _E1) * d**4 / 24.0
        + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 * t1 - 252.0 * _E1 - 3.0 * c1 * c1)
        * d**6
        / 720.0
    )
    lon = LON_ORIGIN + (
        d
        - (1.0 + 2.0 * t1 + c1) * d**3 / 6.0
        + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1 + 8.0 * _E1 + 24.0 * t1 * t1)
        * d**5
        / 120.0
    ) / cos_phi1

    return math.degrees(lon), math.degrees(lat)
