# Snapshot format and API contract: format_version 0.2

This is the **wire contract** between the Internet Snapshot service and any client, in particular the Primitive environment (Unity). The design rationale is in [`DESIGN.md`](DESIGN.md).

Versioning rules:

- Within a `format_version` major.minor, only *additive* changes are made (new fields, new kinds).
- Clients must ignore unknown fields and unknown `kind` values.
- v0.2 is a strict superset of v0.1. It adds:
  - the `portal` and `glyph` node fields;
  - site graphs (§11), icons (§12), `locate` (§13), the agent activity overlay (§14) and agent discovery (§15);
  - GitHub Pages as the canonical host (§10).

---

## 1. Discovery

```
GET {base}/snapshots/latest.json
```

`{base}` is either of:

- the API server's `/v1` prefix, for example `https://<host>/v1`;
- any static mirror of `public/`:
  - The canonical public host is **GitHub Pages: `http://documentation.primitive.io/the-internet-snapshot`** (see §10).
  - Mirror: `https://raw.githubusercontent.com/PRIMITIVE-IO/the-internet-snapshot/main/public`. It carries the snapshots, but not the Pages-only `icons/` or `ip2asn/`.

Static mirrors serve every file. The query endpoints (`/v1/route`, `/v1/whereami`, `/v1/search`, `/v1/node`, `/v1/overlay`) need the API server.

```json
{
  "snapshot_id": "20261004-3f9c2a1b",
  "created_at": "2026-10-04T21:00:00Z",
  "format_version": "0.2",
  "manifest": "20261004-3f9c2a1b/manifest.json"
}
```

All other paths are relative to `{base}/snapshots/`. Everything under `<snapshot_id>/` is **immutable**: cache it forever. Only `latest.json` changes.

## 2. Coordinate system

Coordinates use **Unity conventions**:

- left-handed, **+Y up**, **+Z forward**, **+X right**;
- units are metres.

| Field | Meaning |
|---|---|
| `pos` | `[x, y, z]` world position. The viewer (home network) is at `[0, 0, 0]`. |
| `r` | Distance from the origin (the shell radius) |
| `az` | Azimuth in degrees, `[-180, 180)`, measured from +Z towards +X |
| `el` | Elevation in degrees, `[-90, 90]`, positive is up |

`pos = r · (cos(el)·sin(az), sin(el), cos(el)·cos(az))`

Shell radii are listed in `manifest.shells`. In v0.1:

| Shell | Radius | Contents |
|---|---|---|
| `home` | 0 | The viewer and their LAN (not in the snapshot) |
| `backbone` | 300 | Transit and access networks, IXPs, continent regions. **Geographic:** `az` = longitude, `el` = 0.85 × latitude. |
| `edge` | 600 | Clouds, CDNs, content networks |
| `services` | 1000 | Realms, categories, orgs and services, in functional sectors |

Service nodes sit at r ≈ 985 and orgs at r = 1000. This gives a little parallax. Always read the actual `r`.

## 3. `manifest.json`

```jsonc
{
  "format": "internet-snapshot",
  "format_version": "0.1",
  "snapshot_id": "20261004-3f9c2a1b",
  "created_at": "2026-10-04T21:00:00Z",
  "coordinate_system": { "handedness": "left", "up": "+Y", "forward": "+Z", "units": "m",
                         "geo_mapping": { "az": "longitude", "el": "latitude*0.85" } },
  "shells": { "home": 0, "backbone": 300, "edge": 600, "services": 1000 },
  "lods": [
    { "level": 0, "file": "lod0.json", "nodes": 17,   "edges": 40 },
    { "level": 1, "file": "lod1.json", "nodes": 95,   "edges": 300 },
    { "level": 2, "file": "lod2.json", "nodes": 2400, "edges": 9000 },
    { "level": 3, "tiling": { "scheme": "healpix-nested", "order": 1,
                              "path": "lod3/{order}-{ipix}.json" },
      "tiles": [ { "ipix": 0, "nodes": 210, "edges": 600, "bytes": 81234 } ],
      "nodes": 11000, "edges": 30000 }
  ],
  "realms":     [ { "id": "realm:communication", "label": "Communication", "color": "#4FC3F7" } ],
  "categories": [ { "id": "cat:email", "label": "Email", "realm": "realm:communication", "color": "#4FC3F7" } ],
  "network_roles": [ { "id": "tier1", "label": "Tier-1 transit", "color": "#FFD54F" } ],
  "files": { "anchors": "anchors.json", "asgraph": "asgraph.json", "search": "search.json",
             "domains": "domains.json" },
  "stats": { "nodes": 13512, "edges": 40211, "services": 10000, "networks": 3000 },
  "sources": [ { "id": "crux", "name": "Chrome UX Report top lists", "license": "CC BY 4.0",
                 "license_class": "open", "url": "…", "retrieved_at": "…" } ],
  "notes": [ "AS relationships are heuristic (seed roles + geography); …" ],   // build caveats, show in a debug panel
  "attribution": "Contains data from … (CC BY 4.0) …"
}
```

**Display requirement:** clients must show `attribution` somewhere reachable, for example a credits panel.

## 4. LOD files

Each level file and each LOD-3 tile has this shape:

```jsonc
{
  "snapshot_id": "20261004-3f9c2a1b",
  "level": 2,
  "tile": null,              // or { "order": 1, "ipix": 17 } for tiled levels
  "nodes": [ /* Node */ ],
  "edges": [ /* Edge */ ]
}
```

LOD uses **ADD refinement**. Level *k* contains only the nodes whose `lod == k` and the edges whose `lod == k`. A full view at level *k* is the union of levels 0…k.

LOD-3 tiles:

- A node goes into the HEALPix NESTED tile (order 1, 48 tiles) that contains its direction.
- HEALPix θ/φ are derived from the Unity direction like this: `θ = 90° − el` (colatitude), `φ = az` (in radians, wrapped to `[0, 2π)`).
- Each tile also carries the edges whose **source** node is in that tile.

### 4.1 Node

Every node object has the same keys. Keys that do not apply are `null`.

```jsonc
{
  "id": "svc:gmail.com",          // stable across snapshots (svc:<registrable domain or product hostname>)
  "kind": "service",              // realm | category | org | service | region | network | ixp
  "label": "Gmail",
  "lod": 3,
  "parent": "cat:email",          // spatial/semantic container (see below)
  "realm": "realm:communication", // service-shell nodes
  "category": "cat:email",        // service-shell nodes (and orgs: their primary category)
  "org": "org:google",            // owning org (services, networks)
  "region": null,                 // network-shell nodes: region:<slug>
  "role": null,                   // networks: tier1|transit|access|cloud|cdn|content|hosting|enterprise|education|government|ixp
  "shell": "services",
  "r": 985.0, "az": -72.4, "el": 18.2,
  "pos": [-893.1, 307.7, 284.3],
  "size": 0.82,                   // importance 0..1 (scale and cull by this)
  "color": "#4FC3F7",
  "rank": 1000,                   // popularity bucket (CrUX), lower = more popular; null if unknown
  "domain": "gmail.com",          // services
  "asn": null,                    // networks
  "country": null,                // ISO-3166 alpha-2 when known
  "icon": "gmail",                // simple-icons slug when known (https://simpleicons.org)
  "url": "https://mail.google.com",
  "glyph": "mail",                // v0.2: Lucide glyph name for what the node *is* (§12)
  "portal": "site:google"         // v0.2: site graph you can enter from this node (§11), or null
}
```

How `parent` chains:

- `realm` has no parent.
- `category` → `realm`.
- `org` → its primary `category`.
- `service`:
  - → its org, if the org lives in the same category;
  - otherwise → its category. Ownership is then expressed by `org` and an `owns` edge.
- `region` has no parent.
- `network` / `ixp` → `region`.

### 4.2 Edge

```jsonc
{
  "source": "svc:gmail.com",
  "target": "as:15169",
  "kind": "hosted_by",     // owns | hosted_by | operates | transit | peer | member | aggregate
  "lod": 3,
  "weight": 0.6,           // 0..1, suggested opacity/width
  "count": null,           // aggregates: number of underlying edges
  "a": [x, y, z],          // source position (copied, so tiles are self-contained)
  "b": [x, y, z]           // target position
}
```

- **`transit` direction:** `source` is the provider and `target` is the customer.
- **`peer`** is undirected.

**Drawing edges:** draw edges as **curved arcs**, not straight chords. Use the algorithm in §6.

## 5. Auxiliary files

**`anchors.json`** maps personal-overlay providers to snapshot nodes:

```json
{
  "google": { "anchor": "org:google",
              "products": { "gmail": "svc:gmail.com", "drive": "svc:drive.google.com",
                            "calendar": "svc:calendar.google.com" } },
  "github": { "anchor": "svc:github.com", "products": {} }
}
```

**`asgraph.json`** is a compact AS graph for offline routing:

```jsonc
{
  "nodes": { "3356": { "id": "as:3356", "pos": [..], "role": "tier1", "country": "US" } },
  "rels":  [ [3356, 7922, -1], [3356, 174, 0] ],  // [a, b, -1] = a provider of b; 0 = peers
  "tier1": [174, 701, 1299, 2914, 3257, 3320, 3356, 3491, 5511, 6453, 6461, 6762, 6830, 7018, 12956],
  "relationship_source": "heuristic-seed",          // or "caida-as-rel2"
  "hosting": { "svc:gmail.com": ["as:15169"] },     // service -> serving networks
  "org_networks": { "org:google": ["as:15169", "as:396982"] }
}
```

With the same propagation rules as the server (`internet_snapshot/routing.py`), a client can compute routes offline from `asgraph.json`.

In heuristic builds, guessed peerings exist only in `asgraph.json`; they are not drawn as `peer` edges. The tier-1 mesh is the exception. Edges inferred from CAIDA are all drawn.

**`domains.json`** maps every hostname/domain folded into a service (aliases and regional variants) to its node:

```json
{ "mail.google.com": "svc:gmail.com", "amazon.co.uk": "svc:amazon.com", "youtu.be": "svc:youtube.com" }
```

To resolve an arbitrary hostname, walk up its labels (`a.b.example.com` → `b.example.com` → `example.com`) until one matches.

**`search.json`** is an index of every node, for search UIs:

```jsonc
[ ["svc:gmail.com", "Gmail", "gmail.com", 3] ]   // [id, label, domain or null, lod]
```

## 6. Arc drawing (edges and routes)

To draw a curve from point **A** to point **B**:

- **If either point is the origin (home):** draw a straight segment. Optionally bow it slightly upward.
- **Otherwise:** for `t` in `0…1` (24–48 samples):
  - `dir(t) = slerp(normalize(A), normalize(B), t)`
  - `r(t) = lerp(|A|, |B|, t) − bulge · sin(π·t)`, with `bulge = 0.08 · angle(A,B)/π · min(|A|,|B|)`
  - `P(t) = r(t) · dir(t)`

  The bulge pulls long arcs slightly *inward*, toward the viewer, so they stay visible.

## 7. Routes API

```
GET /v1/route?to=<node-id | domain>[&asn=<home ASN>][&ip=<home IP>]
```

If neither `asn` nor `ip` is given, the server uses the caller's public IP.

```jsonc
{
  "snapshot_id": "20261004-3f9c2a1b",
  "from": { "ip": "73.x.x.x", "asn": 7922, "node": "as:7922", "label": "Comcast", "in_snapshot": true,
            "pos": [..] },
  "to":   { "query": "gmail.com", "node": "svc:gmail.com", "network": "as:15169", "pos": [..] },
  "method": "valley-free",        // observed | valley-free | fallback
  "confidence": "medium",         // high | medium | low
  "relationship_source": "heuristic-seed",
  "as_path": [7922, 3356, 15169],
  "hops": [
    { "seq": 0, "node": "home",          "kind": "home",    "label": "Home network", "pos": [0,0,0], "rel": null },
    { "seq": 1, "node": "as:7922",       "kind": "network", "label": "Comcast",      "pos": [..], "rel": "origin" },
    { "seq": 2, "node": "as:3356",       "kind": "network", "label": "Lumen",        "pos": [..], "rel": "up" },
    { "seq": 3, "node": "as:15169",      "kind": "network", "label": "Google",       "pos": [..], "rel": "peer" },
    { "seq": 4, "node": "svc:gmail.com", "kind": "service", "label": "Gmail",        "pos": [..], "rel": "served" }
  ]
}
```

`rel` values:

- `up`: customer → provider.
- `peer`: across a peering link.
- `down`: provider → customer.
- `sibling`: same org.
- `served`: final hop into the service.

```
GET /v1/whereami            → the "from" object above, plus "country"
```

If the home AS is not in the snapshot, the server creates a synthetic node: `"in_snapshot": false`, positioned at its country's centroid on the backbone shell.

## 8. Personal overlays

### 8.1 Connector discovery

```
GET /v1/connectors
```

```jsonc
[ { "provider": "github", "label": "GitHub", "anchor": "svc:github.com",
    "auth": { "type": "oauth2", "scopes": ["read:user", "read:org", "repo"],
              "authorize_url": "https://github.com/login/oauth/authorize",
              "token_url": "https://github.com/login/oauth/access_token" },
    "proxy": "/v1/overlay/github" } ]
```

### 8.2 Stateless proxy

```
POST /v1/overlay/{provider}
Authorization: Bearer <provider access token>
Content-Type: application/json
{ "account_index": 0, "account_count": 1, "max_assets": 60 }
```

- The body is optional.
- To show several accounts for one provider, call the endpoint once per token and pass `account_index` / `account_count`, so the accounts spread around the anchor.
- The response has `Cache-Control: no-store`. Nothing is persisted.

### 8.3 Overlay document

The same shape applies whether the overlay comes from the proxy or is built client-side.

```jsonc
{
  "overlay_version": "0.1",
  "snapshot_id": "20261004-3f9c2a1b",
  "provider": "github",
  "account": { "id": "ov:github:583231", "label": "octocat" },
  "warnings": [ "orgs: HTTP 403 (needs read:org)" ],     // partial results are still returned
  "nodes": [
    { "id": "ov:github:583231", "kind": "account", "label": "octocat", "parent": "svc:github.com",
      "anchor": "svc:github.com", "pos": [..], "r": .., "az": .., "el": .., "size": 0.5, "color": "#FFFFFF",
      "meta": { "type": "user" } },
    { "id": "ov:github:583231:group:repos", "kind": "group", "label": "Repositories", "parent": "ov:github:583231", … },
    { "id": "ov:github:583231:repo:octocat/hello-world", "kind": "asset", "label": "hello-world",
      "parent": "ov:github:583231:group:repos", "meta": { "type": "repo", "private": false, "stars": 2000,
      "language": "Ruby", "url": "https://github.com/octocat/hello-world" }, … }
  ],
  "edges": [ { "source": "ov:github:583231", "target": "svc:github.com", "kind": "attached", "a": [..], "b": [..] },
             { "source": "ov:github:583231:group:repos", "target": "ov:github:583231", "kind": "contains", … } ]
}
```

### 8.4 Placement algorithm

The placement is deterministic, so clients may build overlays themselves.

**Inputs.** An anchor position `P` with radius `rA = |P|` and direction `u = P / rA`.

**Tangent frame:**

1. `e = normalize(cross(Y, u))`, where `Y = (0,1,0)`. If `|cross(Y,u)| < 1e-6`, use `Z = (0,0,1)` instead of `Y`.
2. `n = cross(u, e)`.

Here `cross(a,b) = (a.y·b.z − a.z·b.y, a.z·b.x − a.x·b.z, a.x·b.y − a.y·b.x)`.

**Offset helper.** `offset(u, dx°, dy°) = normalize(u + tan(dx)·e + tan(dy)·n)`.

**Placement rules:**

- **Account `i` of `N`:**
  - if `N = 1`: direction `u`;
  - otherwise: `offset(u, 1.2°·cos(2πi/N), 1.2°·sin(2πi/N))`;
  - radius `rA − 25`.
- **Group `g` of `G`** within an account (for example Gmail, Drive, Calendar):
  - if the group has its own product anchor in `anchors.json` and that node exists, centre the group near the product anchor at radius `r_product − 25`:
    - if `N = 1`: direction `u_product`;
    - otherwise: `offset(u_product, 0.8°·cos(2πi/N), 0.8°·sin(2πi/N))`, where `i`/`N` are the account index and count;
  - otherwise: `offset(u_account, 0.6°·cos(2πg/G + π/4), 0.6°·sin(2πg/G + π/4))` at radius `rA − 28`.
- **Asset `j` of `M`** within a group, using phyllotaxis:
  - `ρ = 0.5° · sqrt((j + 0.5) / M)`, `θ = j · 137.50776°`;
  - direction `offset(u_group, ρ·cos θ, ρ·sin θ)`;
  - radius `r_group − 3`.

When computing an offset around an account, group or product node, use that node's direction as `u` and build the tangent frame from it.

## 9. Other endpoints

```
GET /v1/search?q=git&limit=20     → [{ "id", "label", "kind", "domain", "lod", "pos" }]
GET /v1/node/{id}                 → { "node": Node, "edges": [Edge], "children": [ids] }
GET /healthz                      → { "ok": true, "snapshot_id": … }
```

---

# v0.2 additions

## 10. Hosting: GitHub Pages and static-only operation

**Base URL:** `http://documentation.primitive.io/the-internet-snapshot`. Every file below is relative to it.

- The PRIMITIVE-IO organisation serves GitHub Pages from its custom domain, and `https://primitive-io.github.io/the-internet-snapshot/` redirects there.
- Once *Enforce HTTPS* is enabled for that domain, use `https://`.
- `agent.json` always carries the URL that GitHub reports for the current deployment, so read the base from there.

```
snapshots/latest.json                      mutable pointer (≈10 min CDN cache)
snapshots/<id>/…                           immutable snapshot, including sites/
icons/index.json, icons/atlas-64.png, icons/glyphs/<name>.svg, icons/brands/<slug>.svg
ip2asn/v4/index.json, ip2asn/v4/<first-octet>.json
agent.json, llms.txt
index.html                                 reference viewer
```

### 10.1 `ip2asn` shards: finding the home AS without a server

`ip2asn/v4/index.json`:

```json
{ "source": "sapics/ip-location-db origin-asn", "license": "PDDL-1.0", "generated_at": "…", "shards": 224 }
```

`ip2asn/v4/<a>.json` holds the ranges whose first octet is `a`:

```jsonc
{ "ranges": [[16777216, 16777471, 13335], …] }   // [start, end, asn], 32-bit unsigned ints, sorted by start
```

**Lookup:**

1. Convert the IPv4 address to a uint32.
2. Fetch shard `a` (the first octet).
3. Binary-search for the last range with `start ≤ ip`, and check `ip ≤ end`.

The client must know its own public IP, for example from its platform backend or a STUN binding request. A missing shard or no match means the AS is unknown.

### 10.2 Client-side routing

With `asgraph.json` (§5) a client can compute routes without the server. Let `dst` be the destination AS:

1. **Customer routes.** Breadth-first search from `dst` up provider links. An AS reached this way has route type *customer*, length = BFS depth, next hop = the AS it was reached from.
2. **Peer routes.** For every AS with a customer route (and for `dst` itself), each of its peers that has no route yet gets type *peer*, length + 1.
3. **Provider routes.** In order of route length, push routes down provider→customer links to ASes with no customer or peer route.
4. **Ties** are broken by lower length, then lower next-hop ASN. Follow next hops from the source AS to `dst`.

If the home AS is unknown, attach it as a customer of two tier-1s from its region. The reference implementation is `internet_snapshot/routing.py`.

## 11. Site graphs

### 11.1 Index

The manifest gains `"files": { …, "sites": "sites/index.json" }`.

```jsonc
// snapshots/<id>/sites/index.json
{
  "snapshot_id": "…",
  "sites": [
    { "id": "site:google", "kind": "site", "label": "Google", "root_node": "org:google",
      "file": "sites/google.json", "nodes": 640, "edges": 120, "bytes": 312345, "max_depth": 4,
      "icon": "google", "hosts": ["google.com", "googleapis.com", "…"] },
    { "id": "site:code-universe", "kind": "code", "label": "GitHub code universe", "root_node": "svc:github.com",
      "file": "sites/code-universe.json", … }
  ]
}
```

A global node whose `portal` is non-null can be entered: load the referenced site file.

### 11.2 Site graph file

```jsonc
{
  "graph_version": "0.2",
  "snapshot_id": "…",
  "id": "site:github", "kind": "site", "label": "GitHub", "root_node": "svc:github.com",
  "radius": 1000, "max_depth": 4, "shells": [0, 250, 500, 750, 1000],
  "nodes": [ SiteNode ],
  "edges": [ SiteEdge ],
  "sources": [ { "id", "name", "license", "url" } ],
  "attribution": "…"
}
```

**Coordinates.** They are the same as the global snapshot: Unity axes, metres. The **site itself is at the origin**, so a viewer standing at the origin sees the site as a skybox. To show the site miniaturised at its global node, scale by `s = desired_radius / radius` and translate to that node's `pos`.

**SiteNode.** Every SiteNode object has the same keys:

```jsonc
{
  "id": "site:github/api/issues/GET /repos/{owner}/{repo}/issues",
  "kind": "operation",       // site | surface | product | section | host | api-group | api | endpoint | operation
                             // code universe: universe | ecosystem | language | cluster | owner | repo
  "label": "List repository issues",
  "parent": "site:github/api/issues",
  "depth": 4,
  "r": 1000.0, "az": 12.3, "el": -4.5, "pos": [x, y, z],
  "size": 0.42,              // importance 0..1 within this graph
  "color": "#64FFDA",        // inherited from the depth-1 branch
  "icon": "github",          // Simple Icons slug or null
  "glyph": "circle-dot",     // Lucide glyph name or null
  "url": "https://docs.github.com/rest/issues/issues#list-repository-issues",   // human/doc link
  "host": "api.github.com",  // for matching (§13); may start with "*." for a wildcard
  "path": "/repos/{owner}/{repo}/issues",   // path template, or null
  "method": "GET",           // HTTP method, or null
  "portal": null,            // another site graph enterable from here (e.g. GitHub → "site:code-universe")
  "meta": { }                // free-form: global (linked global node id), crux_rank, operations, stars, avatar, …
}
```

**SiteEdge:**

```jsonc
{ "source", "target", "kind", "weight", "a": [x,y,z], "b": [x,y,z] }
```

| `kind` | Meaning |
|---|---|
| `serves` | A host serves a product |
| `implements` | An API backs a product |
| `same_resource` | A web section and its API group |
| `maintains` | An owner and its repos (code universe) |
| `links_to` | Reserved for page-link edges |

Parent/child containment is the `parent` field.

### 11.3 Code universe specifics

The code universe has `kind: "code"`, `id: "site:code-universe"`, and `root_node: "svc:github.com"`. Its node kinds:

- `ecosystem`: for example `.NET (NuGet)`. `meta.registry` is the package registry.
- `language`
- `cluster`: a purpose, such as web framework or machine learning.
- `owner`: an owner with three or more top repos.
- `repo`, with `meta`: `full_name`, `stars`, `forks`, `language`, `description`, `owner`, `avatar` (when known), `last_commit`, `rank_in_language`.

## 12. Icons

`icons/index.json`:

```jsonc
{
  "atlases": [ { "file": "icons/atlas-64.png", "cell": 64, "width": 2048, "height": 2048,
                 "cells": { "glyph:mail": [0, 0], "brand:github": [64, 0], … } } ],   // top-left pixel of each cell
  "svg": { "glyph": "icons/glyphs/{name}.svg", "brand": "icons/brands/{name}.svg" },
  "brand_colors": { "github": "#181717", … },
  "licenses": { "glyph": "Lucide (ISC)", "brand": "Simple Icons (CC0); logos are trademarks of their owners" }
}
```

- Icons are **white on transparent**, so tint them in the shader. Use the node `color`, or `brand_colors` for brands.
- UV for a cell `[x, y]`: `u0 = x/width`, `v0 = 1 − (y+cell)/height`, `u1 = (x+cell)/width`, `v1 = 1 − y/height`.
- Fallback when a name is missing from the atlas: use the glyph `circle`.

## 13. Locate: URL → place in the map

```
GET /v1/locate?url=https://api.github.com/repos/octocat/hello/issues&method=GET
```

```jsonc
{
  "url": "…", "host": "api.github.com",
  "global": { "node": "svc:github.com", "label": "GitHub", "kind": "service", "pos": [..] },
  "site":   { "id": "site:github", "node": "site:github/api/issues/GET /repos/{owner}/{repo}/issues",
              "path": ["site:github", "site:github/api", "site:github/api/issues", "…"], "pos": [..] },
  "operation": { "method": "GET", "path": "/repos/{owner}/{repo}/issues", "doc_url": "https://docs.github.com/…" },
  "match": "operation",  // operation | path | host | domain | none
  "also": { "id": "site:code-universe", "node": "…" }   // optional secondary match, e.g. a github.com repo URL
}
```

### 13.1 Algorithm

Clients may implement it themselves.

1. **Global node.** Walk up the host labels against `domains.json`.
2. **Site.** The site is the global node's `portal`. Failing that, use its org's `portal`.
3. **Candidates.** In the site graph, take nodes whose `host` equals the URL host, or whose `host` is `*.suffix` and the URL host ends with `.suffix`.
4. **Path matching.** Among the candidates that have a `path`, compare segment by segment. A `{param}` segment matches any single segment.
   - Prefer, in order: the most literal segments, then the longest template, then a `method` match.
   - An exact operation match is `operation`. A path-prefix match is `path`.
5. **Fallbacks.**
   - If no path matches, the shallowest node with that host is a `host` match.
   - If the site only has the domain, it is a `domain` match.

### 13.2 Site-graph endpoints (API server)

```
GET  /v1/sites                              → { "snapshot_id", "sites": [index entries] }
GET  /v1/sites/{site_id}                    → site graph document
GET  /v1/sites/{site_id|node|domain}/summary?depth=2      → top of the hierarchy, with child counts
GET  /v1/sites/{site_id|node|domain}/endpoints?q=issues   → matching operations, APIs, hosts and sections
GET  /v1/code-universe[?ecosystem=maven&q=spring]         → ecosystems, or top repos
POST /v1/site-graph   { "urls": [...], "label"? }          → on-demand site graph from visited URLs (no-store)
POST /v1/activity     { "events": [...] }                  → agent activity overlay (no-store)
```

## 14. Agent activity overlay

The client records its agents' activity. An **ActivityEvent** looks like this:

```jsonc
{ "agent": "planner-1", "ts": "2026-10-04T21:00:00Z", "kind": "http",   // http | browse | tool
  "method": "GET", "url": "https://api.github.com/repos/o/r/issues", "status": 200, "duration_ms": 120 }
```

It turns events into an overlay. It can do this locally (§13), or with the stateless endpoint `POST /v1/activity` (body `{ "events": [...], "asn": <home ASN, optional> }`):

```jsonc
{
  "overlay_version": "0.2", "kind": "agent-activity", "snapshot_id": "…",
  "agents": [
    { "id": "ag:planner-1", "label": "planner-1", "color": "#FF4081",
      "at": { "space": "global", "node": "svc:github.com", "pos": [..] },
      "at_site": { "space": "site:github", "node": "site:github/api/issues/…", "pos": [..] },
      "trail": [ { "ts": "…", "space": "global", "node": "svc:github.com", "pos": [..], "match": "operation" } ] }
  ],
  "heat": [ { "space": "global", "node": "svc:github.com", "count": 12 },
            { "space": "site:github", "node": "site:github/api/issues", "count": 9 } ]
}
```

- `space` is `"global"` (global coordinates) or a site id (that site's local coordinates).
- Agent colours are deterministic per agent id: hue = hash(id) mod 360.
- Draw the route from home to a new service once per agent per service, using `/v1/route` or §10.2.
- Nothing about activity is stored by this service.

## 15. Agent discovery and MCP

`agent.json` (on Pages):

```jsonc
{
  "name": "the-internet-snapshot", "description": "…",
  "data": { "base": "http://documentation.primitive.io/the-internet-snapshot", "latest": "snapshots/latest.json",
            "contract": "https://github.com/PRIMITIVE-IO/the-internet-snapshot/blob/main/docs/snapshot-format.md" },
  "api": { "base": null },          // set when an API server is deployed
  "mcp": { "command": "python", "args": ["-m", "internet_snapshot", "mcp"],
           "install": "pip install git+https://github.com/PRIMITIVE-IO/the-internet-snapshot",
           "env": { "SNAPSHOT_BASE_URL": "http://documentation.primitive.io/the-internet-snapshot" } },
  "tools": ["search", "describe", "locate", "route", "site_graph", "list_endpoints", "code_universe", "whereami"],
  "attribution": "…"
}
```

The MCP server's tools mirror the API. Results are JSON and use the node ids of this contract, so an agent's tool results can be placed directly in the Primitive environment.
