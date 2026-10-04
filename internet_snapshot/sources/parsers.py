"""Parsers for the raw files downloaded by :mod:`internet_snapshot.sources`."""

from __future__ import annotations

import bz2
import csv
import gzip
import ipaddress
import json
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

import numpy as np


def _open_text(path: Path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


# --- CrUX ------------------------------------------------------------------------------------

def load_crux(path: Path, max_rank: int = 10_000) -> list[tuple[str, int]]:
    """Return [(hostname, rank_bucket)] for origins whose rank bucket <= max_rank."""
    out = []
    with _open_text(path) as f:
        for row in csv.DictReader(f):
            rank = int(row["rank"])
            if rank > max_rank:
                continue
            origin = row["origin"]
            host = origin.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
            out.append((host, rank))
    return out


# --- Public Suffix List ----------------------------------------------------------------------

class PublicSuffixList:
    def __init__(self, rules: set[str], exceptions: set[str], wildcards: set[str]):
        self.rules, self.exceptions, self.wildcards = rules, exceptions, wildcards

    @classmethod
    def load(cls, path: Path) -> "PublicSuffixList":
        rules, exceptions, wildcards = set(), set(), set()
        with _open_text(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                rule = line.split()[0].lower()
                if rule.startswith("!"):
                    exceptions.add(rule[1:])
                elif rule.startswith("*."):
                    wildcards.add(rule[2:])
                else:
                    rules.add(rule)
        return cls(rules, exceptions, wildcards)

    def public_suffix(self, host: str) -> str:
        labels = host.lower().strip(".").split(".")
        for i in range(len(labels)):
            cand = ".".join(labels[i:])
            if cand in self.exceptions:
                return ".".join(labels[i + 1:])
            if cand in self.rules:
                return cand
            if i + 1 < len(labels) and ".".join(labels[i + 1:]) in self.wildcards:
                return cand
        return labels[-1]

    def registrable(self, host: str) -> str:
        host = host.lower().strip(".")
        suffix = self.public_suffix(host)
        if host == suffix:
            return host
        rest = host[: -len(suffix) - 1]
        return rest.rsplit(".", 1)[-1] + "." + suffix


# --- ASN metadata ----------------------------------------------------------------------------

def load_asninfo(path: Path) -> dict[int, dict]:
    out = {}
    with _open_text(path) as f:
        for row in csv.DictReader(f):
            try:
                asn = int(row["asn"])
            except (ValueError, KeyError):
                continue
            out[asn] = {"handle": row.get("handle", ""), "name": row.get("description", ""),
                        "country": (row.get("country-code") or "").upper() or None}
    return out


class OriginAsnTable:
    """IPv4 range -> origin ASN lookup (sapics origin-asn / iptoasn format)."""

    def __init__(self, starts: np.ndarray, ends: np.ndarray, asns: np.ndarray, names: dict[int, str]):
        self.starts, self.ends, self.asns, self.names = starts, ends, asns, names

    @classmethod
    def load(cls, path: Path) -> "OriginAsnTable":
        starts, ends, asns, names = [], [], [], {}
        with _open_text(path) as f:
            for row in csv.reader(f):
                if len(row) < 3:
                    continue
                try:
                    a = int(ipaddress.IPv4Address(row[0]))
                    b = int(ipaddress.IPv4Address(row[1]))
                    asn = int(row[2])
                except ValueError:
                    continue
                starts.append(a)
                ends.append(b)
                asns.append(asn)
                if len(row) > 3 and asn not in names:
                    names[asn] = row[3]
        order = np.argsort(starts)
        return cls(np.array(starts, dtype=np.int64)[order], np.array(ends, dtype=np.int64)[order],
                   np.array(asns, dtype=np.int64)[order], names)

    def lookup(self, ip: str) -> int | None:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if addr.version != 4:
            return None
        x = int(addr)
        i = bisect_right(self.starts, x) - 1
        if i >= 0 and self.starts[i] <= x <= self.ends[i]:
            return int(self.asns[i])
        return None

    def address_space(self) -> dict[int, int]:
        sizes = (self.ends - self.starts + 1).astype(np.int64)
        out: dict[int, int] = defaultdict(int)
        uniq, inv = np.unique(self.asns, return_inverse=True)
        sums = np.bincount(inv, weights=sizes)
        for asn, s in zip(uniq.tolist(), sums.tolist()):
            out[int(asn)] = int(s)
        return dict(out)


# --- Geography -------------------------------------------------------------------------------

def load_countries(path: Path) -> dict[str, dict]:
    out = {}
    with _open_text(path) as f:
        for row in csv.DictReader(f):
            try:
                out[row["country"].upper()] = {"lat": float(row["latitude"]), "lon": float(row["longitude"]),
                                               "name": row["name"]}
            except (ValueError, KeyError):
                continue
    return out


# --- Simple Icons ----------------------------------------------------------------------------

_SLUG_REPL = {"+": "plus", ".": "dot", "&": "and", "đ": "d", "ħ": "h", "ı": "i", "ĸ": "k", "ŀ": "l",
              "ł": "l", "ß": "ss", "ŧ": "t", "ø": "o"}


def simpleicons_slug(title: str) -> str:
    s = "".join(_SLUG_REPL.get(ch, ch) for ch in title.lower())
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if ch.isascii() and ch.isalnum())


def load_simpleicons(path: Path) -> dict[str, str]:
    """slug -> brand hex colour."""
    data = json.loads(Path(path).read_text())
    icons = data["icons"] if isinstance(data, dict) else data
    return {(i.get("slug") or simpleicons_slug(i["title"])): "#" + i.get("hex", "FFFFFF") for i in icons}


# --- CAIDA -----------------------------------------------------------------------------------

def load_caida_asrel(path: Path) -> tuple[list[tuple[int, int, int]], list[int]]:
    """Return ([(a, b, rel)], tier1_clique). rel -1: a is provider of b; 0: peers."""
    rels, clique = [], []
    with _open_text(path) as f:
        for line in f:
            if line.startswith("#"):
                if "input clique:" in line:
                    clique = [int(x) for x in line.split(":", 1)[1].split()]
                continue
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            try:
                rels.append((int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                continue
    return rels, clique


def load_caida_as2org(path: Path) -> dict[int, dict]:
    """ASN -> {org_id, org_name, country} from CAIDA's as-org2info."""
    orgs, asns, mode = {}, {}, None
    with _open_text(path) as f:
        for line in f:
            if line.startswith("# format:"):
                mode = "org" if "org_id|changed|org_name" in line or "org_name" in line else "aut"
                continue
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("|")
            if mode == "org" and len(p) >= 4:
                orgs[p[0]] = {"org_name": p[2], "country": p[3]}
            elif mode == "aut" and len(p) >= 4:
                try:
                    asns[int(p[0])] = p[3]
                except ValueError:
                    pass
    return {asn: {"org_id": oid, **orgs.get(oid, {})} for asn, oid in asns.items()}
