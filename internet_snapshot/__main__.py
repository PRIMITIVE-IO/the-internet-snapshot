"""Command line: ``python -m internet_snapshot {fetch,build,serve,sources}``."""

from __future__ import annotations

import argparse
import json
import sys
import time


def cmd_sources(args) -> int:
    from .sources import SOURCES
    for s in SOURCES.values():
        state = "downloaded" if s.available() else "missing"
        default = "default" if s.default else "opt-in"
        print(f"{s.id:14} {s.license_class:13} {default:8} {state:10} {s.name} [{s.license}]")
    return 0


def _allowed_classes(args) -> set[str]:
    classes = {"open"}
    if getattr(args, "sharealike", False):
        classes.add("sharealike")
    if getattr(args, "allow_noncommercial", False):
        classes.add("noncommercial")
    return classes


def cmd_fetch(args) -> int:
    from .sources import SOURCES, selected_sources
    failed = 0
    chosen = [SOURCES[x] for x in args.only] if args.only else selected_sources(args.source, _allowed_classes(args))
    for s in chosen:
        t = time.time()
        try:
            p = s.fetch(refresh=args.refresh)
            print(f"ok   {s.id:14} {p.stat().st_size/1e6:8.1f} MB  {time.time()-t:5.1f}s  [{s.license}]")
        except Exception as e:  # report and continue; the build decides what is required
            failed += 1
            print(f"FAIL {s.id:14} {e}", file=sys.stderr)
    return 1 if failed and args.strict else 0


def cmd_build(args) -> int:
    from .build.pipeline import run_build
    sid = run_build(resolve_dns=args.resolve_dns, use_caida=args.caida, crux_max_rank=args.crux_max_rank,
                    longtail_networks=args.networks, iters=args.iters, sites=not args.no_sites)
    print(sid)
    return 0


def cmd_pages(args) -> int:
    from .build.pages import build_pages
    print(build_pages(api_base=args.api_base or None, ip2asn=not args.no_ip2asn))
    return 0


def cmd_mcp(args) -> int:
    from .mcp_server import main as mcp_main
    return mcp_main(args.base)


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("internet_snapshot.server.app:app", host=args.host, port=args.port, proxy_headers=True,
                forwarded_allow_ips="*")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="internet_snapshot", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sources", help="list data sources and their licence classes").set_defaults(fn=cmd_sources)

    f = sub.add_parser("fetch", help="download raw public datasets into data/raw/")
    f.add_argument("--source", action="append", help="also fetch this opt-in source (repeatable)")
    f.add_argument("--only", nargs="+", help="fetch exactly these sources")
    f.add_argument("--refresh", action="store_true", help="re-download even if present")
    f.add_argument("--sharealike", action="store_true", help="allow share-alike licensed sources")
    f.add_argument("--allow-noncommercial", action="store_true", help="allow non-commercial sources")
    f.add_argument("--strict", action="store_true", help="exit non-zero if any download fails")
    f.set_defaults(fn=cmd_fetch)

    b = sub.add_parser("build", help="build a snapshot into public/snapshots/")
    b.add_argument("--resolve-dns", action="store_true", help="resolve service domains to attribute hosting ASNs")
    b.add_argument("--caida", action="store_true", help="use CAIDA as-rel2 relationships if downloaded")
    b.add_argument("--crux-max-rank", type=int, default=10_000)
    b.add_argument("--networks", type=int, default=1500, help="long-tail networks by address space")
    b.add_argument("--iters", type=int, default=160, help="layout iterations")
    b.add_argument("--no-sites", action="store_true", help="skip site graphs and the code universe")
    b.set_defaults(fn=cmd_build)

    pg = sub.add_parser("pages", help="assemble the GitHub Pages site in public/ (icons, ip2asn, agent files, viewer)")
    pg.add_argument("--api-base", default=None, help="public URL of a deployed API server, if any")
    pg.add_argument("--no-ip2asn", action="store_true")
    pg.set_defaults(fn=cmd_pages)

    m = sub.add_parser("mcp", help="run the MCP server (stdio) for AI agents")
    m.add_argument("--base", default=None, help="local snapshots dir or base URL (default: $SNAPSHOT_BASE_URL or ./public)")
    m.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("serve", help="run the snapshot API server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
