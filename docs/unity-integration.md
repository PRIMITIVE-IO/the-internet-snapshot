# Unity integration guide (Primitive environment)

This guide is for the agent or engineer who renders the snapshot inside the Primitive environment.

- The wire format is in [`snapshot-format.md`](snapshot-format.md). That document is normative.
- This guide is advisory.

All coordinates in the snapshot are already in **Unity conventions**: left-handed, +Y up, +Z forward, metres. Use `new Vector3(pos[0], pos[1], pos[2])` directly.

## 1. Loading sequence

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
- **Search:** use `search.json`, or `GET /v1/search?q=`.

## 7. Attribution

Show `manifest.attribution` in a credits panel. Some sources are CC BY and require attribution.
