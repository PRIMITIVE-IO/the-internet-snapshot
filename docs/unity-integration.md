# Unity integration guide (Primitive environment)

This guide is for the agent or engineer who renders the snapshot inside the Primitive environment.

- The wire format is in [`snapshot-format.md`](snapshot-format.md). That document is normative.
- This guide is advisory.

All coordinates in the snapshot are already in **Unity conventions**: left-handed, +Y up, +Z forward, metres. Use `new Vector3(pos[0], pos[1], pos[2])` directly.

## 1. Loading sequence

**Public base URL:** GitHub Pages, with no server needed:

```
https://documentation.primitive.io/the-internet-snapshot
```

Mirror: `https://raw.githubusercontent.com/PRIMITIVE-IO/the-internet-snapshot/main/public`. It has the snapshots only, without icons or ip2asn.

Everything works statically (`snapshot-format.md` §10):
- client-side routing over `asgraph.json`;
- home AS from the `ip2asn` shards;
- locate through `domains.json` and the site graphs;
- overlays built client-side.

The API server (`/v1`) is optional.


The reference web viewer (`viewer/index.html`, served at `/viewer/`) is a working example of this guide. The only difference is that it maps Unity's left-handed coordinates to three.js with `(x, y, -z)`. Unity needs no conversion.

1. **Read the pointer.** `GET {base}/snapshots/latest.json` gives you the `snapshot_id`. Compare it with the cached id. If it is the same, load everything from the local cache.
2. **Read the manifest.** `GET {base}/snapshots/{id}/manifest.json` gives you the legend (realms, categories and network roles with colours), the shell radii, the LOD table and the attribution.
3. **Load LOD 0 and LOD 1 immediately.** Both are small. Together they give the whole sky:
   - 10 realm sectors and their categories;
   - continent regions;
   - the major networks.
4. **Load LOD 2 in the background.** It holds orgs and the main networks.
5. **Load LOD 3 tiles on demand.** Load a tile when the camera looks toward it and the zoom/FOV makes its nodes resolvable (see §3).
6. **Ask the server where home is.** Call `GET /v1/whereami` and draw the home network at the origin.
7. **Optionally load routes and overlays.** Use `GET /v1/route?to=…` for routes and §5 for personal overlays.

Cache every file under `{id}/` permanently; those files are immutable.

JSON parsing:

- Prefer **Newtonsoft.Json** (`com.unity.nuget.newtonsoft-json`).
- Node objects always have the same keys, so `JsonUtility` also works with `[Serializable]` classes. In those classes `pos` is a `float[]`, and nullable numbers should be declared as strings or handled by Newtonsoft.

## 2. Rendering

| Element | Suggested technique |
|---|---|
| Nodes (up to tens of thousands) | `Graphics.RenderMeshInstanced` / `DrawMeshInstancedIndirect` with a billboard or low-poly sphere. One batch per shell. Scale by `size`. Tint by `color`. |
| Labels | Show labels only for LOD 0–1 by default, plus nodes near the gaze ray and the hovered node. Use TextMeshPro with distance-independent screen size. |
| Edges | Build one `Mesh` with `MeshTopology.Lines` per LOD level or tile. Sample each edge as an arc using `snapshot-format.md` §6. Alpha comes from `weight`. Colour comes from the edge kind or the source node colour. |
| Sector boundaries | Optional. Draw a faint halo around the realm and category centroids. A later snapshot version may add explicit polygon outlines. |
| Shells | Optional faint wireframe spheres at `manifest.shells` radii. They help depth perception. |
| Home | A distinct glyph at the origin. In VR, place it at the user's feet. |

**Skybox mode.** The service shell is a sphere around the origin. To use it as a true skybox:

- either keep these objects centred on the camera and don't translate them;
- or bake the service shell to a cubemap with a camera at `(0,0,0)` and use it as the skybox material. Keep the inner shells as live geometry for parallax and interaction.

**Free-roam mode.** Leave the graph fixed in world space at the origin. Scale it with a parent transform if the default scale of 1000 m does not suit the scene.

Suggested colour use:

- Service-side nodes use the category colour.
- Networks use the `network_roles` colour.
- Edge colours by kind:
  - `transit`: amber;
  - `peer`: cyan;
  - `hosted_by`: the service's colour at low alpha;
  - `owns`: white at low alpha;
  - `aggregate`: grey.

## 3. Level-of-detail policy

Each level is worth loading once its nodes become resolvable. Approximate typical angular spacing between neighbouring nodes:

| LOD | Typical angular spacing | Load when |
|---|---|---|
| 0 | about 40° | always |
| 1 | about 15° | always |
| 2 | about 3° | at startup, in the background |
| 3 | about 1° | a tile intersects the view frustum *and* the projected 1° exceeds about 12 px |

Projected size of 1° in pixels:

```
pixelsPerDegree = Screen.height / camera.fieldOfView
```

**Tile visibility.** LOD-3 tiles are HEALPix order-1 cells, 48 of them, each about 29° across. Take the tile's representative direction to be the mean of its nodes' positions. Equivalently, compute it once from the first node you load and cache it.

Tiles have no fixed bounding box listed in the manifest, so a cheap test is enough. Treat a tile as visible when the angle between the camera forward vector and the tile centre is less than `fov/2 + 20°`.

**Unloading.** You may unload LOD-3 tiles that have been out of view for a while. LOD 0–2 should stay resident.

## 4. Routes

```
GET /v1/route?to=gmail.com
```

Draw the polyline `hops[0].pos → hops[1].pos → …`:

- Use a straight segment out of the origin.
- After that, use arcs as in §6 of the format document.
- Animate a pulse travelling along the route.
- Colour each segment by `rel`:
  - `up`: amber;
  - `peer`: cyan;
  - `down`: green;
  - `served`: the service colour.

Show `method` and `confidence` in the UI. A `low` confidence means the middle of the path is a guess.

## 5. Personal overlays

Recommended flow:

1. Primitive holds the user's OAuth tokens. This service does not provide an OAuth app or store tokens.
2. Either:
   - **(a)** call `POST /v1/overlay/{provider}` with `Authorization: Bearer <token>`. This is the stateless proxy, and it returns positioned nodes and edges; or
   - **(b)** call the provider API directly and place the nodes yourself with `snapshot-format.md` §8.4. This keeps the data entirely on the client.
3. Render overlay nodes like normal nodes, but with a distinct "personal" material, for example a white glow. Draw `attached` edges from each account node to its anchor.
4. Several accounts of the same provider: make one request per token, with `account_index`/`account_count`. The accounts then spread on a ring around the anchor.

Overlay node ids start with `ov:`. They never collide with snapshot ids.

## 6. Interaction suggestions

- **Gaze or point at a node:** show the label and call `GET /v1/node/{id}` for details, neighbours and children.
- **Select a realm or category:** fade everything else and load that sector's LOD-3 tiles first.
- **Select a service:** draw its `hosted_by` edges to the edge shell and the route from home (`/v1/route`).
- **Search:** use `search.json`, or `GET /v1/search?q=`. To map a hostname the user visits, for example a page in a Primitive browser panel, to its node, use `domains.json`. It covers aliases such as `mail.google.com` → `svc:gmail.com`.

## 7. Site graphs ("entering" a site)

1. Global nodes with a non-null `portal` can be entered. Examples: Google, GitHub, Microsoft, Amazon, Wikipedia, about 350 sites in all.
2. To enter a site, load `snapshots/<id>/` + the `file` from `sites/index.json`.
3. Its coordinates use the same conventions, with the **site at the origin**:
   - **Immersive:** hide the global map, put the camera at the origin, and show the site graph as the new skybox. Depth *d* is on shell `shells[d]`.
   - **Miniature:** parent the site graph under the global node's position and scale it by `≈ 30 / radius`. It then looks like a small galaxy attached to the node.
4. Draw parent→child links as arcs (`snapshot-format.md` §6) at low alpha. Explicit `edges` (`same_resource`, `maintains`) are cross-links. Draw them dimmer when there are many.
5. Labels: depth 1 always, depth 2 when there are fewer than about 80 depth-2 nodes, and deeper on gaze or hover.
6. Some site nodes have a `portal` of their own, such as GitHub → *Open-source universe* → `site:code-universe`. Let the user follow it.

## 8. Icons

- Load `icons/index.json` and `icons/atlas-64.png` from the Pages base (`snapshot-format.md` §12).
- Every node can have:
  - `icon`: a brand, which is preferred when present;
  - `glyph`: a function, for example `mail`, `git-pull-request` or `credit-card`.
- Render nodes as instanced quads that sample the atlas cell for their icon or glyph, tinted by the node `color`.
- The PNG is white on transparent, and its cell UVs are given in the index.
- The reference viewer does this with a point-sprite shader. See `viewer/index.html`, `iconMat`.

## 9. Agents and swarms

The user's agents produce events: HTTP calls, page visits and tool calls.

- Turn each event into a position with `locate(url)`. Locally, use `domains.json` plus the site graph's host/path rules. Otherwise use `/v1/locate` or the MCP server.
- Or batch them through `POST /v1/activity`. The result follows `snapshot-format.md` §14.
- Suggested rendering:
  - one avatar per agent, in its deterministic colour, at `at` (global) or `at_site` (inside an entered site);
  - a fading trail through recent `trail` steps;
  - per-node `heat` as a glow or bar on the node;
  - for a new service, the network route from home (`/v1/route` or client-side routing) drawn in the agent's colour.

Agents themselves can use the MCP server (`python -m internet_snapshot mcp`, configured by `agent.json` on Pages). They can then reason about the same map that the user sees.

## 10. Attribution

Show `manifest.attribution` in a credits panel. Some sources are CC BY and require attribution.
