# Research: 3D internet layouts, spherical/skybox mapping, and LOD formats

## Prior art

| Project | Layout | Takeaway |
|---|---|---|
| CAIDA AS Core | Polar: radius decreases with AS outdegree; angle is the prefix-weighted longitude | Fix the axes by meaning: geography and "coreness" |
| CAIDA Walrus / Munzner H3 | 3D hyperbolic layout of a spanning tree, projected into a ball | The fisheye centre maps naturally to angular LOD |
| Opte Project | LGL force layout of RouteViews ASes, coloured by RIR | A pure force layout of about 70k ASes reads well |
| internet-map.net (Enikeev) | N-body charged springs; size is traffic, colour is country | Closest analogue for services |
| Halcyon "Map of the Internet" | Hand-drawn; sites are "countries" clustered by category; ISPs at the centre | Semantic sectors with a core-to-periphery gradient |
| Cloudflare Radar / Kaspersky globes | Real geography with arcs | Geographic globe mode |

**Pattern.** The most readable maps fix one or two axes by meaning, such as geography or coreness. Force or packing then handles locality within those constraints.

## Layout libraries (offline, around 100k nodes)

- **igraph `layout_drl(dim=3)`.** Best 3D option on pip.
- **ngraph.forcelayout and ngraph.native.** npm, 3D, offline, with binary output.
- **d3-force-3d.** Custom forces, for example a "stay on shell r" force.
- **graph-tool `sfdp`.** 2D only, but it has nested SBM hierarchies.
- **fa2_modified.** 2D only.
- **Spherical spring embedder** (Kobourov & Wampler 2005, "Non-Euclidean Spring Embedders"). Compute forces in the tangent plane, then renormalise each node to its shell. Easy to write in numpy. **This is the approach chosen here.**
- **Sphere tessellation.** HEALPix (`healpy`) gives equal-area nested cells. `scipy.spatial.SphericalVoronoi` gives organic sector shapes.

## LOD and tiling formats

- **3D Tiles 1.1.** Robust, but geospatial (ECEF) and heavy without Cesium.
- **HEALPix tiling, as in astronomy HiPS/MOC.**
  - 12 base cells, with child index = `parent*4+k`.
  - All cells have equal area.
  - HiPS is literally a progressive skybox tile pyramid served as static files.
  - **This is the best fit for a sphere seen from inside.**
- **glTF/GLB.** `EXT_mesh_gpu_instancing` plus meshopt gives engine-ready instancing. An optional later export.
- **Arrow or raw typed arrays.** Zero-copy access for engines.

**Recommendation.** An immutable, content-addressed snapshot directory:

- `manifest.json`
- `lod/{level}/...` (or HEALPix-tiled per level)
- `latest.json` as the only mutable pointer

Use ADD refinement, so child tiles add detail and parents never need to be hidden.

## Mapping to a skybox

1. **Category sectors.** Assign each category equal-area HEALPix cells in proportion to its weight. Grow regions by BFS over cell neighbours, and place related categories next to each other.
2. **Elevation semantics.** Either use a backbone band, or geo-mode: azimuth = longitude, elevation = latitude.
3. **Radius bands for parallax.** For example, infrastructure shells inside and services at the outer shell.
4. **Within-sector layout.** A spherical force layout with a containment force for the sector. Cross-sector edges become great-circle arcs (slerp).
5. **Angular LOD.** A tile at order k spans about 58.6°/2^k. Load tiles that intersect the view frustum (`query_disc`).

Sources: caida.org/projects/as-core, opte.org, Kobourov & Wampler (TVCG 2005), HiPS (arXiv:1505.02291), OGC 3D Tiles 1.1, and the igraph, ngraph and d3-force-3d documentation.
