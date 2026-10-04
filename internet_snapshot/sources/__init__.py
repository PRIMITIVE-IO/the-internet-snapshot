"""Public data sources. Every source declares its licence class.

The default build uses only sources whose derived data may be redistributed (``open``). The
other classes are opt-in:

- ``sharealike``: derived output must carry the same licence.
- ``ask-first``: the publisher's terms require permission for commercial redistribution.
- ``noncommercial``: the build must stay non-commercial.

See docs/DESIGN.md §3 and docs/research/.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..config import RAW_DIR, USER_AGENT

LICENSE_CLASSES = ("open", "sharealike", "ask-first", "noncommercial")


@dataclass
class Source:
    id: str
    name: str
    url: str
    license: str
    license_class: str
    attribution: str
    filename: str
    default: bool = True
    homepage: str = ""
    resolver: object = None  # optional callable(client) -> concrete download URL
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return RAW_DIR / self.id

    @property
    def path(self) -> Path:
        return self.dir / self.filename

    def available(self) -> bool:
        return self.path.exists()

    def meta(self) -> dict:
        m = {"id": self.id, "name": self.name, "url": self.homepage or self.url, "license": self.license,
             "license_class": self.license_class}
        meta_path = self.dir / "meta.json"
        if meta_path.exists():
            m.update({k: v for k, v in json.loads(meta_path.read_text()).items()
                      if k in ("retrieved_at", "sha256", "download_url")})
        return m

    def fetch(self, refresh: bool = False, timeout: float = 120.0) -> Path:
        if self.available() and not refresh:
            return self.path
        self.dir.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": USER_AGENT}
        with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as client:
            url = self.resolver(client) if self.resolver else self.url
            tmp = self.path.with_suffix(self.path.suffix + ".part")
            h = hashlib.sha256()
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(1 << 16):
                        f.write(chunk)
                        h.update(chunk)
            tmp.replace(self.path)
        (self.dir / "meta.json").write_text(json.dumps({
            "download_url": url,
            "retrieved_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
            "sha256": h.hexdigest(),
        }, indent=2))
        return self.path


def _caida_latest(subdir: str, pattern: str):
    """Resolver for CAIDA's dated files: parse the directory index and take the newest match."""

    def resolve(client: httpx.Client) -> str:
        last_err = None
        for base in ("https://publicdata.caida.org/datasets/", "https://data.caida.org/datasets/"):
            index = base + subdir
            try:
                r = client.get(index)
                r.raise_for_status()
            except httpx.HTTPError as e:  # try the next mirror
                last_err = e
                continue
            names = sorted(set(re.findall(pattern, r.text)))
            if names:
                return index + names[-1]
        raise RuntimeError(f"could not resolve latest CAIDA file in {subdir}: {last_err}")

    return resolve


def _npm_tarball(package: str):
    """Resolver: the latest published tarball of an npm package."""

    def resolve(client: httpx.Client) -> str:
        r = client.get(f"https://registry.npmjs.org/{package}")
        r.raise_for_status()
        d = r.json()
        return d["versions"][d["dist-tags"]["latest"]]["dist"]["tarball"]

    return resolve


def _evanli_latest(client: httpx.Client) -> str:
    """Resolver: the newest daily EvanLi/Github-Ranking CSV (published around 04:00 UTC)."""
    base = "https://raw.githubusercontent.com/EvanLi/Github-Ranking/master/Data/github-ranking-{}.csv"
    today = _dt.datetime.now(_dt.timezone.utc).date()
    for back in range(0, 10):
        url = base.format(today - _dt.timedelta(days=back))
        if client.head(url).status_code == 200:
            return url
    raise RuntimeError("no EvanLi/Github-Ranking CSV in the last 10 days")


SOURCES: dict[str, Source] = {s.id: s for s in [
    Source(
        id="crux", name="Chrome UX Report top lists (global)",
        url="https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/global/current.csv.gz",
        homepage="https://developer.chrome.com/docs/crux",
        license="CC BY 4.0", license_class="open", filename="current.csv.gz",
        attribution="Chrome UX Report by Google (CC BY 4.0), via zakird/crux-top-lists",
    ),
    Source(
        id="psl", name="Public Suffix List",
        url="https://raw.githubusercontent.com/publicsuffix/list/main/public_suffix_list.dat",
        homepage="https://publicsuffix.org/",
        license="MPL-2.0", license_class="open", filename="public_suffix_list.dat",
        attribution="Public Suffix List, Mozilla Foundation (MPL-2.0)",
    ),
    Source(
        id="asninfo", name="ipverse asn-info (AS names and countries)",
        url="https://raw.githubusercontent.com/ipverse/asn-info/master/as.csv",
        homepage="https://github.com/ipverse/asn-info",
        license="CC0 1.0", license_class="open", filename="as.csv",
        attribution="ipverse/asn-info (CC0)",
    ),
    Source(
        id="originasn", name="IP prefix to origin ASN (sapics/ip-location-db origin-asn)",
        url="https://github.com/sapics/ip-location-db/releases/download/latest/origin-asn-ipv4.csv",
        homepage="https://github.com/sapics/ip-location-db",
        license="PDDL 1.0", license_class="open", filename="origin-asn-ipv4.csv",
        attribution="sapics/ip-location-db origin-asn (PDDL)",
    ),
    Source(
        id="countries", name="Country centroids (Google DSPL canonical countries)",
        url="https://raw.githubusercontent.com/google/dspl/master/samples/google/canonical/countries.csv",
        homepage="https://developers.google.com/public-data/docs/canonical/countries_csv",
        license="CC BY 4.0", license_class="open", filename="countries.csv",
        attribution="Country centroids from Google DSPL (CC BY 4.0)",
    ),
    Source(
        id="simpleicons", name="Simple Icons brand index",
        url="https://raw.githubusercontent.com/simple-icons/simple-icons/develop/data/simple-icons.json",
        homepage="https://simpleicons.org/",
        license="CC0 1.0 (logos remain trademarks of their owners)", license_class="open",
        filename="simple-icons.json",
        attribution="Simple Icons (CC0); brand logos are trademarks of their respective owners",
    ),
    Source(
        id="github_rest", name="GitHub REST API description (OpenAPI)",
        url="https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
        homepage="https://github.com/github/rest-api-description",
        license="MIT", license_class="open", filename="api.github.com.json",
        attribution="GitHub REST API description, GitHub Inc. (MIT)",
    ),
    Source(
        id="google_discovery", name="Google API Discovery directory",
        url="https://www.googleapis.com/discovery/v1/apis",
        homepage="https://developers.google.com/discovery",
        license="Google APIs Terms of Service (public API metadata)", license_class="open", filename="apis.json",
        attribution="Google API Discovery Service directory",
    ),
    Source(
        id="github_ranking", name="EvanLi/Github-Ranking (daily top-100 repositories per language)",
        url="", homepage="https://github.com/EvanLi/Github-Ranking",
        license="MIT", license_class="open", filename="github-ranking.csv", resolver=_evanli_latest,
        attribution="EvanLi/Github-Ranking (MIT), from public GitHub repository metadata",
    ),
    Source(
        id="lucide", name="Lucide icons (static SVG package)",
        url="", homepage="https://lucide.dev", resolver=_npm_tarball("lucide-static"),
        license="ISC", license_class="open", filename="lucide-static.tgz",
        attribution="Lucide icons (ISC)",
    ),
    Source(
        id="simpleicons_svg", name="Simple Icons (SVG package)",
        url="", homepage="https://simpleicons.org", resolver=_npm_tarball("simple-icons"),
        license="CC0 1.0 (logos remain trademarks of their owners)", license_class="open", filename="simple-icons.tgz",
        attribution="Simple Icons (CC0); brand logos are trademarks of their respective owners",
    ),
    Source(
        id="apis_guru", name="APIs.guru OpenAPI directory (list)",
        url="https://api.apis.guru/v2/list.json", homepage="https://apis.guru",
        license="CC0 1.0", license_class="open", filename="list.json", default=False,
        attribution="APIs.guru OpenAPI directory (CC0)",
        notes="optional: enriches site graphs with provider APIs (AWS, Microsoft Graph, Stripe, ...)",
    ),
    Source(
        id="caida_asrel", name="CAIDA AS Relationships (serial-2)",
        url="", homepage="https://www.caida.org/catalog/datasets/as-relationships/",
        license="CAIDA Public AUA", license_class="ask-first", filename="as-rel2.txt.bz2", default=False,
        resolver=_caida_latest("as-relationships/serial-2/", r"\d{8}\.as-rel2\.txt\.bz2"),
        attribution="CAIDA AS Relationships Dataset, https://www.caida.org/catalog/datasets/as-relationships/",
    ),
    Source(
        id="caida_as2org", name="CAIDA AS-to-Organization",
        url="", homepage="https://www.caida.org/catalog/datasets/as-organizations/",
        license="CAIDA Public AUA", license_class="ask-first", filename="as-org2info.txt.gz", default=False,
        resolver=_caida_latest("as-organizations/", r"\d{8}\.as-org2info\.txt\.gz"),
        attribution="CAIDA AS Organizations Dataset, https://www.caida.org/catalog/datasets/as-organizations/",
    ),
]}


def selected_sources(include: list[str] | None = None, allow_classes: set[str] | None = None) -> list[Source]:
    """Default sources plus any explicitly included ones whose licence class is allowed."""
    allow_classes = allow_classes or {"open"}
    out = []
    for s in SOURCES.values():
        wanted = s.default or (include and s.id in include)
        if wanted and (s.license_class in allow_classes or (include and s.id in include)):
            out.append(s)
    return out
