"""Assemble the snapshot graph (nodes and edges) from the seed catalogue and public datasets.

The output carries no positions yet; those come from :mod:`layout`. Node dicts use the public
schema keys from docs/snapshot-format.md §4.1. Keys starting with ``_`` are internal and are
stripped on export.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..config import EDGE_ROLES
from ..geo import country_from_domain, region_for_country
from ..glyphs import CATEGORY_GLYPH, KIND_GLYPH, REALM_GLYPH, ROLE_GLYPH
from ..seed import Seed
from ..sources import SOURCES
from ..sources import parsers as P

NODE_KEYS = ("id", "kind", "label", "lod", "parent", "realm", "category", "org", "region", "role", "shell",
             "r", "az", "el", "pos", "size", "color", "rank", "domain", "asn", "country", "icon", "url",
             "glyph", "portal")


def new_node(id: str, kind: str, label: str, **kw) -> dict:
    n = {k: None for k in NODE_KEYS}
    n.update(id=id, kind=kind, label=label)
    n.update(kw)
    return n


@dataclass
class Catalog:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tier1: list[int] = field(default_factory=list)
    relationship_source: str = "heuristic-seed"
    rels: list[tuple[int, int, int]] = field(default_factory=list)  # (a, b, -1 a provides b | 0 peers)

    def add(self, node: dict) -> dict:
        self.nodes[node["id"]] = node
        return node

    def edge(self, source: str, target: str, kind: str, weight: float = 0.5, **kw) -> None:
        e = {"source": source, "target": target, "kind": kind, "lod": None, "weight": round(weight, 3),
             "count": None}
        e.update(kw)
        self.edges.append(e)

    def of_kind(self, kind: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["kind"] == kind]


@dataclass
class BuildOptions:
    crux_max_rank: int = 10_000
    longtail_networks: int = 1500
    resolve_dns: bool = False
    use_caida: bool = False


# --- long-tail heuristics -------------------------------------------------------------------

_GOV_RE = re.compile(r"(^|\.)(gov|mil|gob|gouv|go|gc|govt|gv)(\.[a-z]{2})?$")
_EDU_RE = re.compile(r"(^|\.)(edu|ac)(\.[a-z]{2})?$")
_ADULT = ("porn", "xxx", "sex", "xvideo", "xhamster", "hentai", "nsfw", "onlyfans", "chaturbate", "stripchat",
          "bongacams", "livejasmin", "xnxx", "redtube", "youporn", "spankbang", "eporner", "rule34", "brazzers",
          "fapello", "hanime", "camsoda", "erome", "motherless", "pornhub", "tnaflix", "javhd", "missav")
_KEYWORDS = [
    ("news", ("news", "times", "post", "daily", "journal", "herald", "tribune", "gazette", "press", "weather",
              "magazine", "noticias", "zeitung", "giornale")),
    ("banking", ("bank", "credit", "finance", "invest", "insur", "loan", "broker", "trading")),
    ("gaming", ("game", "casino", "poker", "slot", "bet365", "betting", "esport", "lotto", "jackpot")),
    ("video", ("movie", "film", "anime", "stream", "video", "tube", "drama", "cinema", "series")),
    ("music", ("music", "radio", "lyrics", "song")),
    ("shopping", ("shop", "store", "mart", "deals", "outlet", "fashion", "market")),
    ("travel", ("travel", "hotel", "flight", "booking", "rail", "airline", "tour")),
    ("health", ("health", "clinic", "pharma", "hospital", "medic", "doctor")),
    ("business", ("job", "career", "recruit", "hiring")),
    ("education", ("learn", "school", "univ", "college", "course", "academy", "tutor")),
    ("ai", ("gpt", "ai.", "chatbot")),
    ("forums", ("forum", "board", "community")),
]


def guess_category(domain: str, psl: P.PublicSuffixList) -> tuple[str, str]:
    """(category slug, source) for a domain we know nothing about. The source is heuristic or default."""
    suffix = psl.public_suffix(domain)
    brand = domain[: -len(suffix) - 1] if domain != suffix else domain
    if any(k in domain for k in _ADULT):
        return "adult", "heuristic"
    if _GOV_RE.search(suffix) or suffix in ("gov", "mil"):
        return "government", "heuristic"
    if _EDU_RE.search(suffix):
        return "education", "heuristic"
    probe = brand + "."
    for cat, words in _KEYWORDS:
        if any(w in probe for w in words):
            return cat, "heuristic"
    return "web", "default"


def popularity(rank: int | None) -> float:
    """CrUX rank bucket -> 0..1 popularity."""
    if rank is None:
        return 0.35
    return {1000: 1.0, 5000: 0.72, 10000: 0.55, 50000: 0.42, 100000: 0.36}.get(rank, 0.3)


_ROLE_PATTERNS = [
    ("education", re.compile(r"univ|college|school|educat|research|academ|institut|\bedu\b|campus|polytech", re.I)),
    ("government", re.compile(r"government|ministry|ministerio|\bdod\b|department of|federal|agency|"
                              r"\bdisa\b|defense|military|national .* (center|centre)", re.I)),
    ("hosting", re.compile(r"hosting|host|cloud|server|data ?cent|datacenter|colo|vps|dedicated|compute|cdn", re.I)),
    ("access", re.compile(r"telecom|telekom|telecomunica|broadband|cable|mobile|wireless|fiber|fibre|"
                          r"communications|\bisp\b|internet|telefon|\btel\b|net(work)?s?\b|celular|movil|"
                          r"vodafone|orange|tele", re.I)),
]


def guess_role(name: str) -> str:
    for role, rx in _ROLE_PATTERNS:
        if rx.search(name or ""):
            return role
    return "enterprise"


def clean_as_name(name: str, handle: str = "") -> str:
    name = (name or "").strip()
    if not name:
        return handle or "Unknown network"
    name = re.sub(r"\s+", " ", name)
    return name[:60]


_TIER1_BY_REGION = {
    "north-america": [3356, 174, 7018, 701, 6461, 2914, 3257],
    "latin-america": [3356, 12956, 174, 6762],
    "europe": [1299, 3320, 174, 5511, 6762, 6830, 3257],
    "africa": [5511, 6453, 6762, 3356],
    "middle-east": [6453, 1299, 6762, 3491],
    "asia": [2914, 3491, 6453, 1299],
    "oceania": [2914, 3491, 3356],
}


def _pick(options: list[int], key: int, k: int) -> list[int]:
    """Deterministically pick k distinct options for a key."""
    if not options:
        return []
    start = (key * 2654435761) % len(options)
    out = []
    for i in range(len(options)):
        o = options[(start + i) % len(options)]
        if o not in out:
            out.append(o)
        if len(out) == k:
            break
    return out


# --- build ----------------------------------------------------------------------------------

def build_catalog(seed: Seed, opts: BuildOptions) -> Catalog:
    cat = Catalog()
    tax = seed.taxonomy

    def use_source(sid: str):
        s = SOURCES[sid]
        if not s.available():
            raise FileNotFoundError(f"source {sid!r} not downloaded; run `python -m internet_snapshot fetch`")
        cat.sources.append(s.meta() | {"attribution": s.attribution})
        return s.path

    psl = P.PublicSuffixList.load(use_source("psl"))
    crux = P.load_crux(use_source("crux"), opts.crux_max_rank)
    asninfo = P.load_asninfo(use_source("asninfo"))
    ip_table = P.OriginAsnTable.load(use_source("originasn"))
    countries = P.load_countries(use_source("countries"))
    icons = P.load_simpleicons(use_source("simpleicons"))
    cat.sources.append({"id": "seed", "name": "Curated seed catalogue (this repository)",
                        "url": "https://github.com/PRIMITIVE-IO/the-internet-snapshot/tree/main/seed",
                        "license": "MIT", "license_class": "open",
                        "attribution": "Curated seed catalogue, the-internet-snapshot contributors (MIT)"})

    def icon_ok(slug):
        return slug if slug and slug in icons else None

    # ---- realms, categories, regions ----
    for realm in tax["realms"]:
        cat.add(new_node(f"realm:{realm['slug']}", "realm", realm["label"], lod=0, realm=f"realm:{realm['slug']}",
                         shell="services", color=realm["color"], size=1.0))
        for c in realm["categories"]:
            cat.add(new_node(f"cat:{c['slug']}", "category", c["label"], lod=1, parent=f"realm:{realm['slug']}",
                             realm=f"realm:{realm['slug']}", category=f"cat:{c['slug']}", shell="services",
                             color=realm["color"], size=0.8))
    for r in tax["regions"]:
        cat.add(new_node(f"region:{r['slug']}", "region", r["label"], lod=0, region=f"region:{r['slug']}",
                         role="region", shell="backbone", color="#ECEFF1", size=1.0,
                         _geo=(r["lat"], r["lon"])))

    # ---- services: seed ----
    host_map: dict[str, str] = {}
    brand_map: dict[str, str] = {}
    for s in seed.services:
        sid = f"svc:{s.domain}"
        c = seed.categories[s.category]
        cat.add(new_node(sid, "service", s.label, category=f"cat:{s.category}", realm=f"realm:{c['realm']}",
                         shell="services", color=c["color"], domain=s.domain, icon=icon_ok(s.icon),
                         url=f"https://{s.domain}", _org=s.org, _hosted=list(s.hosted), _seed=True,
                         _origins=0, _cat_src="seed", _aliases=list(s.aliases)))
        for d in [s.domain, *s.aliases]:
            host_map[d] = sid
        reg = psl.registrable(s.domain)
        if reg == s.domain:
            brand = s.domain[: -len(psl.public_suffix(s.domain)) - 1]
            if len(brand) >= 4:
                brand_map.setdefault(brand, sid)

    # ---- services: CrUX long tail ----
    def match_host(host: str) -> str | None:
        labels = host.split(".")
        for i in range(len(labels) - 1):
            sid = host_map.get(".".join(labels[i:]))
            if sid:
                return sid
        return None

    for host, rank in crux:
        sid = match_host(host)
        if sid is None:
            reg = psl.registrable(host)
            sid = host_map.get(reg)
            if sid is None:
                suffix = psl.public_suffix(reg)
                brand = reg[: -len(suffix) - 1] if reg != suffix else reg
                sid = brand_map.get(brand)
                if sid is not None:
                    host_map[reg] = sid  # regional variant, e.g. amazon.co.uk -> svc:amazon.com
                    cat.nodes[sid]["_aliases"].append(reg)
            if sid is None:
                sid = f"svc:{reg}"
                host_map[reg] = sid
                cslug, csrc = guess_category(reg, psl)
                c = seed.categories[cslug]
                cat.add(new_node(sid, "service", reg, category=f"cat:{cslug}", realm=f"realm:{c['realm']}",
                                 shell="services", color=c["color"], domain=reg, url=f"https://{reg}",
                                 country=country_from_domain(reg), _org=None, _hosted=[], _seed=False,
                                 _origins=0, _cat_src=csrc, _aliases=[]))
        n = cat.nodes[sid]
        n["rank"] = rank if n["rank"] is None else min(n["rank"], rank)
        n["_origins"] += 1

    # ---- orgs ----
    services = cat.of_kind("service")
    by_org: dict[str, list[dict]] = defaultdict(list)
    for s in services:
        if s["_org"]:
            by_org[s["_org"]].append(s)
    org_ids = {}
    for slug, svcs in by_org.items():
        so = seed.orgs.get(slug)
        if not (len(svcs) >= 2 or (so and so.asns)):
            continue  # single-service orgs are represented by the service itself
        svcs_sorted = sorted(svcs, key=lambda s: (s["rank"] or 10**7, s["id"]))
        cslug = (so.category if so and so.category else svcs_sorted[0]["category"].split(":", 1)[1])
        c = seed.categories[cslug]
        oid = f"org:{slug}"
        org_ids[slug] = oid
        cat.add(new_node(oid, "org", so.label if so else svcs_sorted[0]["label"], parent=f"cat:{cslug}",
                         category=f"cat:{cslug}", realm=f"realm:{c['realm']}", shell="services", color=c["color"],
                         country=so.country if so else None, icon=icon_ok(so.icon if so else None),
                         org=oid, rank=min((s["rank"] for s in svcs if s["rank"]), default=None),
                         _asns=list(so.asns) if so else [], _services=[s["id"] for s in svcs]))
    for s in services:
        oid = org_ids.get(s["_org"])
        s["org"] = oid
        if oid and cat.nodes[oid]["category"] == s["category"]:
            s["parent"] = oid
        else:
            s["parent"] = s["category"]
        if oid:
            cat.edge(oid, s["id"], "owns", 0.35)

    # ---- hosting: service -> ASNs ----
    dns_ips: dict[str, list[str]] = {}
    if opts.resolve_dns:
        from .dns import resolve_many
        need = [s["domain"] for s in services if not s["_hosted"] and not (s["org"] and cat.nodes[s["org"]]["_asns"])]
        hosts = need + ["www." + d for d in need if d.count(".") == 1]
        dns_ips = resolve_many(hosts)
        cat.sources.append({"id": "dns", "name": "DNS A-record lookups via the system resolver (build-time)",
                            "url": "", "license": "n/a (factual)", "license_class": "open",
                            "attribution": ""})
        cat.notes.append(f"resolved {len(hosts)} hostnames via DNS")
    hosted_count: Counter = Counter()
    for s in services:
        asns = list(s["_hosted"])
        if not asns and s["org"]:
            asns = cat.nodes[s["org"]]["_asns"][:1]
        if not asns and dns_ips:
            for h in (s["domain"], "www." + s["domain"]):
                for ip in dns_ips.get(h, []):
                    a = ip_table.lookup(ip)
                    if a and a not in asns:
                        asns.append(a)
                if asns:
                    break
        s["_hosted"] = asns[:2]
        for a in s["_hosted"]:
            hosted_count[a] += 1

    # ---- networks ----
    space = ip_table.address_space()

    def as_country(asn: int) -> str | None:
        sn = seed.networks.get(asn)
        if sn and sn.country:
            return sn.country
        info = asninfo.get(asn)
        return info["country"] if info else None

    wanted: dict[int, str] = {}  # asn -> reason
    for asn in seed.networks:
        wanted[asn] = "seed"
    for o in seed.orgs.values():
        for a in o.asns:
            wanted.setdefault(a, "seed-org")
    for a in hosted_count:
        wanted.setdefault(a, "hosting")
    longtail = [a for a, _ in sorted(space.items(), key=lambda kv: (-kv[1], kv[0]))
                if a not in wanted and a > 0 and a in asninfo]
    for a in longtail[: opts.longtail_networks]:
        wanted[a] = "address-space"

    role_of = {}
    for asn in wanted:
        sn = seed.networks.get(asn)
        info = asninfo.get(asn, {})
        if sn:
            role, label = sn.role, sn.label
        else:
            label = clean_as_name(info.get("name") or ip_table.names.get(asn, ""), info.get("handle", ""))
            role = guess_role(f"{label} {info.get('handle', '')}")
            if hosted_count[asn] >= 3 and role in ("enterprise", "access"):
                role = "hosting"
        org_slug = (sn.org if sn else None) or next((o.slug for o in seed.orgs.values() if asn in o.asns), None)
        cc = as_country(asn)
        region = region_for_country(cc)
        if cc and cc in countries:
            geo = (countries[cc]["lat"], countries[cc]["lon"])
        else:
            rg = next(r for r in tax["regions"] if r["slug"] == region)
            geo = (rg["lat"], rg["lon"])
        role_of[asn] = role
        cat.add(new_node(f"as:{asn}", "network", label, parent=f"region:{region}", region=f"region:{region}",
                         role=role, shell="edge" if role in EDGE_ROLES else "backbone", asn=asn, country=cc,
                         org=org_ids.get(org_slug) if org_slug else None,
                         url=f"https://bgp.tools/as/{asn}",
                         _geo=geo, _space=space.get(asn, 0), _hosts=hosted_count[asn], _reason=wanted[asn],
                         _seed=sn is not None))

    for s in services:
        for a in s["_hosted"]:
            if f"as:{a}" in cat.nodes:
                cat.edge(s["id"], f"as:{a}", "hosted_by", 0.3)
    for o in cat.of_kind("org"):
        for a in o["_asns"]:
            if f"as:{a}" in cat.nodes:
                cat.edge(o["id"], f"as:{a}", "operates", 0.6)

    # ---- IXPs ----
    for ix in seed.ixps:
        region = region_for_country(ix.country)
        cat.add(new_node(f"ix:{ix.slug}", "ixp", ix.label, parent=f"region:{region}", region=f"region:{region}",
                         role="ixp", shell="backbone", country=ix.country, _geo=(ix.lat, ix.lon)))

    # ---- AS relationships ----
    included = set(wanted)
    if opts.use_caida and SOURCES["caida_asrel"].available():
        rels, clique = P.load_caida_asrel(use_source("caida_asrel"))
        cat.rels = [r for r in rels if r[0] in included and r[1] in included]
        cat.tier1 = clique or [a for a, r in role_of.items() if r == "tier1"]
        cat.relationship_source = "caida-as-rel2"
    else:
        cat.rels = heuristic_relationships(role_of, {a: cat.nodes[f"as:{a}"]["country"] for a in included},
                                           seed_asns=set(seed.networks))
        cat.tier1 = sorted(a for a, r in role_of.items() if r == "tier1")
        cat.relationship_source = "heuristic-seed"
        cat.notes.append("AS relationships are heuristic (seed roles + geography); enable CAIDA as-rel2 for "
                         "inferred BGP relationships")
    tier1_set = set(cat.tier1)
    heuristic = cat.relationship_source.startswith("heuristic")
    for a, b, rel in cat.rels:
        # Guessed peerings stay in the routing graph (asgraph.json) but are not drawn, except the
        # well-established tier-1 mesh; inferred (CAIDA) relationships are all drawn.
        if heuristic and rel == 0 and not (a in tier1_set and b in tier1_set):
            continue
        cat.edge(f"as:{a}", f"as:{b}", "transit" if rel == -1 else "peer", 0.5 if rel == -1 else 0.4)

    # ---- IXP membership (heuristic until PeeringDB is enabled: carriers in their region, ISPs in-country) ----
    ixps = cat.of_kind("ixp")
    for n in cat.of_kind("network"):
        if not n["_seed"]:
            continue
        if n["role"] in ("tier1", "transit"):
            members = [x for x in ixps if x["region"] == n["region"]]
        elif n["role"] == "access":
            members = [x for x in ixps if x["country"] == n["country"]]
        else:
            members = []
        for x in members:
            cat.edge(n["id"], x["id"], "member", 0.25)

    # ---- colours for network-side nodes ----
    role_colors = {r["id"]: r["color"] for r in tax["network_roles"]}
    for n in cat.nodes.values():
        if n["kind"] in ("network", "ixp"):
            n["color"] = role_colors.get(n["role"], "#90A4AE")

    # ---- glyphs: what each node is ----
    for n in cat.nodes.values():
        if n["kind"] == "realm":
            n["glyph"] = REALM_GLYPH.get(n["id"].split(":", 1)[1], "orbit")
        elif n["kind"] in ("category", "service", "org"):
            n["glyph"] = CATEGORY_GLYPH.get((n["category"] or ":").split(":", 1)[1], "circle")
        elif n["kind"] in ("network", "ixp", "region"):
            n["glyph"] = ROLE_GLYPH.get(n["role"], KIND_GLYPH.get(n["kind"], "circle"))

    # ---- sizes ----
    for s in services:
        pop = popularity(s["rank"])
        if s["_seed"] and s["rank"] is None:
            pop = 0.5
        bonus = min(0.15, 0.03 * max(0, s["_origins"] - 1)) + (0.08 if s["_seed"] else 0)
        s["size"] = round(min(1.0, pop + bonus), 3)
    for o in cat.of_kind("org"):
        members = [cat.nodes[sid] for sid in o["_services"]]
        o["size"] = round(min(1.0, max(m["size"] for m in members) + 0.05 * math.log2(len(members))), 3)
    max_space = max((n["_space"] for n in cat.of_kind("network")), default=1) or 1
    for n in cat.of_kind("network"):
        sp = math.log10(1 + n["_space"]) / math.log10(1 + max_space)
        h = math.log10(1 + n["_hosts"]) / 3
        base = {"tier1": 0.55, "cloud": 0.45, "cdn": 0.45, "content": 0.35}.get(n["role"], 0.1)
        n["size"] = round(min(1.0, base + 0.35 * sp + 0.3 * h), 3)
    for x in ixps:
        x["size"] = 0.45
    return cat


def heuristic_relationships(role_of: dict[int, str], country_of: dict[int, str | None],
                            seed_asns: set[int] | None = None) -> list[tuple[int, int, int]]:
    """Approximate AS relationships from roles and geography (used only when CAIDA is not enabled).

    - The tier-1s form a full peering mesh.
    - Transit, hosting and long-tail networks buy transit from two tier-1s in their region,
      or from a seed access/transit network in their country.
    - Access networks buy transit from regional tier-1s and peer with the big content/CDN/cloud
      networks. Those also peer with every tier-1 and with each other. This mirrors how most traffic to large
      services leaves an eyeball network over direct peering.
    """
    seed_asns = set(role_of) if seed_asns is None else seed_asns
    rels: set[tuple[int, int, int]] = set()
    tier1 = sorted(a for a, r in role_of.items() if r == "tier1")
    for i, a in enumerate(tier1):
        for b in tier1[i + 1:]:
            rels.add((a, b, 0))
    big_content = sorted(a for a, r in role_of.items() if r in ("content", "cdn", "cloud") and a in seed_asns)
    # the large content, CDN and cloud networks also peer with each other (PNIs and IXPs)
    for i, a in enumerate(big_content):
        for b in big_content[i + 1:]:
            rels.add((a, b, 0))
    national_upstreams: dict[str, list[int]] = defaultdict(list)
    for a, r in sorted(role_of.items()):
        if r in ("transit", "access") and country_of.get(a) and a in seed_asns:
            national_upstreams[country_of[a]].append(a)

    for a, role in sorted(role_of.items()):
        if role == "tier1":
            continue
        region = region_for_country(country_of.get(a))
        regional = [t for t in _TIER1_BY_REGION[region] if t in role_of] or tier1
        if role in ("content", "cdn", "cloud") and a in seed_asns:
            for t in tier1:
                rels.add((a, t, 0))
            continue
        if role in ("transit", "access") and a in national_upstreams.get(country_of.get(a) or "", []):
            for p in _pick(regional, a, 2):
                rels.add((p, a, -1))
            if role == "access":
                for c in big_content:
                    rels.add((a, c, 0))
            continue
        # long tail: one national upstream when we know one, plus one regional tier-1
        nat = [u for u in national_upstreams.get(country_of.get(a) or "", []) if u != a]
        providers = _pick(nat, a, 1) + _pick(regional, a, 1)
        for p in providers:
            rels.add((p, a, -1))
    # normalise peer tuples so each pair appears once
    out, seen = [], set()
    for a, b, r in sorted(rels):
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        out.append((a, b, r))
    return out
