"""Builders for site graphs: curated specs, automatic org/service graphs, and the code universe."""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..build.catalog import Catalog, popularity
from ..config import SEED_DIR
from ..glyphs import CATEGORY_GLYPH, glyph_for_text
from ..sources import SOURCES
from ..sources import parsers as P
from .model import SiteGraph, host_matches

SITES_SEED_DIR = SEED_DIR / "sites"


@dataclass
class SiteContext:
    catalog: Catalog
    psl: P.PublicSuffixList
    crux_hosts: dict[str, list[tuple[str, int]]]          # registrable domain -> [(host, rank)]
    categories: dict[str, dict]                             # taxonomy categories by slug
    github_ops: list[dict] = field(default_factory=list)
    google_apis: list[dict] = field(default_factory=list)
    apis_guru: dict[str, list[dict]] = field(default_factory=dict)   # provider domain -> apis
    sources_used: dict[str, dict] = field(default_factory=dict)

    def use(self, sid: str) -> None:
        s = SOURCES.get(sid)
        if s and sid not in self.sources_used:
            self.sources_used[sid] = {"id": s.id, "name": s.name, "license": s.license,
                                      "url": s.homepage or s.url, "attribution": s.attribution}

    def service_domains(self, svc: dict) -> list[str]:
        return [svc["domain"], *svc.get("_aliases", [])] if svc.get("domain") else []

    def hosts_for_domains(self, domains: list[str]) -> list[tuple[str, int]]:
        regs = {self.psl.registrable(d) for d in domains if d}
        out = {}
        for reg in regs:
            for h, r in self.crux_hosts.get(reg, []):
                if h not in out or r < out[h]:
                    out[h] = r
        return sorted(out.items(), key=lambda x: (x[1], x[0]))


def load_context(catalog: Catalog, categories: dict[str, dict]) -> SiteContext:
    psl = P.PublicSuffixList.load(SOURCES["psl"].path)
    crux_hosts: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for host, rank in P.load_crux(SOURCES["crux"].path, max_rank=10**9):
        crux_hosts[psl.registrable(host)].append((host, rank))
    ctx = SiteContext(catalog=catalog, psl=psl, crux_hosts=crux_hosts, categories=categories)
    ctx.use("crux")
    if SOURCES["github_rest"].available():
        spec = json.loads(SOURCES["github_rest"].path.read_text())
        for path, item in spec["paths"].items():
            for method, op in item.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                xg = op.get("x-github", {})
                ctx.github_ops.append({"path": path, "method": method.upper(), "id": op.get("operationId", f"{method} {path}"),
                                       "summary": op.get("summary") or op.get("operationId"),
                                       "category": xg.get("category") or (op.get("tags") or ["other"])[0],
                                       "subcategory": xg.get("subcategory"),
                                       "doc": (op.get("externalDocs") or {}).get("url")})
    if SOURCES["google_discovery"].available():
        items = json.loads(SOURCES["google_discovery"].path.read_text()).get("items", [])
        ctx.google_apis = [i for i in items if i.get("preferred")]
    if SOURCES["apis_guru"].available():
        for key, api in json.loads(SOURCES["apis_guru"].path.read_text()).items():
            ver = api.get("versions", {}).get(api.get("preferred", ""), {})
            info = ver.get("info", {})
            provider = info.get("x-providerName") or key.split(":")[0]
            ctx.apis_guru[provider.lower()].append({"key": key, "title": info.get("title", key),
                                                    "service": info.get("x-serviceName"),
                                                    "categories": info.get("x-apisguru-categories", []),
                                                    "url": (info.get("externalDocs") or {}).get("url") or ver.get("swaggerUrl")})
    return ctx


# --- helpers ---------------------------------------------------------------------------------

def _url_for(host: str | None, path: str | None) -> str | None:
    if not host or host.startswith("*"):
        return None
    clean = re.sub(r"/\{[^}]+\}.*$", "", path or "") if path else ""
    return f"https://{host}{clean}"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


MAX_HOSTS_PER_NODE = 40


def _host_node(g: SiteGraph, parent: str, host: str, rank: int | None) -> dict | None:
    """Add a host under parent, keeping at most MAX_HOSTS_PER_NODE (hosts arrive most popular first)."""
    p = g.nodes[parent]
    if p["meta"].get("hosts_shown", 0) >= MAX_HOSTS_PER_NODE:
        p["meta"]["more_hosts"] = p["meta"].get("more_hosts", 0) + 1
        return None
    p["meta"]["hosts_shown"] = p["meta"].get("hosts_shown", 0) + 1
    return g.add(parent, host, "host", host, weight=popularity(rank) * 0.9, host=host, url=f"https://{host}",
                 glyph=glyph_for_text(host.split(".")[0], default="globe"), meta={"crux_rank": rank})


def _attach_hosts(g: SiteGraph, ctx: SiteContext, domains: list[str], targets: list[tuple[dict, list[str], list[str]]],
                  catch_all: str) -> None:
    """Attach CrUX hostnames to the best-matching node.

    targets: [(node, explicit host patterns, global-service domains)]
    """
    for host, rank in ctx.hosts_for_domains(domains):
        best, best_score = None, (-1, -1, -1)
        for node, patterns, gdomains in targets:
            score = None
            for pat in patterns:
                if host_matches(pat, host):
                    score = (3 if pat.lower() == host else 2, node["depth"], len(pat))
                    break
            if score is None:
                for d in gdomains:
                    if host == d or host.endswith("." + d):
                        score = (1, node["depth"], len(d))
                        break
            if score and score > best_score:
                best, best_score = node, score
        if best is not None and best_score[0] == 3 and not best.get("path"):
            best["meta"]["crux_rank"] = min(rank, best["meta"].get("crux_rank") or rank)
            best["_w"] = max(best["_w"], popularity(rank))
            continue
        parent = best["id"] if best is not None else catch_all
        if best is not None and best.get("path"):  # a path-section: attach the host to its surface instead
            parent = best["parent"]
        _host_node(g, parent, host, rank)


# --- curated ---------------------------------------------------------------------------------

def build_curated(spec: dict, ctx: SiteContext) -> SiteGraph:
    nodes = ctx.catalog.nodes
    root_global = nodes.get(spec["root_node"])
    g = SiteGraph(id=f"site:{spec['id']}", kind="site", label=spec["label"], root_node=spec["root_node"],
                  icon=spec.get("icon"))
    g.root["url"] = root_global.get("url") if root_global else None
    ctx_targets: list[tuple[dict, list[str], list[str]]] = []
    api_claims: dict[str, dict] = {}
    special: dict[str, dict] = {}
    catch_all = g.id

    def walk(parent_id: str, items: list[dict], depth: int, inherited: list[str]):
        nonlocal catch_all
        for it in items:
            glob = nodes.get(it.get("global", "")) if it.get("global") else None
            kind = "surface" if depth == 1 else ("api" if it.get("openapi") else
                                                 "product" if glob or it.get("children") else
                                                 "section" if it.get("path") else "product")
            hosts = list(it.get("hosts", []))
            # path sections without their own host inherit it from the nearest ancestor (for locate)
            match_hosts = hosts or (inherited if it.get("path") else [])
            host = next((h for h in match_hosts if "*" not in h), match_hosts[0] if match_hosts else None)
            icon = it.get("icon") or (glob or {}).get("icon")
            n = g.add(parent_id, it["key"], kind, it["label"], weight=float(it.get("weight", 0.5)),
                      host=host, path=it.get("path"), method=it.get("method"),
                      url=it.get("url") or (glob or {}).get("url") or _url_for(host, it.get("path")),
                      icon=icon, glyph=it.get("glyph") or glyph_for_text(it["label"], default="circle"),
                      portal=it.get("portal"),
                      meta={"global": glob["id"]} if glob else {})
            if glob:
                n["_w"] = max(n["_w"], glob.get("size") or 0.5)
            gdomains = ctx.service_domains(glob) if glob else []
            ctx_targets.append((n, hosts, gdomains))
            for a in it.get("apis", []):
                api_claims[a] = n
            for flag in ("google_cloud_apis", "apis_rest", "openapi"):
                if it.get(flag):
                    special[flag] = n
            if it.get("crux_hosts"):
                catch_all = n["id"]
            walk(n["id"], it.get("children", []), depth + 1, hosts or inherited)

    walk(g.id, spec["children"], 1, [])

    if "openapi" in special and ctx.github_ops:
        _expand_github_api(g, special["openapi"], ctx)
    if ctx.google_apis and (api_claims or special.get("google_cloud_apis") or special.get("apis_rest")):
        _attach_google_apis(g, ctx, api_claims, special.get("google_cloud_apis"), special.get("apis_rest"))

    domains = list(spec.get("domains", []))
    for _, _, gd in ctx_targets:
        domains.extend(gd)
    _attach_hosts(g, ctx, domains, ctx_targets, catch_all)
    _link_same_resources(g)
    return g


GITHUB_CORE = {"repos", "issues", "pulls", "actions", "users", "orgs", "git", "search", "releases", "gists", "copilot",
               "packages", "checks", "commits", "branches"}


def _expand_github_api(g: SiteGraph, api_node: dict, ctx: SiteContext) -> None:
    ctx.use("github_rest")
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for op in ctx.github_ops:
        by_cat[op["category"]].append(op)
    for cat, ops in sorted(by_cat.items()):
        core = cat in GITHUB_CORE
        grp = g.add(api_node["id"], cat, "api-group", cat.replace("-", " ").title(),
                    weight=(0.75 if core else 0.4) * min(1.0, 0.4 + math.log10(1 + len(ops)) / 2.5),
                    host="api.github.com", glyph=glyph_for_text(cat, default="braces"),
                    url=f"https://docs.github.com/rest/{cat}", meta={"operations": len(ops)})
        subs = Counter(o["subcategory"] for o in ops)
        use_subs = len(ops) > 15 and len(subs) > 1
        for op in sorted(ops, key=lambda o: (o["subcategory"] or "", o["path"], o["method"])):
            parent = grp
            if use_subs and op["subcategory"]:
                sc = op["subcategory"]
                parent = g.add(grp["id"], sc, "api-group", sc.replace("-", " ").title(), weight=0.35,
                               host="api.github.com", glyph=glyph_for_text(sc, cat, default="braces"),
                               url=f"https://docs.github.com/rest/{cat}/{sc}")
            g.add(parent["id"], op["id"].replace("/", ":"), "operation", op["summary"],
                  weight=0.35 if core and op["method"] == "GET" else 0.2,
                  host="api.github.com", path=op["path"], method=op["method"], url=op["doc"],
                  glyph=glyph_for_text(op["summary"], op["path"], default="arrow-right-left"),
                  meta={"operation_id": op["id"], "category": cat, "subcategory": op["subcategory"]})


_CLOUD_GROUPS = [
    ("compute", "Compute & containers", "cpu", r"compute|container|run|functions|appengine|batch|vmware|gke|kubernetes|workstations|baremetal|tpu"),
    ("data", "Data & storage", "database", r"storage|bigquery|bigtable|spanner|sql|firestore|datastore|dataproc|dataflow|datafusion|datacatalog|dataplex|composer|memcache|redis|alloydb|file|backup|datastream|looker|metastore"),
    ("network", "Networking", "network", r"dns|network|vpc|connectivity|servicenetworking|trafficdirector|cdn|edge|interconnect|domains"),
    ("ops", "Operations & observability", "chart-line", r"logging|monitoring|trace|errorreporting|profiler|clouddebugger|osconfig|recommender|cloudasset|servicemanagement|serviceusage|cloudbilling|billingbudgets|cloudresourcemanager|essentialcontacts|orgpolicy|policyanalyzer"),
    ("security", "Security", "shield-check", r"security|kms|secret|binaryauthorization|privateca|certificate|websecurityscanner|recaptcha|dlp|accessapproval|assuredworkloads|chronicle"),
    ("integration", "Integration & messaging", "webhook", r"pubsub|tasks|scheduler|workflow|eventarc|apigee|integrations|connectors|apigateway|cloudbuild|clouddeploy|artifactregistry|sourcerepo|containeranalysis|ondemandscanning"),
]


_PREFIX_FAMILIES = {"firebase", "android", "analytics", "adsense", "youtube", "drive", "games", "doubleclick",
                    "adexchange", "admin", "gmail"}


def _attach_google_apis(g: SiteGraph, ctx: SiteContext, claims: dict[str, dict], cloud: dict | None,
                        rest: dict | None) -> None:
    ctx.use("google_discovery")
    for api in ctx.google_apis:
        name = api["name"]
        target = claims.get(name)
        if target is None:
            for k, v in claims.items():
                if k in _PREFIX_FAMILIES and name.startswith(k):
                    target = v
                    break
        sub = None
        if target is None and cloud is not None and "cloud.google.com" in (api.get("documentationLink") or ""):
            target = cloud
            for key, label, glyph, rx in _CLOUD_GROUPS:
                if re.search(rx, name):
                    sub = (key, label, glyph)
                    break
            else:
                sub = ("other", "More Cloud APIs", "cloud")
        if target is None:
            target = rest
        if target is None:
            continue
        parent = target
        if sub:
            parent = g.add(target["id"], f"apis-{sub[0]}", "api-group", sub[1], weight=0.4, glyph=sub[2])
        elif target is not rest:
            parent = g.add(target["id"], "apis", "api-group", f"{target['label']} APIs", weight=0.4, glyph="braces")
        disc = urlparse(api.get("discoveryRestUrl") or "")
        if disc.hostname and disc.hostname != "www.googleapis.com":
            host, path = disc.hostname, None
        else:
            host, path = "www.googleapis.com", f"/{name}/{api['version']}"
        title = re.sub(r"\s+API$", "", api.get("title", name))
        g.add(parent["id"], name, "api", title, weight=0.45, host=host, path=path, url=api.get("documentationLink"),
              glyph=glyph_for_text(name, title, default="plug"),
              meta={"api": name, "version": api.get("version"), "description": (api.get("description") or "")[:240]})


def _link_same_resources(g: SiteGraph) -> None:
    """Cross-link a web section and the API group of the same name (e.g. web 'issues' <-> REST 'issues')."""
    sections = {n["id"].rsplit("/", 1)[-1]: n for n in g.nodes.values() if n["kind"] == "section"}
    for n in g.nodes.values():
        if n["kind"] == "api-group" and n["depth"] == 2:
            key = n["id"].rsplit("/", 1)[-1]
            if key in sections:
                g.edge(sections[key]["id"], n["id"], "same_resource", 0.5)


# --- automatic graphs --------------------------------------------------------------------------

def _apis_guru_for(ctx: SiteContext, domains: list[str]) -> list[dict]:
    out = []
    for d in domains:
        out.extend(ctx.apis_guru.get(d.lower(), []))
    return out


def build_org_auto(org: dict, ctx: SiteContext, min_nodes: int = 6) -> SiteGraph | None:
    nodes = ctx.catalog.nodes
    services = [nodes[s] for s in org.get("_services", []) if s in nodes]
    if not services:
        return None
    slug = org["id"].split(":", 1)[1]
    g = SiteGraph(id=f"site:{slug}", kind="site", label=org["label"], root_node=org["id"], icon=org.get("icon"))
    targets = []
    by_cat = defaultdict(list)
    for s in services:
        by_cat[s["category"]].append(s)
    domains = []
    for cat_id, svcs in sorted(by_cat.items(), key=lambda kv: -sum(s["size"] for s in kv[1])):
        cslug = cat_id.split(":", 1)[1]
        surf = g.add(g.id, cslug, "surface", ctx.categories[cslug]["label"], weight=0.6,
                     glyph=CATEGORY_GLYPH.get(cslug, "layers"))
        for s in sorted(svcs, key=lambda s: -s["size"]):
            p = g.add(surf["id"], _slug(s["domain"]), "product", s["label"], weight=s["size"], host=s["domain"],
                      url=s.get("url"), icon=s.get("icon"), glyph=CATEGORY_GLYPH.get(cslug, "circle"),
                      meta={"global": s["id"]})
            sd = ctx.service_domains(s)
            domains.extend(sd)
            targets.append((p, [], sd))
            apis = _apis_guru_for(ctx, sd)
            if apis:
                ctx.use("apis_guru")
                grp = g.add(p["id"], "apis", "api-group", f"{s['label']} APIs", weight=0.4, glyph="braces")
                for a in apis[:300]:
                    g.add(grp["id"], _slug(a["key"]), "api", a["title"], weight=0.35, url=a["url"],
                          glyph=glyph_for_text(a["title"], " ".join(a["categories"]), default="plug"),
                          meta={"apis_guru": a["key"], "categories": a["categories"]})
    _attach_hosts(g, ctx, domains, targets, g.id)
    return g if len(g.nodes) - 1 >= min_nodes else None


def build_service_auto(svc: dict, ctx: SiteContext, min_hosts: int = 6) -> SiteGraph | None:
    if svc.get("lod", 3) > 2:
        return None  # only major services get a precomputed graph; others are built on demand
    domains = ctx.service_domains(svc)
    hosts = ctx.hosts_for_domains(domains)
    apis = _apis_guru_for(ctx, domains)
    if len(hosts) + len(apis) < min_hosts:
        return None
    g = SiteGraph(id=f"site:{svc['domain']}", kind="site", label=svc["label"], root_node=svc["id"], icon=svc.get("icon"))
    g.root["url"] = svc.get("url")
    by_reg = defaultdict(list)
    for h, r in hosts:
        by_reg[ctx.psl.registrable(h)].append((h, r))
    if len(by_reg) > 1:
        for reg, hs in sorted(by_reg.items(), key=lambda kv: min(r for _, r in kv[1])):
            grp = g.add(g.id, _slug(reg), "surface", reg, weight=popularity(min(r for _, r in hs)), host=reg,
                        url=f"https://{reg}", glyph="globe")
            for h, r in hs:
                _host_node(g, grp["id"], h, r)
    else:
        for h, r in hosts:
            _host_node(g, g.id, h, r)
    if apis:
        ctx.use("apis_guru")
        grp = g.add(g.id, "apis", "surface", "APIs", weight=0.5, glyph="braces")
        for a in apis[:300]:
            g.add(grp["id"], _slug(a["key"]), "api", a["title"], weight=0.35, url=a["url"],
                  glyph=glyph_for_text(a["title"], default="plug"), meta={"apis_guru": a["key"]})
    return g


# --- code universe -----------------------------------------------------------------------------

ECOSYSTEMS = [
    # key, label, registry, icon, ranking lists (EvanLi "item" names)
    ("dotnet", ".NET (NuGet)", "nuget", "dotnet", ["CSharp"]),
    ("jvm", "JVM (Maven)", "maven", "apachemaven", ["Java", "Kotlin", "Scala", "Groovy", "Clojure"]),
    ("npm", "JavaScript (npm)", "npm", "npm", ["JavaScript", "TypeScript", "CoffeeScript"]),
    ("python", "Python (PyPI)", "pypi", "pypi", ["Python"]),
    ("ruby", "Ruby (RubyGems)", "rubygems", "rubygems", ["Ruby"]),
    ("php", "PHP (Packagist)", "packagist", "packagist", ["PHP"]),
    ("go", "Go (modules)", "go", "go", ["Go"]),
    ("rust", "Rust (Cargo)", "cargo", "rust", ["Rust"]),
    ("apple", "Apple (SwiftPM / CocoaPods)", "cocoapods", "swift", ["Swift", "Objective-C"]),
    ("native", "Native C/C++ (vcpkg / Conan)", "conan", "cplusplus", ["C", "CPP"]),
    ("dart", "Dart (pub)", "pub", "dart", ["Dart"]),
    ("beam", "BEAM (Hex)", "hex", "elixir", ["Elixir"]),
    ("r", "R (CRAN)", "cran", "r", ["R"]),
    ("haskell", "Haskell (Hackage)", "hackage", "haskell", ["Haskell"]),
    ("julia", "Julia (General)", "julia", "julia", ["Julia"]),
    ("lua", "Lua (LuaRocks)", "luarocks", "lua", ["Lua"]),
    ("perl", "Perl (CPAN)", "cpan", "perl", ["Perl"]),
    ("web", "Web (HTML & CSS)", None, "html5", ["HTML", "CSS"]),
    ("shell", "Shell & automation", None, "gnubash", ["Shell", "PowerShell", "Vim-script"]),
    ("science", "Scientific & docs", None, "latex", ["MATLAB", "TeX"]),
    ("other", "Other languages", None, None, ["ActionScript", "DM"]),
    ("knowledge", "Knowledge (lists, books, guides)", None, "markdown", []),
]
LANGUAGE_LABELS = {"CSharp": "C#", "CPP": "C++", "Vim-script": "Vim script"}
LANGUAGE_ICONS = {"CSharp": "dotnet", "Java": "openjdk", "Kotlin": "kotlin", "Scala": "scala", "Groovy": "apachegroovy",
                  "Clojure": "clojure", "JavaScript": "javascript", "TypeScript": "typescript",
                  "CoffeeScript": "coffeescript", "Python": "python", "Ruby": "ruby", "PHP": "php", "Go": "go",
                  "Rust": "rust", "Swift": "swift", "C": "c", "CPP": "cplusplus", "Dart": "dart", "Elixir": "elixir",
                  "R": "r", "Haskell": "haskell", "Julia": "julia", "Lua": "lua", "Perl": "perl", "HTML": "html5",
                  "CSS": "css", "Shell": "gnubash", "PowerShell": "powershell", "Vim-script": "vim", "TeX": "latex"}

PURPOSES = [
    ("learning", "Learning & lists", "book-open", r"awesome|\blist\b|tutorial|learn|course|interview|\bbook|guide|roadmap|resources|examples?\b|algorithms|cheat|curated|collection"),
    ("ai", "AI & machine learning", "sparkles", r"machine.?learning|deep.?learning|neural|\bllm|gpt|\bai\b|agent|transformer|diffusion|model|nlp|inference|vision"),
    ("frontend", "Frontend & UI", "palette", r"\bui\b|component|react|vue|svelte|angular|css|design|frontend|animation|icons?\b|theme|chart|widget|tailwind"),
    ("web", "Web frameworks & servers", "braces", r"framework|\bweb\b|http|server|\bapi\b|rest|graphql|router|middleware|backend"),
    ("devtools", "Developer tools & CLI", "terminal", r"\bcli\b|terminal|command|tool|editor|\bide\b|vim|neovim|lint|format|debug|shell|prompt|git\b|build"),
    ("infra", "Infrastructure & DevOps", "container", r"docker|kubernetes|cloud|deploy|infrastructure|devops|\bci\b|monitor|proxy|network|distributed|cluster"),
    ("data", "Data & databases", "database", r"database|\bsql|data|storage|cache|query|analytics|\borm\b|search engine|stream"),
    ("apps", "Apps (mobile & desktop)", "smartphone", r"android|\bios\b|mobile|desktop|\bapp\b|electron|flutter|client"),
    ("games", "Games & graphics", "gamepad-2", r"game|engine|graphics|render|\b3d\b|opengl|vulkan|emulator"),
    ("security", "Security & privacy", "shield-check", r"security|crypto|password|\bauth|vulnerab|pentest|hack|privacy|proxy"),
]


def _purpose(desc: str) -> tuple[str, str, str]:
    for key, label, glyph, rx in PURPOSES:
        if re.search(rx, desc or "", re.I):
            return key, label, glyph
    return "libs", "Libraries & misc", "package"


def build_code_universe(ctx: SiteContext, path: Path | None = None) -> SiteGraph | None:
    src = SOURCES["github_ranking"]
    path = path or src.path
    if not Path(path).exists():
        return None
    ctx.use("github_ranking")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    list_to_eco = {lst: eco for eco in ECOSYSTEMS for lst in eco[4]}
    repos: dict[str, dict] = {}
    for row in rows:
        url = row["repo_url"]
        item = row["item"]
        if item in ("top-100-stars", "top-100-forks"):
            if url in repos:
                continue
            lang = (row.get("language") or "").strip()
            item = {"C#": "CSharp", "C++": "CPP", "Vim Script": "Vim-script"}.get(lang, lang)
            if item not in list_to_eco:
                item = "__knowledge__"
        elif url in repos and repos[url]["item"] != "__knowledge__":
            continue
        try:
            stars = int(row["stars"])
        except ValueError:
            continue
        repos[url] = {"item": item, "row": row, "stars": stars}
    if not repos:
        return None

    g = SiteGraph(id="site:code-universe", kind="code", label="GitHub code universe", root_node="svc:github.com",
                  icon="github")
    g.root["url"] = "https://github.com/trending"
    max_stars = max(r["stars"] for r in repos.values())
    eco_nodes = {}
    for key, label, registry, icon, _ in ECOSYSTEMS:
        eco_nodes[key] = g.add(g.id, key, "ecosystem", label, weight=0.6, icon=icon, glyph="boxes",
                               meta={"registry": registry})
    owners = Counter(r["row"]["username"] for r in repos.values())
    hubs = {o for o, c in owners.items() if c >= 3}
    maint = g.add(g.id, "maintainers", "ecosystem", "Top maintainers", weight=0.6, glyph="users",
                  meta={"registry": None})
    for o in sorted(hubs):
        g.add(maint["id"], _slug(o), "owner", o, weight=min(1.0, 0.3 + 0.1 * owners[o]), host="github.com",
              path=f"/{o}", url=f"https://github.com/{o}", glyph="user",
              meta={"repos": owners[o], "avatar": f"https://github.com/{o}.png"})

    for url, r in sorted(repos.items(), key=lambda kv: -kv[1]["stars"]):
        row = r["row"]
        item = r["item"]
        eco = "knowledge" if item == "__knowledge__" else list_to_eco[item][0]
        lang_label = "Lists & docs" if item == "__knowledge__" else LANGUAGE_LABELS.get(item, item)
        lang = g.add(eco_nodes[eco]["id"], _slug(lang_label), "language", lang_label, weight=0.5,
                     icon=LANGUAGE_ICONS.get(item), glyph="code")
        pkey, plabel, pglyph = _purpose(row.get("description", "") + " " + row["repo_name"])
        cl = g.add(lang["id"], pkey, "cluster", plabel, weight=0.4, glyph=pglyph)
        owner, name = row["username"], row["repo_name"]
        w = math.log10(1 + r["stars"]) / math.log10(1 + max_stars)
        node = g.add(cl["id"], _slug(f"{owner}-{name}"), "repo", name, weight=w, host="github.com",
                     path=f"/{owner}/{name}", url=url, glyph=pglyph,
                     meta={"full_name": f"{owner}/{name}", "owner": owner, "stars": r["stars"],
                           "forks": int(row["forks"] or 0), "language": row.get("language") or None,
                           "description": (row.get("description") or "")[:240],
                           "last_commit": row.get("last_commit"), "rank_in_language": int(row["rank"]),
                           "avatar": f"https://github.com/{owner}.png"})
        if owner in hubs:
            g.edge(f"{maint['id']}/{_slug(owner)}", node["id"], "maintains", 0.3)
    g.prune_empty(keep_kinds=("repo", "owner"))
    return g


def load_curated_specs() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(SITES_SEED_DIR.glob("*.json"))]
