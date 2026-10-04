# the-internet-snapshot

A living, viewable snapshot of the entire accessible internet: services grouped by function, the networks and CDNs that wire them together, and the route from *your* home network to each of them. It is laid out as a frozen 3D force-directed graph on concentric spherical shells, for display as a 360° skybox inside the Primitive environment.

It does **no crawling of its own**. It only uses public datasets that others already publish: CrUX, iptoasn/origin-asn, ipverse, the Public Suffix List and DSPL; CAIDA, PeeringDB and Wikidata are planned or opt-in. See [`docs/research/`](docs/research/).

**Latest snapshot (public):**
<https://raw.githubusercontent.com/PRIMITIVE-IO/the-internet-snapshot/main/public/snapshots/latest.json>

## Documents

| Doc | For |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | Architecture, data sources, layout, LOD, routing, private overlays, roadmap, and what v0.1 does and does not do yet (§11) |
| [`docs/snapshot-format.md`](docs/snapshot-format.md) | **Client contract**: file formats, coordinates (Unity conventions), API |
| [`docs/unity-integration.md`](docs/unity-integration.md) | Rendering guidance for the Primitive environment (Unity) |
| [`docs/research/`](docs/research/) | Survey of public internet-mapping datasets and prior art |

## Shape of the snapshot

```
r = 0      home (the viewer's network)
r = 300    backbone shell: transit and access ISPs, IXPs (geographic: az = longitude)
r = 600    edge shell: clouds and CDNs, placed behind the services they host
r = 1000   service shell: 10 realms → 38 categories → orgs → services (equal-area sectors)
LOD 0 (17 nodes) → LOD 1 (86) → LOD 2 (≈2k) → LOD 3 (≈9k, 48 HEALPix tiles)
```

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python -m internet_snapshot sources                 # list sources and their licence classes
python -m internet_snapshot fetch                   # download open-licence datasets to data/raw/
python -m internet_snapshot build --resolve-dns     # build into public/snapshots/<id>/ and update latest.json
python -m internet_snapshot serve --port 8000       # API + viewer at http://localhost:8000/viewer/

pip install pytest anyio && python -m pytest -q     # unit, contract-conformance, routing, overlay and server tests
```

Opt-in sources with "ask first" licences (CAIDA AS relationships) are enabled with
`fetch --source caida_asrel` and `build --caida`. Only enable them once the licence allows your use.

Docker: `docker build -t internet-snapshot . && docker run -p 8000:8000 internet-snapshot`.

The snapshot is rebuilt weekly by [`.github/workflows/build-snapshot.yml`](.github/workflows/build-snapshot.yml).

## API (summary)

| Endpoint | |
|---|---|
| `GET /v1/snapshots/latest.json`, `GET /v1/snapshots/{id}/{file}` | Snapshot files (immutable, gzip) |
| `GET /v1/whereami` | Caller IP → home AS → backbone position |
| `GET /v1/route?to=gmail.com[&asn=…]` | Home → destination route (valley-free AS path with 3D hop positions) |
| `GET /v1/search?q=…`, `GET /v1/node/{id}` | Lookup |
| `GET /v1/connectors`, `POST /v1/overlay/{github,google}` | Personal overlays (stateless; tokens are never stored) |

## Licence

Code: MIT. Each snapshot's `manifest.json` lists its data sources, their licences and the required attribution (`attribution`).
