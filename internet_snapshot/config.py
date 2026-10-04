"""Paths and global constants shared by the pipeline and the server."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "seed"
DATA_DIR = Path(os.environ.get("SNAPSHOT_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PUBLIC_DIR = Path(os.environ.get("SNAPSHOT_PUBLIC_DIR", ROOT / "public"))
SNAPSHOTS_DIR = PUBLIC_DIR / "snapshots"

USER_AGENT = os.environ.get(
    "SNAPSHOT_USER_AGENT",
    "the-internet-snapshot/0.1 (+https://github.com/PRIMITIVE-IO/the-internet-snapshot)",
)

# Shell radii (metres, Unity units). See docs/snapshot-format.md §2.
SHELLS = {"home": 0.0, "backbone": 300.0, "edge": 600.0, "services": 1000.0}
# Radius offsets inside the service shell (a little parallax between hierarchy levels).
SERVICE_RADIUS = {"realm": 1000.0, "category": 1000.0, "org": 1000.0, "service": 985.0}

# Elevation compression for geographic shells: el = latitude * GEO_EL_SCALE.
GEO_EL_SCALE = 0.85

# Network roles that live on the edge shell (everything else is on the backbone shell).
EDGE_ROLES = {"cloud", "cdn", "content", "hosting"}

# HEALPix orders used by the layout and the tiling.
SECTOR_ORDER = 4   # 3072 equal-area cells for realm/category sectors
TILE_ORDER = 1     # 48 tiles for LOD-3

SEED = 20261004    # deterministic layout seed
