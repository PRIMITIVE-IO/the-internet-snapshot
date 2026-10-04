"""Spherical geometry in the snapshot's Unity-convention coordinate system.

Left-handed, +Y up, +Z forward, +X right. Azimuth is measured from +Z toward +X;
elevation is the angle above the XZ plane. See docs/snapshot-format.md §2.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from .config import GEO_EL_SCALE


def dir_from_azel(az_deg, el_deg):
    """Unit direction(s) for azimuth/elevation in degrees. Accepts scalars or arrays."""
    az = np.radians(az_deg)
    el = np.radians(el_deg)
    return np.stack([np.cos(el) * np.sin(az), np.sin(el), np.cos(el) * np.cos(az)], axis=-1)


def azel_from_dir(v):
    """(az, el) in degrees for unit vector(s) v[..., 3]."""
    v = np.asarray(v, dtype=float)
    az = np.degrees(np.arctan2(v[..., 0], v[..., 2]))
    el = np.degrees(np.arcsin(np.clip(v[..., 1], -1.0, 1.0)))
    return az, el


def geo_dir(lat, lon):
    """Direction for a geographic location on a network shell (az = lon, el = lat * scale)."""
    return dir_from_azel(lon, np.asarray(lat) * GEO_EL_SCALE)


def normalize(v):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1.0, n)


def to_healpix_angles(v):
    """HEALPix (theta, phi) in radians for Unity directions: theta = colatitude, phi = azimuth."""
    v = normalize(v)
    theta = np.arccos(np.clip(v[..., 1], -1.0, 1.0))
    phi = np.mod(np.arctan2(v[..., 0], v[..., 2]), 2 * np.pi)
    return theta, phi


def from_healpix_angles(theta, phi):
    st = np.sin(theta)
    return np.stack([st * np.sin(phi), np.cos(theta), st * np.cos(phi)], axis=-1)


def stable_unit(key: str) -> float:
    """Deterministic pseudo-random number in [0, 1) derived from a string."""
    h = hashlib.blake2b(key.encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


def jitter_dir(v, key: str, max_deg: float):
    """Deterministically perturb a unit direction by up to max_deg degrees."""
    v = normalize(np.asarray(v, dtype=float))
    e, n = tangent_frame(v)
    ang = 2 * math.pi * stable_unit(key + ":a")
    rad = math.radians(max_deg) * math.sqrt(stable_unit(key + ":r"))
    return normalize(v + math.tan(rad) * (math.cos(ang) * e + math.sin(ang) * n))


def tangent_frame(u):
    """Tangent frame (e, n) at unit direction u, exactly as specified in snapshot-format.md §8.4."""
    u = np.asarray(u, dtype=float)
    ref = np.array([0.0, 1.0, 0.0])
    e = np.cross(ref, u)
    if np.linalg.norm(e) < 1e-6:
        e = np.cross(np.array([0.0, 0.0, 1.0]), u)
    e = e / np.linalg.norm(e)
    n = np.cross(u, e)
    return e, n


def offset_dir(u, dx_deg: float, dy_deg: float):
    """offset(u, dx, dy) from snapshot-format.md §8.4."""
    u = normalize(np.asarray(u, dtype=float))
    e, n = tangent_frame(u)
    return normalize(u + math.tan(math.radians(dx_deg)) * e + math.tan(math.radians(dy_deg)) * n)


def angle_between(a, b) -> float:
    a = normalize(a)
    b = normalize(b)
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1.0, 1.0))))


def placement(v, r: float) -> dict:
    """Position fields (r, az, el, pos) for a node at direction v and radius r."""
    v = normalize(np.asarray(v, dtype=float))
    az, el = azel_from_dir(v)
    p = v * r
    return {
        "r": round(float(r), 2),
        "az": round(float(az), 3),
        "el": round(float(el), 3),
        "pos": [round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2)],
    }


# --- countries -> regions -------------------------------------------------------------------

_REGION_COUNTRIES = {
    "north-america": "US CA GL BM PM",
    "latin-america": (
        "MX GT BZ SV HN NI CR PA CU JM HT DO PR BS BB TT AG DM GD KN LC VC AW CW SX BQ KY TC VG VI "
        "AI MS GP MQ BL MF CO VE EC PE BO BR PY UY AR CL GY SR GF FK"
    ),
    "europe": (
        "GB IE FR DE NL BE LU CH AT IT ES PT AD MC SM VA MT DK NO SE FI IS EE LV LT PL CZ SK HU SI "
        "HR BA RS ME MK AL GR BG RO MD UA BY RU LI GI FO AX GG JE IM XK CY EU"
    ),
    "middle-east": "TR SA AE QA KW BH OM YE IQ IR SY LB JO IL PS",
    "africa": (
        "EG LY TN DZ MA EH MR ML NE TD SD SS ER DJ ET SO KE UG RW BI TZ MZ MW ZM ZW BW NA ZA LS SZ "
        "MG MU SC KM YT RE AO CD CG GA GQ CM CF NG BJ TG GH CI LR SL GN GW SN GM CV ST SH BF"
    ),
    "asia": (
        "CN HK MO TW JP KR KP MN KZ KG TJ UZ TM AF PK IN NP BT BD LK MV MM TH LA KH VN MY SG BN ID "
        "PH TL AZ GE AM IO AP"
    ),
    "oceania": "AU NZ PG FJ SB VU NC PF WS TO KI TV NR PW FM MH GU MP AS CK NU TK WF NF PN",
}
COUNTRY_REGION = {cc: region for region, ccs in _REGION_COUNTRIES.items() for cc in ccs.split()}


def region_for_country(cc: str | None, default: str = "north-america") -> str:
    if not cc:
        return default
    return COUNTRY_REGION.get(cc.upper(), default)


# ccTLD -> country code for the cases where they differ.
CCTLD_EXCEPTIONS = {"uk": "GB", "eu": "EU", "ac": "SH", "su": "RU"}


def country_from_domain(domain: str) -> str | None:
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in CCTLD_EXCEPTIONS:
        return CCTLD_EXCEPTIONS[tld]
    if len(tld) == 2 and tld.isalpha():
        return tld.upper()
    return None
