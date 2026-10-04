# The Internet Snapshot: design document

**Status:** v0.1, 2026-10-04. The first working version is implemented and published. See §11 for what the current build contains and what is still approximate.
**Audience:** two groups:

- people building the snapshot pipeline;
- the agent or engineers integrating the snapshot into the **Primitive environment** (Unity).

The wire contract that clients code against is [`snapshot-format.md`](snapshot-format.md).
Unity-specific rendering guidance is in [`unity-integration.md`](unity-integration.md).

---

## 1. Purpose

Build a **living, viewable snapshot of the entire accessible internet**. Any Primitive environment client can download it and render it as a 360° "cyberspace" around the viewer.

The snapshot has four parts:

1. **Structure.** It shows the internet's *services*, grouped by function: social media, developer tools, cloud, email, streaming, finance, AI, and so on.
2. **Wiring.** It shows the internet's *networks*: transit backbones, eyeball/access ISPs, IXPs, clouds and CDNs. It also shows the *route* traffic would take from the viewer's home network to any service.
3. **Frozen layout.** Everything is laid out as a **frozen 3D force-directed layout on concentric spherical shells**. The viewer stands at the centre, which is their home network, and sees the internet as a skybox.
4. **Private personal layer.** The user connects their own accounts (Google, GitHub, …). The slice of each service that the user controls appears as a small cluster attached to that service's node. For example, Gmail and Drive folders hang off Google, and repos hang off GitHub.

### Division of responsibility

| This service (`the-internet-snapshot`) | Primitive environment (Unity, other agent) |
|---|---|
| Researching and ingesting public datasets | Rendering, interaction, camera, UI |
| Building the graph, hierarchy and frozen layout | Choosing LOD at runtime from the view |
| Publishing immutable, versioned snapshot files | Downloading and caching snapshots |
| Route inference (home → destination) | Drawing routes |
| Personal-overlay connectors and the anchoring/placement contract | Holding the user's tokens and showing overlays |

This service never changes the Primitive environment. It only publishes data and a contract.

### Non-goals

- **No crawling or active measurement of our own.** We only consume datasets that other organisations already publish. See §3.
- No real-time traffic visualisation in v1. Snapshots are periodic.

---

## 2. Design principles

1. **Level of detail first.**
   - The top level of abstraction always loads first, and it is tiny: a few dozen nodes.
   - Deeper levels are only fetched when the viewer needs them.
   - Each level *adds* nodes (ADD refinement), so a client never has to hide parents.
2. **Frozen and deterministic.**
   - The layout is computed offline with fixed seeds.
   - A snapshot never changes after it is published. Its directory name contains a content hash.
   - New snapshots are seeded from the previous layout, so things stay put between versions.
3. **Meaningful axes.** Following CAIDA AS Core, Halcyon and internet-map research (see `research/03`):
   - **Network shells are geographic.** Azimuth is longitude and elevation is latitude.
   - **The service shell is functional.** It is divided into equal-area category sectors.
   - **Radius is the layer of the stack:** home → access/backbone → edge/cloud → services.
4. **Licence-clean by default.**
   - Every source carries a licence class.
   - The default build only uses sources whose derived data can be redistributed commercially.
   - Opt-in flags enable "ask-first" sources and non-commercial sources.
   - The manifest lists every source and its attribution.
5. **Private stays private.**
   - Personal overlays are never stored server-side and never become part of a snapshot.
   - The preferred mode runs connectors on the client.

---

## 3. Data sources (no crawling)

The full survey is in [`research/`](research/). The table below lists what the pipeline uses.

| Purpose | Source | Licence class | Default |
|---|---|---|---|
| Service universe and popularity | **Chrome UX Report top lists** (global plus per country) | CC BY 4.0 | ✅ |
| Origin → registrable domain | **Public Suffix List** | MPL-2.0 | ✅ |
| Curated taxonomy, org ↔ service ↔ ASN catalogue | **`seed/` (this repo)** | ours (MIT) | ✅ |
| AS names and countries | **ipverse/asn-info** | CC0 | ✅ |
| Prefix → origin AS, address-space weight | **iptoasn / sapics origin-asn** | PDDL | ✅ |
| Country centroids (geo anchors) | **Google DSPL countries.csv** | CC BY | ✅ |
| Domain → hosting AS | DNS A lookups at build time, then the origin-asn table | factual | opt-in `--resolve-dns` (on in published builds) |
| Cloud provider ranges | AWS / GCP / Azure / Cloudflare / Fastly / Oracle JSON | factual | planned |
| Owner org and category for the long tail | **Wikidata** (P856/P31/P127/P749) | CC0 | planned (v0.2) |
| Functional categories, gap fill | UT1 blacklists | CC BY-SA (tagged) | opt-in `--sharealike` |
| AS relationships and tier-1 clique | **CAIDA as-rel2** | ask first | opt-in `--source caida_asrel` |
| IXPs and facilities | PeeringDB | ask first | planned, opt-in |
| Eyeball population per AS | APNIC aspop | ask first | planned, opt-in |
| Org grouping and third-party categories | DuckDuckGo Tracker Radar | CC BY-NC-SA | not used (non-commercial) |
| Domain categories and rankings | Cloudflare Radar | CC BY-NC | not used (non-commercial) |

**Planned clean replacements**, tracked in §10:

- AS relationships inferred by ourselves from **RouteViews RIBs** (CC BY), via BGPKIT, replacing CAIDA.
- OpenStreetMap submarine cables (ODbL), replacing TeleGeography.
- OpenINTEL toplist DNS for domain → IP → ASN.

### Bootstrapping

The **curated seed** is the high-abstraction skeleton.

- It is hand-maintained and covers about 500 of the most important services, their owners, categories and ASNs.
- It covers the backbone: tier-1 carriers, hyperscalers, CDNs, major IXPs and large eyeball ISPs, with their known relationships.

Public datasets then fill in the long tail beneath it:

- CrUX supplies about 10k services.
- iptoasn and asn-info supply thousands of networks.
- CAIDA supplies the full relationship graph when it is enabled.

---

## 4. Data model

### 4.1 Node kinds and IDs

IDs are stable across snapshots. Clients may persist them.

| Kind | ID pattern | Example | Shell |
|---|---|---|---|
| `realm` | `realm:<slug>` | `realm:communication` | services |
| `category` | `cat:<slug>` | `cat:email` | services |
| `org` | `org:<slug>` | `org:google` | services |
| `service` | `svc:<registrable-domain>` | `svc:gmail.com`, `svc:github.com` | services |
| `region` | `region:<slug>` | `region:europe` | backbone |
| `network` | `as:<asn>` | `as:15169`, `as:3356` | backbone or edge |
| `ixp` | `ix:<slug>` | `ix:de-cix-frankfurt` | backbone |

Each node records:

- its `realm` and `category` (service-side nodes), or its `region` and `role` (network-side nodes);
- its hierarchy `parent`;
- the `lod` level at which it first appears.

### 4.2 Hierarchy

```
Services shell:  realm ─▶ category ─▶ org ─▶ service
                 (an org lives in the category of its primary service;
                  its other services sit in their own categories, linked by `owns` edges)
Network shells:  region ─▶ network (AS) / ixp
```

### 4.3 Edge kinds

| Kind | Meaning |
|---|---|
| `owns` | org → service. The org's services that live in other categories. |
| `hosted_by` | service → network: who serves the service (origin AS or CDN/cloud AS) |
| `operates` | org → network: the org runs this AS (Google → AS15169) |
| `transit` | provider AS → customer AS (p2c) |
| `peer` | AS ↔ AS settlement-free peering (p2p) |
| `member` | network → IXP |
| `aggregate` | Roll-up of the edges above between two aggregate nodes at a coarse LOD. Carries `count` and `weight`. |

Parent/child containment is expressed by the node's `parent` field. It is not an edge.

### 4.4 Functional taxonomy (v1)

There are 10 realms and about 35 categories. The full list, with colours, is in `seed/taxonomy.json`.

| Realm | Categories |
|---|---|
| Communication | social, messaging, email, video-calls, forums |
| Media & Entertainment | video, music, gaming, news |
| Commerce & Finance | shopping, payments, banking, crypto, travel |
| Knowledge & Discovery | search, reference, education, maps |
| Work & Productivity | productivity, collaboration, storage, business, design |
| Developer & AI | code, devtools, ai, apis |
| Cloud & Edge | cloud, cdn, dns, identity |
| Advertising & Analytics | ads, analytics |
| Society & Public | government, health, nonprofit |
| The Long Tail | web (services not yet classified, grouped by country/TLD) |

---

## 5. Spatial design: cyberspace as a skybox

The viewer stands at the **origin**, which represents their **home network** (the network the Primitive environment runs in). The internet surrounds them on concentric shells. Moving outward from the origin is moving outward through the internet's layers.

```
             r = 0      HOME (viewer; computed per client, not in snapshot)
             r = 300    BACKBONE shell — transit & access networks, IXPs. Geographic.
             r = 600    EDGE shell — clouds, CDNs, content networks. Pulled toward what they host.
             r = 1000   SERVICE shell — realms → categories → orgs → services. Functional sectors.
```

### Coordinate system

The canonical coordinate system is **Unity's**:

- left-handed, **+Y up**, +Z forward, +X right;
- 1 unit = 1 m;
- azimuth `az` is in degrees, measured from +Z towards +X (a compass heading);
- elevation `el` is in degrees above the horizontal plane;
- `pos = r · (cos el · sin az, sin el, cos el · cos az)`.

Every node carries `pos` and also `az`/`el`/`r`, so clients can rescale freely.

**Geographic convention (network shells):**

- `az = longitude`, so Greenwich is straight ahead (+Z) and east is to the right;
- `el = latitude × 0.85`, compressed slightly so that polar nodes don't bunch at the zenith.

### 5.1 Service shell layout

1. **Sector allocation.** The sphere is divided into HEALPix equal-area cells (order 4, 3,072 cells).
   - Each realm gets a contiguous region whose area is proportional to its weight. The weight is a damped total popularity of its services.
   - The regions are grown by multi-source BFS over HEALPix neighbours from well-spaced seed directions.
   - Related realms are seeded next to each other. For example, Developer & AI sits next to Cloud & Edge.
   - Categories are then allocated inside their realm's region in the same way.
2. **Force-directed placement.** Org and service nodes are laid out with a **spherical spring embedder** (Kobourov–Wampler): forces are computed in the tangent plane and every node is renormalised onto its shell after each step. The forces are:
   - attraction along `owns` edges (service ↔ org);
   - weak attraction toward shared infrastructure (services hosted by the same CDN cluster together);
   - pairwise repulsion;
   - a **containment force** that keeps each node inside its category's cells.

   The result is frozen: a fixed seed and a fixed number of iterations.
3. **Aggregates.** A category node sits at the area centroid of its cells, and a realm node at the centroid of its region.

### 5.2 Network shells

- **Backbone shell (r = 300):** transit ASes, access/eyeball ASes and IXPs.
  - Each one is seeded at its registration country's centroid (geographic convention).
  - It is then relaxed with a spherical force layout that combines relationship springs (`transit`, `peer`) with a geographic anchor spring.
  - Tier-1 / global transit networks have a weak geo anchor, so they settle among their customers.
  - `region:*` aggregates sit at continent centroids.
- **Edge shell (r = 600):** clouds, CDNs and content networks (Google, Meta, Amazon, Cloudflare, Akamai, …).
  - Each is placed in the **direction of the weighted centroid of the services it hosts**, then relaxed with repulsion.
  - A CDN therefore hangs "behind" the services it delivers, between the backbone and the service shell.

### 5.3 Why this works as a skybox

- From the origin, every node has a well-defined direction, and the service shell covers the full 360° × 180°.
- The inner shells are sparse point clouds. They give parallax and depth without hiding the sky.
- If a client wants a strict skybox, with the camera locked at the origin, it can bake the outer shell into a cubemap. All positions are directions, so the baking is exact.

---

## 6. Level of detail

ADD refinement: each level adds nodes and edges on top of the previous levels. Target sizes for the v1 build:

| LOD | Service shell | Network shells | Edges | Delivery | v0.1 build |
|---|---|---|---|---|---|
| 0 | 10 realms | 7 continent regions | realm↔region aggregates | one file | 17 nodes, 11 KB |
| 1 | 38 categories | about 50 major networks (tier-1s, hyperscalers, CDNs, big content) | category↔network aggregates, tier-1 peering | one file | 86 nodes, about 75 KB |
| 2 | multi-service orgs, all curated services, CrUX top-1k services | 800 most important networks, IXPs | `owns`, `hosted_by`, `operates`, `transit`/`peer`, `member` | one file | about 2k nodes, about 1.2 MB |
| 3 | the rest of the about 8.4k services | remaining networks | `hosted_by`, `transit` | **HEALPix order-1 tiles** (48 tiles), by node direction | about 9k nodes, 48 tiles |

Each node also carries `size`, a normalised importance from 0 to 1. Clients use it to scale a node and to cull small nodes by angular size.

**LOD selection rule for clients.** Load level *k* tiles intersecting the view when the angular spacing of that level's nodes would exceed a few pixels. See `unity-integration.md`.

---

## 7. Routes: home → destination

1. **Home network.** The server maps the client's public IP (or an explicit `asn=`) to an AS with the PDDL prefix → AS table. The home node is drawn at the origin. Its access AS (`as:<asn>`) sits on the backbone shell.
2. **Destination.** The destination is a service, org or domain. Its serving network comes from `hosted_by`, which prefers a CDN/cloud edge AS.
3. **Path inference** proceeds in order:
   1. An **observed** path (future: RouteViews/RIS RIB lookup).
   2. Otherwise a **valley-free (Gao–Rexford) simulation** over the AS relationship graph. The route preference is customer > peer > provider, then the shortest path, then a deterministic tie-break.
   3. Otherwise a **fallback**: home AS → the most likely upstream tier-1 (by geography) → destination AS. This fallback is marked `confidence: "low"`.
4. **Response.** The route is a list of hops with node IDs and positions. The client draws `origin → hop₁ → … → destination service`. Each segment is a great-circle arc on a shell, or a radial curve between shells. See `snapshot-format.md` §6.

Route accuracy is reported honestly: the response includes `method` and `confidence`. Published valley-free exact-path accuracy is about 30–70%. The first and last hops are much better than the middle.

---

## 8. Personal layer (private overlays)

### 8.1 Model

Each connected account becomes an **overlay**, a small tree attached to one **anchor** node in the snapshot. The anchors are published in `anchors.json`.

| Provider | Anchor | Overlay content (v1) |
|---|---|---|
| Google | `org:google` (account), with sub-anchors `svc:gmail.com`, `svc:drive.google.com`, `svc:calendar.google.com` | Gmail labels (with counts), top-level Drive folders, calendars |
| GitHub | `svc:github.com` | User, orgs, repositories (by owner), with stars, private flag, language |
| Others (planned) | `svc:*` | Slack workspaces, Microsoft 365, Notion, AWS accounts, … |

**Multiple accounts per provider are supported.** Each account is its own sub-cluster with its own `account` node, for example two Google accounts.

### 8.2 Placement

Overlay nodes use the same coordinate system.

- The overlay sits slightly **in front of** its anchor, toward the viewer (`r = r_anchor − 25`), in the anchor's local tangent frame.
- Accounts are spread on a small ring of angular radius 1.2° around the anchor.
- Each account's assets form a phyllotaxis disc of angular radius ≤ 1° around the account.
- An `attached` edge links every account to its anchor.

The algorithm is deterministic. It is specified in `snapshot-format.md` §7, so clients can compute placement themselves.

### 8.3 Privacy modes

1. **Client-side (preferred).**
   - The Primitive environment holds the OAuth tokens and calls the provider APIs itself.
   - It maps the results with the published connector specs: anchor, endpoints and scopes, from `GET /v1/connectors`.
   - It then places the nodes with the published algorithm. No personal data reaches this service.
2. **Stateless proxy (convenience).**
   - `POST /v1/overlay/{provider}` with the user's token in `Authorization`.
   - The server calls the provider, builds and places the overlay, and returns it.
   - Tokens and results are **never persisted or logged**, and responses are `Cache-Control: no-store`.

Minimum scopes are read-only:

- GitHub: `read:user`, `read:org`, `repo` (only if private repos should appear).
- Google: `gmail.labels`, `drive.metadata.readonly`, `calendar.readonly`.

---

## 9. Serving

### 9.1 Static snapshot (CDN-friendly)

**Public URL:**

```
https://raw.githubusercontent.com/PRIMITIVE-IO/the-internet-snapshot/main/public/snapshots/latest.json
```

The repository is public and the snapshot is committed under `public/`. jsDelivr mirrors it as a CDN:

```
https://cdn.jsdelivr.net/gh/PRIMITIVE-IO/the-internet-snapshot@main/public/
```


```
public/snapshots/latest.json                      ← only mutable file (short TTL)
public/snapshots/<snapshot_id>/manifest.json      ← immutable from here down
public/snapshots/<snapshot_id>/lod0.json
public/snapshots/<snapshot_id>/lod1.json
public/snapshots/<snapshot_id>/lod2.json
public/snapshots/<snapshot_id>/lod3/<healpix_order>-<ipix>.json
public/snapshots/<snapshot_id>/anchors.json
public/snapshots/<snapshot_id>/asgraph.json        ← compact AS relationship graph for offline routing
```

- `snapshot_id` = `YYYYMMDD-<sha8>`, where `sha8` is the first 8 hex digits of the content hash.
- Any static host works: GitHub raw/Pages, S3 + CloudFront, or the bundled server.

### 9.2 API server (FastAPI, `internet_snapshot.server`)

| Method & path | Purpose |
|---|---|
| `GET /v1/snapshots/latest` | Pointer to the current snapshot |
| `GET /v1/snapshots/{id}/{file}` | Static snapshot files: immutable caching, ETag, gzip |
| `GET /v1/whereami` | Caller IP → home AS → backbone node and position |
| `GET /v1/route?to=<node-id or domain>[&asn=][&ip=]` | Route from home to the destination |
| `GET /v1/search?q=` | Find nodes by label or domain |
| `GET /v1/node/{id}` | Node details plus neighbours |
| `GET /v1/connectors` | Personal-overlay connector specs |
| `POST /v1/overlay/{provider}` | Stateless overlay proxy (§8.3) |
| `GET /healthz` | Liveness |
| `GET /viewer/` | Reference web viewer (three.js). A debugging aid that renders the snapshot exactly per the contract. |

**Deployment.** The `Dockerfile` runs this server. With `SNAPSHOT_FETCH_LOOKUPS=1`, it downloads the IP→ASN tables at startup so `whereami` works from the caller's IP. The server is stateless apart from the snapshot files, so any container host works.

---

## 10. Pipeline

```
fetch ─▶ normalise ─▶ build graph ─▶ hierarchy+weights ─▶ layout (frozen) ─▶ LOD+tiles ─▶ publish
 sources/*   records      graph.py         graph.py           layout.py         export.py     latest.json flip
```

- `python -m internet_snapshot fetch [--source ...]` downloads raw files to `data/raw/<source>/`. Each source module declares its licence class.
- `python -m internet_snapshot build` produces `public/snapshots/<id>/` and updates `latest.json`.
- `python -m internet_snapshot serve` runs the API server.

**Scheduling.** `.github/workflows/build-snapshot.yml` rebuilds the snapshot on GitHub-hosted runners, which have open egress. It runs weekly and on demand, runs the tests, and commits the new `public/snapshots/<id>/`. Old snapshots are pruned to the last 3.

**Repo size.** Committing snapshots to git is the bootstrap hosting. Once snapshots grow past roughly 50 MB, move them to object storage (S3/R2 + CDN) and keep only `latest.json` in git.

### Roadmap

| Phase | Deliverable |
|---|---|
| **v0.1 (this)** | Design, curated seed, CrUX + asn-info + origin-asn ingestion, frozen layout, LOD 0–3 export, API server, valley-free routing, GitHub and Google overlays |
| v0.2 | CAIDA as-rel and PeeringDB IXPs in CI builds; Wikidata long-tail categorisation; APNIC eyeball weights |
| v0.3 | AS relationships inferred by ourselves from RouteViews (licence-clean); observed-path lookup; OSM submarine cables as backbone arcs |
| v0.4 | Common Crawl domain-graph affinity edges; HTTP Archive CDN attribution; binary/GLB tile option |
| v0.5 | More connectors (Microsoft, Slack, Notion, AWS); delta snapshots |

---

## 11. Current build: what is real and what is approximate (v0.1)

| Aspect | v0.1 status |
|---|---|
| Service universe | **Real.** CrUX global top-10k origins (8,432 services after folding origins into registrable domains, aliases and regional variants). |
| Categories | **429 curated services** have hand-assigned categories. About 1,600 long-tail services are keyword- or suffix-classified (`.gov`, `.edu`, "news", …). The remaining about 6,400 are in *General Web*. Wikidata (v0.2) will classify the long tail. |
| Orgs | Curated: 66 multi-service orgs. A long-tail service is its own org until Wikidata ownership lands. |
| Hosting (service → AS) | **Real.** About 97% of services are attributed through DNS lookups and the public-domain prefix→AS table, or through the curated org ASNs. |
| Networks | **Real.** About 2,600 ASes: 150 curated with known roles, plus the largest by announced address space and every AS that hosts a service. Roles for the long tail are guessed from AS names. |
| AS relationships | **Heuristic** (`relationship_source: heuristic-seed`): a tier-1 mesh, regional transit, and eyeball↔content peering. Routes therefore report `confidence: "low"`. Enabling CAIDA as-rel2 (needs CAIDA's permission for commercial use) switches to inferred BGP relationships. |
| IXPs | 23 major IXPs at real metro locations. Membership is heuristic until PeeringDB is enabled. |
| Layout | Deterministic. The same inputs give the same snapshot id. |
| Overlays | GitHub and Google connectors implemented and tested against mocked APIs. Live OAuth is the client's responsibility. |
