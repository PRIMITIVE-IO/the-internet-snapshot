# The Internet Snapshot: design document

**Status:** v0.2 design, 2026-10-04.

- v0.1 (global snapshot, routes, overlays) is implemented and published. §11 says what it contains and what is still approximate.
- v0.2 adds the following, with their client contract in `snapshot-format.md` §10–§15:
  - GitHub-native hosting (§9)
  - per-site endpoint graphs (§12)
  - the GitHub code universe (§13)
  - the agent interface (§14)
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
5. **Site graphs ("microcosms").** Every major site or service family (Google, GitHub, Microsoft, Amazon, …) also gets its own frozen 3D force-directed graph of its endpoints, arranged in a hierarchy:
   - surfaces → products/sections → hostnames and API groups → operations;
   - sized by importance and iconised by function.

   A user (or their agent) can "enter" a site from the global map. Services the user visits are added the same way. See §12.
6. **Code universe.** The most popular open-source codebases on GitHub, grouped into their package-ecosystem domains (.NET/NuGet, JVM/Maven, npm, PyPI, RubyGems, PHP/Packagist, Go, Cargo, …). It is published as one more graph, reachable from GitHub's node. See §13.
7. **Agents.** This is the age of AI-agent swarms. The snapshot is also a machine-readable map for the user's agents:
   - an MCP server and discovery files let agents search, locate URLs, route and enumerate endpoints;
   - an activity-overlay format lets the Primitive environment show where each agent in a swarm is working.

   See §14.

### Division of responsibility

| This service (`the-internet-snapshot`) | Primitive environment (Unity, other agent) |
|---|---|
| Researching and ingesting public datasets | Rendering, interaction, camera, UI |
| Building the graph, hierarchy and frozen layout | Choosing LOD at runtime from the view |
| Publishing immutable, versioned snapshot files | Downloading and caching snapshots |
| Route inference (home → destination) | Drawing routes |
| Personal-overlay connectors and the anchoring/placement contract | Holding the user's tokens and showing overlays |
| Site graphs, code universe, icon atlases | Entering/exiting site graphs, rendering icons |
| `locate()` + MCP server + activity-overlay format | Capturing the user's agents' activity and drawing agents and trails |
| Building and publishing on GitHub (Actions → Pages, GHCR) | Pointing clients at the Pages URL |

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

## 9. Hosting and serving (GitHub-native)

Hosting follows the common practice for a GitHub repository: **GitHub Actions builds, GitHub Pages serves, and GitHub Container Registry (GHCR) holds the server image.** GitHub cannot run a long-lived server process. The design is therefore **static-first**: every client capability works from the static files on Pages alone. The API server is an optional convenience.

```
                ┌──────────── GitHub Actions (weekly + on demand) ────────────┐
 public data ──▶│ fetch ▶ build snapshot ▶ site graphs ▶ code universe ▶ icons │
                │        ▶ ip2asn shards ▶ tests ▶ commit snapshot ▶ deploy   │
                └────────────┬──────────────────────────────┬─────────────────┘
                             ▼                              ▼
              GitHub Pages (static, CDN)            GHCR image (API server)
   https://primitive-io.github.io/the-internet-snapshot/   ghcr.io/primitive-io/the-internet-snapshot
     snapshots/ · icons/ · ip2asn/ · agent.json ·          optional: run anywhere; the GitHub-preferred
     llms.txt · viewer                                     managed host is Azure Container Apps
```

### 9.1 GitHub Pages: the gateway

**Canonical base URL:** **`https://primitive-io.github.io/the-internet-snapshot/`**

| Path | Contents |
|---|---|
| `snapshots/latest.json` | The only mutable pointer |
| `snapshots/<snapshot_id>/…` | Immutable snapshot: LOD files, aux files, `sites/` (site graphs and code universe) |
| `icons/` | Icon atlases (PNG + JSON UV map) and SVGs: brand icons (Simple Icons, CC0) and function glyphs (Lucide, ISC) |
| `ip2asn/v4/<first-octet>.json` | Sharded public-domain prefix→AS table, so clients can find their home AS without a server |
| `agent.json`, `llms.txt` | Discovery files for AI agents (§14) |
| `index.html` | The reference viewer |

- Pages serves through a CDN with about 10 min of caching. Snapshot directories are content-addressed, so stale caches can never mix versions.
- The raw-GitHub URL for the committed snapshot keeps working as a mirror.
- `snapshot_id` = `YYYYMMDD-<sha8>`, where `sha8` is the first 8 hex digits of the content hash.

### 9.2 What works statically, and how

| Capability | Static (Pages only) | API server |
|---|---|---|
| Snapshot, site graphs, code universe, icons | Yes | Yes |
| Home network | Client knows its public IP, then looks it up in `ip2asn` shards → AS | `GET /v1/whereami` (from the caller IP) |
| Routes | Client runs the valley-free simulation over `asgraph.json` (algorithm in `snapshot-format.md` §5 and §7) | `GET /v1/route` |
| Locate a URL | `domains.json` plus the site graph's `match` rules (`snapshot-format.md` §13) | `GET /v1/locate` |
| Personal overlays | Client calls providers itself and places nodes with `snapshot-format.md` §8.4 | Stateless proxy `POST /v1/overlay/{provider}` |
| Graph of a long-tail site the user visits | Client builds it from the user's own visited URLs (§12.4) | `POST /v1/site-graph` |
| Agent tools | MCP server run locally beside the agent, reading Pages (§14) | Same |

### 9.3 API server image

- `.github/workflows/publish-image.yml` builds the `Dockerfile` and pushes `ghcr.io/primitive-io/the-internet-snapshot:{latest,<sha>}`.
- If Azure credentials are configured as repository secrets, the same workflow also deploys the image to **Azure Container Apps**. Azure is Microsoft's managed container host, and GitHub Actions has first-party actions for it. Without those secrets, the deploy job is skipped.
- The server is stateless apart from the snapshot files, so any container host works.

| Method & path | Purpose |
|---|---|
| `GET /v1/snapshots/latest.json`, `GET /v1/snapshots/{id}/{file}` | Snapshot files: immutable caching, ETag, gzip |
| `GET /v1/whereami` | Caller IP → home AS → backbone node and position |
| `GET /v1/route?to=…[&asn=][&ip=]` | Route from home to the destination |
| `GET /v1/locate?url=…[&method=]` | URL → global node, site graph and site node, API operation (§14) |
| `GET /v1/search?q=`, `GET /v1/node/{id}` | Lookup |
| `GET /v1/sites`, `GET /v1/sites/{site_id}` | Site-graph index and site graphs (§12) |
| `POST /v1/site-graph` | Lay out a site graph from a list of URLs: stateless, for long-tail sites the user visits |
| `GET /v1/connectors`, `POST /v1/overlay/{provider}` | Personal overlays (§8) |
| `GET /healthz`, `GET /viewer/` | Liveness, reference viewer |

---

## 10. Pipeline

```
fetch ─▶ normalise ─▶ build graph ─▶ hierarchy+weights ─▶ layout (frozen) ─▶ LOD+tiles ─▶ publish
 sources/*   records      graph.py         graph.py           layout.py         export.py     latest.json flip
```

- `python -m internet_snapshot fetch [--source ...]` downloads raw files to `data/raw/<source>/`. Each source module declares its licence class.
- `python -m internet_snapshot build` produces `public/snapshots/<id>/` and updates `latest.json`.
- `python -m internet_snapshot serve` runs the API server.

**Scheduling.** `.github/workflows/build-snapshot.yml` runs on GitHub-hosted runners, which have open egress. It runs weekly and on demand, and performs these steps:

1. Rebuilds everything.
2. Runs the tests.
3. Commits `public/snapshots/<id>/`. Old snapshots are pruned to the last 3.
4. Deploys `public/` (snapshots, icons, ip2asn shards, agent files, viewer) to GitHub Pages.

The ip2asn shards and the icon atlases are regenerated each build and only deployed to Pages; they are not committed to git.

### Roadmap

| Phase | Deliverable |
|---|---|
| **v0.1 (this)** | Design, curated seed, CrUX + asn-info + origin-asn ingestion, frozen layout, LOD 0–3 export, API server, valley-free routing, GitHub and Google overlays |
| v0.2 | CAIDA as-rel and PeeringDB IXPs in CI builds; Wikidata long-tail categorisation; APNIC eyeball weights |
| v0.3 | AS relationships inferred by ourselves from RouteViews (licence-clean); observed-path lookup; OSM submarine cables as backbone arcs |
| v0.4 | Common Crawl domain-graph affinity edges; HTTP Archive CDN attribution; binary/GLB tile option |
| v0.5 | More connectors (Microsoft, Slack, Notion, AWS); delta snapshots |
| **v0.2-sites** | GitHub Pages hosting; site graphs; code universe; icon atlases; `locate`; MCP server; agent activity overlay format |
| later | Common Crawl URL-index paths for long-tail site graphs; dependency edges between code-universe repos (deps.dev / ecosyste.ms); live swarm-activity relay |

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
| **Site graphs (v0.2)** | **Real.** About 350 graphs and about 15k nodes:<br>- Google and GitHub are curated. GitHub has all 1,232 REST operations from GitHub's OpenAPI description. Google has 315 APIs from its Discovery directory and its CrUX hostnames.<br>- Every other multi-service org, and every major service with 6 or more hostnames, gets an automatic graph from CrUX hostnames.<br>- With APIs.guru (fetched in CI), AWS, Microsoft and others gain their API lists. |
| **Code universe (v0.2)** | **Real.** About 3,400 top repositories, from EvanLi/Github-Ranking daily data, in 22 ecosystem domains plus a maintainer hub.<br>- Purpose clusters are keyword-derived.<br>- Planned: topics from the GitHub Search API, and dependency edges. |
| **Agents (v0.2)** | `locate`, the activity overlay, an on-demand site graph from URLs, and an MCP server with 10 tools, tested over stdio. `agent.json` and `llms.txt` are on Pages. |
| **Hosting (v0.2)** | GitHub Pages deployed by Actions (needs the one-time *Settings → Pages → Source: GitHub Actions*). The GHCR image is built by Actions. The Azure Container Apps deploy is wired up and waits for credentials. |

---

## 12. Site graphs ("microcosms")

### 12.1 What and why

Every major website or service family gets **its own frozen, hierarchical 3D force-directed graph of its endpoints**. Examples are Google, GitHub, Microsoft, Amazon, Meta and Apple, plus any curated service with enough structure.

In the global snapshot a site is a single node, or an org with a few services. When the user or their agent *goes into* it, the Primitive environment swaps in or nests that site's graph.

- **Same metaphor.** The site sits at the centre with the viewer. Its structure surrounds them on concentric shells: surfaces → products → endpoints → operations.
- **Same coordinate conventions** as the global map. The site graph can be shown either as a skybox (the user has entered the site) or miniaturised at the site's node in the global view, by scaling by `radius / 1000`.

### 12.2 Hierarchy

| Depth | Kind | Examples (Google) | Examples (GitHub) |
|---|---|---|---|
| 0 | `site` | Google | GitHub |
| 1 | `surface` | Consumer apps, Workspace, Developer APIs, Cloud, Ads & Analytics, Identity, Static/CDN | Web app, REST API, Content & CDN, Packages, Pages, AI |
| 2 | `product` / `section` / `api-group` | Gmail, Drive, Maps, YouTube…; Gmail API, Drive API… | Repositories, Issues, Pull requests, Actions…; API groups `repos`, `issues`, `actions`… |
| 3 | `host` / `api` / `endpoint` | `mail.google.com`, `gmail.googleapis.com` | `api.github.com/repos/{owner}/{repo}` path groups |
| 4 | `operation` | (API methods, when cheap to list) | `GET /repos/{owner}/{repo}/issues` |

**Edges.** Hierarchy is implied by `parent`. Cross-links are explicit edges:

- `serves`: a host serves a product;
- `implements`: an API backs a product;
- `same_resource`: a web section and its API group;
- `links_to`: a link from one page to another (future: Common Crawl).

### 12.3 Data sources (still no crawling)

| Source | Gives | Licence |
|---|---|---|
| Curated `seed/sites/*.json` | Surfaces, products and sections of the major sites, with glyphs | ours (MIT) |
| CrUX top-1M origins | Every popular **hostname** under the site's domains, with popularity | CC BY 4.0 |
| GitHub REST API description (`github/rest-api-description`) | Every GitHub API operation, grouped by category | MIT |
| Google API Discovery directory (`googleapis.com/discovery/v1/apis`) | Every public Google API, with title, docs link and root URL | Google API Terms (metadata) |
| APIs.guru OpenAPI directory | APIs of about 700 providers (Stripe, Twilio, Slack, Microsoft Graph…) | CC0 |
| *Planned:* Common Crawl URL index | Page-path hierarchy of any site | CC ToU |
| *Private, client-side:* URLs the user or their agents actually visit | The parts of a long-tail site that matter to *this* user | never leaves the client |

### 12.4 Which sites get graphs

- **Precomputed** (in the snapshot): every multi-service org, plus every curated service with at least 6 endpoint nodes.
- **On demand.** For any service the user visits, the client builds a site graph from the URLs it has seen, using the same hierarchy rules. Hierarchy: host → first path segment → second path segment … (path templates like `/{id}` are collapsed).
  - The client can lay it out with `POST /v1/site-graph` (API server or local MCP server).
  - Or it can use the precomputed graph and add its URLs as overlay leaves under the deepest matching node.

### 12.5 Importance and icons

- **Size** is in 0..1. It is the max of these signals, then normalised per graph:
  - the curated weight;
  - the CrUX rank of the hostname;
  - `log(number of operations)` for API groups;
  - `log(subtree size)`.
- **`icon`**: a Simple Icons brand slug, for brands and products that have one.
- **`glyph`**: a [Lucide](https://lucide.dev) icon name that says *what is at the endpoint*, for example:
  - `mail` for an inbox, `folder` for storage, `git-pull-request` for PRs;
  - `play` for video, `credit-card` for payments, `key-round` for auth.

  It is assigned from curated data, or from keyword rules over names and paths.
- Both icon sets are published on Pages as **PNG atlases with a JSON UV map** (Unity-ready) and as SVGs.

### 12.6 Layout: radial sectors

1. **Shells.** The root is at the origin. Depth *d* sits on shell `r_d = radius · d / max_depth`, with `radius = 1000`.
2. **Sectors.** Each depth-1 subtree gets an equal-area HEALPix sector proportional to its subtree weight. The sectors are grown exactly like realms in the global map. Recursively, each depth-2 subtree gets a sub-sector inside its parent's sector.
3. **Relaxation.** The spherical spring embedder (parent–child springs, cross-link springs, repulsion, sector containment) runs per shell.
4. **Determinism.** The result is frozen and deterministic.

The outermost shell therefore reads as a skybox of the site's finest endpoints, clustered by the products they belong to.

---

## 13. Code universe (GitHub)

### 13.1 What

The code universe is a graph of **the most popular open-source codebases on GitHub, grouped into their package-ecosystem "domains"**. It ships as a site graph of kind `code` with id `site:code-universe`. Its portal is GitHub's node (`svc:github.com`).

### 13.2 Hierarchy

```
universe ─▶ ecosystem domain ─▶ language ─▶ purpose cluster ─▶ repository
            .NET (NuGet)         C#, F#        web framework     dotnet/runtime …
            JVM (Maven)          Java, Kotlin, Scala, Groovy, Clojure
            JavaScript (npm)     JavaScript, TypeScript, CoffeeScript, Vue …
            Python (PyPI)        Python
            Ruby (RubyGems) · PHP (Packagist) · Go (modules) · Rust (Cargo)
            Apple (SwiftPM/CocoaPods) · Native C/C++ (vcpkg/Conan) · Dart (pub)
            BEAM (Hex) · R (CRAN) · Haskell (Hackage) · Julia · Lua (LuaRocks)
            Perl (CPAN) · Shell & tooling · Web (HTML/CSS) · Knowledge (lists, books)
```

- **Purpose clusters** come from keyword rules over the description, and over topics when available. Examples: web framework, machine learning, devtools/CLI, database, mobile, game engine, infrastructure, editor, UI, security, education/lists.
- **Owner hubs.** An owner with three or more top repos (Microsoft, Google, Meta, Apache, …) becomes an `owner` node with `maintains` edges. This links ecosystems: TypeScript, VS Code and .NET all connect to Microsoft.

### 13.3 Data

| Source | Use | Licence |
|---|---|---|
| **EvanLi/Github-Ranking** | Daily top-100-by-stars per language, for 34 languages, about 3.4k repos. Baseline, no auth. | MIT |
| **GitHub Search API** (in CI, with `GITHUB_TOKEN`) | Enriches with topics, owner avatar, licence and homepage, and extends to the top 200 per ecosystem | GitHub API Terms (public repository metadata) |
| *Planned:* deps.dev / ecosyste.ms | Real dependency edges between repos | CC BY 4.0 / CC BY-SA 4.0 |

Size is `log(stars)`, normalised. Glyphs are by purpose. Ecosystem icons are the ecosystem's brand icon (dotnet, apachemaven, npm, python, ruby, php, go, rust, swift, …).

---

## 14. Agents: the snapshot in the age of AI-agent swarms

### 14.1 Goals

The user's agents, alone or in swarms, should be able to:

1. **Understand** the map: what is out there, grouped by function and hierarchy.
2. **Navigate** it: search, find which node and endpoint a URL belongs to, find routes, and enumerate a service's API endpoints and documentation.
3. **Be seen**: the Primitive environment shows each agent's activity as positions and trails in the same 3D space. The user can then supervise a swarm spatially.

### 14.2 Discovery

These files are published on Pages:

- `agent.json`: a machine-readable capability descriptor. It lists the data URLs, the API base (if deployed), the MCP install command, tool names and the licence and attribution.
- `llms.txt`: a plain-language guide for LLM agents.

### 14.3 MCP server

`python -m internet_snapshot mcp` is a Model Context Protocol server over stdio. It is installable straight from GitHub (`pip install git+https://github.com/PRIMITIVE-IO/the-internet-snapshot`).

It reads either local files or the Pages base URL, so **no hosted server is needed** and each agent runs its own. Tools:

| Tool | Purpose |
|---|---|
| `search(query)` | Find services, orgs and networks |
| `describe(node_id)` | Node details, children, edges, and whether a site graph exists |
| `locate(url, method?)` | URL → global node, site graph and site node path, plus the matched API operation and its documentation link |
| `route(to, asn? / ip?)` | Home → destination AS path, with 3D hop positions |
| `site_graph(site_or_node, depth?)` | Summarised hierarchy of a site's endpoints |
| `list_endpoints(service, query?)` | API operations and hosts of a service, for agents that are about to call it |
| `code_universe(ecosystem?, query?)` | Top repos per ecosystem domain |
| `whereami(ip?)` | Home AS lookup |

### 14.4 Agent activity overlay

The Primitive environment records what the user's agents do: HTTP calls, page visits and tool calls. The recording happens on the client, and the data is private by default. It turns each event into a position with `locate()`:

```
event {agent, ts, kind, method, url, status}
   ─▶ locate(url) ─▶ {global node, site node, operation}
   ─▶ agent avatar moves there; trail = home ─▶ route hops ─▶ service ─▶ site node
```

- **Swarms** are many agents. They are drawn as many avatars. Per-node activity counts become a heat overlay.
- The overlay document is specified in `snapshot-format.md` §14. It follows the same pattern as personal overlays: ids prefixed `ag:`, positions in the same coordinates, and a stateless "build from events" function.
- This service only provides the mapping and the format. Capturing and storing activity is the client's job.
