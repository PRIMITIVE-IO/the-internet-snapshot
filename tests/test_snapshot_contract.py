"""Conformance of the published snapshot with docs/snapshot-format.md."""

import json
import math
from pathlib import Path

import pytest

from internet_snapshot.build.catalog import NODE_KEYS
from internet_snapshot.build.export import tile_of
from internet_snapshot.config import SNAPSHOTS_DIR

LATEST = SNAPSHOTS_DIR / "latest.json"
pytestmark = pytest.mark.skipif(not LATEST.exists(), reason="no published snapshot")


@pytest.fixture(scope="module")
def snap():
    latest = json.loads(LATEST.read_text())
    root = SNAPSHOTS_DIR / latest["snapshot_id"]
    manifest = json.loads((root / "manifest.json").read_text())
    docs = []
    for lm in manifest["lods"]:
        if "file" in lm:
            docs.append(json.loads((root / lm["file"]).read_text()))
        else:
            t = lm["tiling"]
            for tile in lm["tiles"]:
                docs.append(json.loads((root / t["path"].format(order=t["order"], ipix=tile["ipix"])).read_text()))
    return latest, manifest, docs, root


def test_latest_points_to_manifest(snap):
    latest, manifest, _, root = snap
    assert manifest["snapshot_id"] == latest["snapshot_id"]
    assert (SNAPSHOTS_DIR / latest["manifest"]).exists()
    assert manifest["format_version"] == latest["format_version"] == "0.1"
    assert manifest["coordinate_system"]["up"] == "+Y"


def test_nodes_have_schema_and_consistent_positions(snap):
    _, manifest, docs, _ = snap
    shells = manifest["shells"]
    seen = set()
    for d in docs:
        assert d["snapshot_id"] == manifest["snapshot_id"]
        for n in d["nodes"]:
            assert tuple(n.keys()) == NODE_KEYS
            assert n["id"] not in seen
            seen.add(n["id"])
            assert n["lod"] == d["level"]
            az, el, r = math.radians(n["az"]), math.radians(n["el"]), n["r"]
            expect = [r * math.cos(el) * math.sin(az), r * math.sin(el), r * math.cos(el) * math.cos(az)]
            assert all(abs(a - b) < 0.05 for a, b in zip(n["pos"], expect)), n["id"]
            assert abs(r - shells[n["shell"]]) <= 20, n["id"]
            assert 0 <= n["size"] <= 1
            if d["tile"]:
                assert tile_of(n["pos"]) == d["tile"]["ipix"]
    assert manifest["stats"]["nodes"] == len(seen)


def test_edges_reference_loaded_nodes_and_respect_lod(snap):
    _, _, docs, _ = snap
    lod_of = {n["id"]: n["lod"] for d in docs for n in d["nodes"]}
    pos_of = {n["id"]: n["pos"] for d in docs for n in d["nodes"]}
    kinds = {"owns", "hosted_by", "operates", "transit", "peer", "member", "aggregate"}
    for d in docs:
        for e in d["edges"]:
            assert e["kind"] in kinds
            assert e["lod"] == d["level"]
            assert max(lod_of[e["source"]], lod_of[e["target"]]) <= e["lod"]
            assert e["a"] == pos_of[e["source"]] and e["b"] == pos_of[e["target"]]


def test_parents_exist_and_hierarchy(snap):
    _, _, docs, _ = snap
    nodes = {n["id"]: n for d in docs for n in d["nodes"]}
    for n in nodes.values():
        if n["parent"]:
            p = nodes[n["parent"]]
            assert p["lod"] <= n["lod"]
        if n["kind"] == "service":
            assert n["parent"].startswith(("org:", "cat:"))
            assert n["category"] in nodes
    # the realm/category/region skeleton is complete at the top levels
    assert sum(1 for n in nodes.values() if n["kind"] == "realm") == 10
    assert all(nodes[c]["lod"] == 1 for c in nodes if c.startswith("cat:"))


def test_service_shell_covers_full_sphere(snap):
    _, _, docs, _ = snap
    svc = [n for d in docs for n in d["nodes"] if n["shell"] == "services"]
    azs = [n["az"] for n in svc]
    els = [n["el"] for n in svc]
    assert min(azs) < -170 and max(azs) > 170
    assert min(els) < -75 and max(els) > 75


def test_anchors_and_aux_files(snap):
    _, manifest, docs, root = snap
    nodes = {n["id"] for d in docs for n in d["nodes"]}
    anchors = json.loads((root / manifest["files"]["anchors"]).read_text())
    assert anchors["google"]["anchor"] == "org:google"
    assert anchors["github"]["anchor"] == "svc:github.com"
    for a in anchors.values():
        assert a["anchor"] in nodes
        assert all(v in nodes for v in a["products"].values())
    domains = json.loads((root / manifest["files"]["domains"]).read_text())
    assert domains["mail.google.com"] == "svc:gmail.com"
    assert all(v in nodes for v in domains.values())
    asg = json.loads((root / manifest["files"]["asgraph"]).read_text())
    assert asg["tier1"] and asg["rels"]
    assert all(v["id"] in nodes for v in asg["nodes"].values())
