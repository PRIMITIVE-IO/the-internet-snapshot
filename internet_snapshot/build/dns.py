"""Optional DNS stage: domain -> IPv4 addresses, cached on disk.

This is a plain resolver lookup, the same thing any browser does before connecting. It is not
crawling, and no page content is fetched. It is opt-in (``--resolve-dns``). The planned
replacement is OpenINTEL's published toplist DNS measurements (see docs/DESIGN.md §3).
"""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import DATA_DIR

CACHE = DATA_DIR / "cache" / "dns-a.json"


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    return sorted({i[4][0] for i in infos})


def resolve_many(hosts: list[str], workers: int = 64, cache_path: Path = CACHE, chunk: int = 1000,
                 progress=print) -> dict[str, list[str]]:
    cache: dict[str, list[str]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    todo = [h for h in dict.fromkeys(hosts) if h not in cache]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        for i in range(0, len(todo), chunk):
            part = todo[i:i + chunk]
            for host, ips in zip(part, ex.map(_resolve, part)):
                cache[host] = ips
            cache_path.write_text(json.dumps(cache, sort_keys=True))
            if progress:
                progress(f"dns: {min(i + chunk, len(todo))}/{len(todo)} resolved")
    return {h: cache.get(h, []) for h in hosts}
