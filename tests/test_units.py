import math

import numpy as np
import pytest

from internet_snapshot.build.catalog import guess_role, heuristic_relationships
from internet_snapshot.geo import (azel_from_dir, country_from_domain, dir_from_azel, offset_dir, placement,
                                   region_for_country, tangent_frame)
from internet_snapshot.routing import ASGraph
from internet_snapshot.seed import load_seed
from internet_snapshot.sources.parsers import PublicSuffixList, simpleicons_slug


def test_unity_axes():
    # az=0, el=0 is straight ahead (+Z); az=90 is right (+X); el=90 is up (+Y)
    assert np.allclose(dir_from_azel(0, 0), [0, 0, 1])
    assert np.allclose(dir_from_azel(90, 0), [1, 0, 0])
    assert np.allclose(dir_from_azel(0, 90), [0, 1, 0], atol=1e-12)
    az, el = azel_from_dir(dir_from_azel(-123.4, 37.5))
    assert az == pytest.approx(-123.4) and el == pytest.approx(37.5)


def test_placement_matches_formula():
    p = placement(dir_from_azel(40, -20), 600)
    az, el, r = math.radians(p["az"]), math.radians(p["el"]), p["r"]
    expect = [r * math.cos(el) * math.sin(az), r * math.sin(el), r * math.cos(el) * math.cos(az)]
    assert np.allclose(p["pos"], expect, atol=0.02)


def test_tangent_frame_and_offset():
    u = dir_from_azel(10, 20)
    e, n = tangent_frame(u)
    assert abs(np.dot(e, u)) < 1e-9 and abs(np.dot(n, u)) < 1e-9 and abs(np.dot(e, n)) < 1e-9
    v = offset_dir(u, 1.0, 0.0)
    assert math.degrees(math.acos(np.clip(np.dot(u, v), -1, 1))) == pytest.approx(1.0, abs=1e-6)
    # pole fallback
    e, n = tangent_frame(np.array([0.0, 1.0, 0.0]))
    assert np.linalg.norm(e) == pytest.approx(1.0)


def test_psl():
    psl = PublicSuffixList({"com", "uk", "co.uk", "github.io", "jp"}, {"city.kawasaki.jp"}, {"kawasaki.jp"})
    assert psl.registrable("www.bbc.co.uk") == "bbc.co.uk"
    assert psl.registrable("m.youtube.com") == "youtube.com"
    assert psl.registrable("foo.github.io") == "foo.github.io"
    assert psl.registrable("a.b.kawasaki.jp") == "a.b.kawasaki.jp"
    assert psl.registrable("www.city.kawasaki.jp") == "city.kawasaki.jp"


def test_country_and_region():
    assert country_from_domain("bbc.co.uk") == "GB"
    assert country_from_domain("spiegel.de") == "DE"
    assert country_from_domain("example.com") is None
    assert region_for_country("BR") == "latin-america"
    assert region_for_country("JP") == "asia"


def test_simpleicons_slug():
    assert simpleicons_slug(".NET") == "dotnet"
    assert simpleicons_slug("Booking.com") == "bookingdotcom"
    assert simpleicons_slug("Google Drive") == "googledrive"


def test_seed_is_valid():
    seed = load_seed()
    assert seed.validate() == []
    assert len(seed.services) > 300


def test_guess_role():
    assert guess_role("Massachusetts Institute of Technology") == "education"
    assert guess_role("Hetzner Online GmbH hosting") == "hosting"
    assert guess_role("Comcast Cable Communications") == "access"


def test_heuristic_relationships_shape():
    roles = {3356: "tier1", 1299: "tier1", 7922: "access", 15169: "content", 64500: "enterprise"}
    cc = {3356: "US", 1299: "SE", 7922: "US", 15169: "US", 64500: "US"}
    rels = heuristic_relationships(roles, cc)
    pairs = {(a, b): r for a, b, r in rels}
    assert pairs.get((1299, 3356), pairs.get((3356, 1299))) == 0       # tier-1 mesh
    assert any(b == 7922 and r == -1 for a, b, r in rels)              # access buys transit
    assert (7922, 15169) in pairs and pairs[(7922, 15169)] == 0         # eyeball <-> content peering
    assert any(b == 64500 and r == -1 for a, b, r in rels)             # long tail has an upstream


def test_valley_free_routing():
    # 1 and 2 are tier-1 peers; 10 is a customer of 1, 20 a customer of 2; 30 a customer of 10.
    nodes = {a: {} for a in (1, 2, 10, 20, 30, 40)}
    rels = [[1, 2, 0], [1, 10, -1], [2, 20, -1], [10, 30, -1], [10, 40, 0]]
    g = ASGraph(nodes, rels, [1, 2])
    assert g.as_path(30, 20) == [30, 10, 1, 2, 20]
    # a peer route must not be re-exported upward: 40 cannot reach 20 via 10's peering
    assert g.as_path(40, 20) is None
    assert g.as_path(40, 30) == [40, 10, 30]
    assert [g.rel(a, b) for a, b in [(30, 10), (1, 2), (2, 20)]] == ["up", "peer", "down"]
    # unknown source is attached to fallback providers
    r = g.route(99, [20], "north-america")
    assert r["method"] == "fallback" and r["as_path"][0] == 99 and r["as_path"][-1] == 20
