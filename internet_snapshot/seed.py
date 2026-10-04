"""Load the curated seed catalogue in ``seed/``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import SEED_DIR


def _read_psv(path: Path, ncols: int) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (ncols - len(parts))
        rows.append(parts[:ncols])
    return rows


def _csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


@dataclass
class SeedService:
    domain: str
    label: str
    category: str
    org: str
    aliases: list[str]
    icon: str | None
    hosted: list[int]


@dataclass
class SeedOrg:
    slug: str
    label: str
    country: str | None
    asns: list[int]
    category: str | None
    icon: str | None


@dataclass
class SeedNetwork:
    asn: int
    label: str
    role: str
    country: str | None
    org: str | None


@dataclass
class SeedIxp:
    slug: str
    label: str
    city: str
    country: str
    lat: float
    lon: float


@dataclass
class Seed:
    taxonomy: dict
    services: list[SeedService]
    orgs: dict[str, SeedOrg]
    networks: dict[int, SeedNetwork]
    ixps: list[SeedIxp]
    categories: dict[str, dict] = field(default_factory=dict)  # slug -> {label, realm, color}

    def validate(self) -> list[str]:
        errors = []
        for s in self.services:
            if s.category not in self.categories:
                errors.append(f"service {s.domain}: unknown category {s.category!r}")
        for o in self.orgs.values():
            if o.category and o.category not in self.categories:
                errors.append(f"org {o.slug}: unknown category {o.category!r}")
        roles = {r["id"] for r in self.taxonomy["network_roles"]}
        for n in self.networks.values():
            if n.role not in roles:
                errors.append(f"AS{n.asn}: unknown role {n.role!r}")
            if n.org and n.org not in self.orgs:
                errors.append(f"AS{n.asn}: unknown org {n.org!r}")
        seen = {}
        for s in self.services:
            for d in [s.domain, *s.aliases]:
                if d in seen:
                    errors.append(f"domain {d} listed by both {seen[d]} and {s.domain}")
                seen[d] = s.domain
        return errors


def load_seed(seed_dir: Path = SEED_DIR) -> Seed:
    taxonomy = json.loads((seed_dir / "taxonomy.json").read_text())
    categories = {}
    for realm in taxonomy["realms"]:
        for c in realm["categories"]:
            categories[c["slug"]] = {"label": c["label"], "realm": realm["slug"], "color": realm["color"]}

    services = [
        SeedService(domain=r[0].lower(), label=r[1], category=r[2], org=r[3], aliases=[a.lower() for a in _csv(r[4])],
                    icon=r[5] or None, hosted=[int(x) for x in _csv(r[6])])
        for r in _read_psv(seed_dir / "services.psv", 7)
    ]
    orgs = {
        r[0]: SeedOrg(slug=r[0], label=r[1], country=r[2] or None, asns=[int(x) for x in _csv(r[3])],
                      category=r[4] or None, icon=r[5] or None)
        for r in _read_psv(seed_dir / "orgs.psv", 6)
    }
    networks = {
        int(r[0]): SeedNetwork(asn=int(r[0]), label=r[1], role=r[2], country=r[3] or None, org=r[4] or None)
        for r in _read_psv(seed_dir / "networks.psv", 5)
    }
    ixps = [
        SeedIxp(slug=r[0], label=r[1], city=r[2], country=r[3], lat=float(r[4]), lon=float(r[5]))
        for r in _read_psv(seed_dir / "ixps.psv", 6)
    ]
    return Seed(taxonomy=taxonomy, services=services, orgs=orgs, networks=networks, ixps=ixps,
                categories=categories)
