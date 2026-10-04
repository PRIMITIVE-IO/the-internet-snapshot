# Snapshot format and API contract: format_version 0.1

This is the **wire contract** between the Internet Snapshot service and any client, in particular the Primitive environment (Unity). The design rationale is in [`DESIGN.md`](DESIGN.md).

Versioning rules:

- Within a `format_version` major.minor, only *additive* changes are made (new fields, new kinds).
- Clients must ignore unknown fields and unknown `kind` values.

---

## 1. Discovery

```
GET {base}/snapshots/latest.json
```

`{base}` is either of:

- the API server's `/v1` prefix, for example `https://<host>/v1`;
- any static mirror of `public/` (for example GitHub raw `…/main/public`).

```json
{
  "snapshot_id": "20261004-3f9c2a1b",
  "created_at": "2026-10-04T21:00:00Z",
  "format_version": "0.1",
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
  "files": { "anchors": "anchors.json", "asgraph": "asgraph.json", "search": "search.json" },
  "stats": { "nodes": 13512, "edges": 40211, "services": 10000, "networks": 3000 },
  "sources": [ { "id": "crux", "name": "Chrome UX Report top lists", "license": "CC BY 4.0",
                 "license_class": "open", "url": "…", "retrieved_at": "…" } ],
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
  "id": "svc:gmail.com",          // stable across snapshots
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
  "url": "https://mail.google.com"
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
  "tier1": [174, 701, 1299, 2914, 3257, 3320, 3356, 3491, 5511, 6453, 6461, 6762, 6830, 7018, 12956]
}
```

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
