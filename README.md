# the-internet-snapshot

A living, viewable snapshot of the entire accessible internet: services grouped by function, the networks and CDNs that wire them together, and the route from *your* home network to each of them. It is laid out as a frozen 3D force-directed graph on concentric spherical shells, for display as a 360° skybox inside the Primitive environment.

It does **no crawling of its own**. It only uses public datasets that others already publish: CrUX, iptoasn, ipverse, Wikidata, CAIDA, PeeringDB, RouteViews and others. See [`docs/research/`](docs/research/).

## Documents

| Doc | For |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | Architecture, data sources, layout, LOD, routing, private overlays, roadmap |
| [`docs/snapshot-format.md`](docs/snapshot-format.md) | **Client contract**: file formats, coordinates (Unity conventions), API |
| [`docs/unity-integration.md`](docs/unity-integration.md) | Rendering guidance for the Primitive environment (Unity) |
| [`docs/research/`](docs/research/) | Survey of public internet-mapping datasets and prior art |

## Getting a snapshot

The latest published snapshot lives in [`public/snapshots/`](public/snapshots/). Start at `public/snapshots/latest.json`.
