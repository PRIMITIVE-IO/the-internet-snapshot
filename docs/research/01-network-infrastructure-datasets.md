# Research: public datasets for the network and infrastructure layer

Status as of 2026-10-04. This is a survey of datasets that other organisations already publish, so that the snapshot never has to crawl or measure anything itself.

How the entries were checked:

- **V**: fetched live from the build container.
- **D**: confirmed from current documentation or web search only. The research sandbox could not reach the host.

Hosts that the build sandbox's egress policy blocks include caida.org, routeviews.org, ripe.net, bgp.tools, peeringdb.com, submarinecablemap.com, labs.apnic.net and iptoasn.com. Fetchers for these sources are implemented. They run wherever the pipeline has open egress, for example GitHub Actions.

CAIDA's documentation now points to `https://data.caida.org/datasets/...`. The older paths under `publicdata.caida.org` still appear in some docs.

## 1. CAIDA

| Dataset | URL pattern | Format / cadence | Fields | License |
|---|---|---|---|---|
| AS Relationships serial-1 (D) | `data.caida.org/datasets/as-relationships/serial-1/YYYYMMDD.as-rel.txt.bz2`, plus `ppdc-ases` (customer cones) | Pipe text, ~3 MB, monthly | `<prov>\|<cust>\|-1`, `<peer>\|<peer>\|0`. The header lists the inferred Tier-1 clique and IXP ASes. | CAIDA Public AUA. **Ask CAIDA before commercial redistribution of derived data.** |
| AS Relationships serial-2 (D) | `.../serial-2/YYYYMMDD.as-rel2.txt.bz2` | Same, with a 4th field `bgp`/`mlp`. Monthly. | Adds multilateral-peering (route-server) links | Public AUA |
| AS Rank API v2.1 (D) | `api.asrank.caida.org/v2/graphql`, `/v2/restful/asns/{asn}` | JSON, monthly, no key | Rank, customer cone, degree, org, country | Public AUA |
| AS-to-Organization (D) | `data.caida.org/datasets/as-organizations/YYYYMMDD.as-org2info.txt.gz` (also `.jsonl.gz`) | Quarterly | AS → org_id → org name and country | Public AUA |
| AS Classification | Downloads were removed in 2021 | — | — | Use PeeringDB `info_type` or bgp.tools tags instead |
| RouteViews pfx2as (D) | `data.caida.org/datasets/routing/routeviews-prefix2as/YYYY/MM/routeviews-rv2-YYYYMMDD-HHMM.pfx2as.gz` | Daily | prefix, length, origin AS | AUA, or derive it yourself from RouteViews (CC BY) |
| CAIDA PeeringDB archive (D) | `data.caida.org/datasets/peeringdb/YYYY/MM/peeringdb_2_dump_YYYY_MM_DD.json` | Daily, 40–80 MB | Full PeeringDB objects | AUA plus the PeeringDB AUP |
| ITDK, Ark traceroutes (D) | Request form | Multi-GB | Router-level topology and geo | Restricted, research use only |

## 2. BGP routing tables

| Dataset | URL pattern | Notes | License |
|---|---|---|---|
| RouteViews (D) | `archive.routeviews.org/{collector}/bgpdata/YYYY.MM/RIBS/rib.YYYYMMDD.HHMM.bz2` | MRT. RIBs every 2 h. ~40 collectors. | **CC BY 4.0.** The cleanest source for deriving AS paths and relationships ourselves. |
| RIPE RIS (D) | `data.ris.ripe.net/rrcNN/latest-bview.gz`; RIS Live at `wss://ris-live.ripe.net/v1/ws/` | MRT, bview 3×/day | Free with attribution. Commercial use is under RIPE NCC's default revocable permission. |
| RIPEstat (D) | `stat.ripe.net/data/{as-overview,asn-neighbours,announced-prefixes,looking-glass,...}/data.json?resource=AS3333` | Lookups, limited to 8 concurrent requests | RIPEstat T&C. Use it for per-user lookups, not bulk download. |
| bgp.tools (D) | `bgp.tools/table.jsonl`, `bgp.tools/asns.csv`, `bgp.tools/tags/{cdn,eyeball,...}.csv` | Rebuilt every 30 min. Needs a User-Agent with contact info. | ToS: ask before redistributing |
| BGPKIT Broker (D) | `api.bgpkit.com/v3/broker/search?...` | Index of RouteViews/RIS MRT files. `pybgpkit` parser. | Free (index). The data keeps its source license. |
| Hurricane Electric | HTML only | — | **Do not scrape** |

## 3. IXPs and facilities

- **PeeringDB API (D).** `www.peeringdb.com/api/{net,org,ix,ixlan,ixpfx,netixlan,fac,netfac,ixfac}`.
  - Rate limits: 20 requests/min anonymous, 40 requests/min with an API key.
  - It is the only free source of facility lat/lon.
  - The AUP restricts bulk redistribution. Use it to derive aggregates internally and request approval.
- **PCH IXP directory (D).** Has IXP history and status. Terms are not stated.
- **Euro-IX IXPDB / IX-F JSON exports (D).** These are the authoritative member lists. Their URLs are listed in PeeringDB `ixlan.ixf_ixp_member_list_url`.

## 4. IP → ASN and IP → geo

| DB | URL | License |
|---|---|---|
| iptoasn.com (D) | `iptoasn.com/data/ip2asn-v4.tsv.gz`, hourly | **PDDL** |
| sapics/ip-location-db `origin-asn` (**V**) | `github.com/sapics/ip-location-db/releases/download/latest/origin-asn-ipv4.csv` (27 MB, daily) | **PDDL**. Reachable from the build container. |
| ipverse/asn-info (**V**) | `raw.githubusercontent.com/ipverse/asn-info/master/as.csv` (125k ASNs: asn, handle, description, cc) | **CC0** |
| DB-IP Lite (D, mirrored by sapics **V**) | `download.db-ip.com/free/dbip-{country,city,asn}-lite-YYYY-MM.csv.gz` | CC BY 4.0 |
| IPinfo Lite (D) | `ipinfo.io/data/ipinfo_lite.csv.gz?token=` | CC BY-SA 4.0 (share-alike) |
| MaxMind GeoLite2 | Account required | Redistribution needs a paid licence. **Avoid.** |

## 5. Cloud and CDN published IP ranges

All of these are free, factual lists.

- AWS (**V**): `ip-ranges.amazonaws.com/ip-ranges.json`
- GCP: `www.gstatic.com/ipranges/cloud.json` and `goog.json`
- Azure: weekly `ServiceTags_Public_YYYYMMDD.json`, linked from download id 56519
- Cloudflare: `www.cloudflare.com/ips-v4` and `/ips-v6`
- Fastly: `api.fastly.com/public-ip-list`
- Oracle: `docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json`
- Akamai: no public list. Use AS20940 and AS16625 instead.

## 6. Physical layer

- **TeleGeography Submarine Cable Map (D).**
  - Endpoints: `submarinecablemap.com/api/v3/cable/cable-geo.json` and `landing-point/landing-point-geo.json`.
  - **The underlying data is a paid product.** Use it for prototyping only, or switch to OpenStreetMap `submarine=yes` cables (ODbL).
- **Terrestrial fiber.** There is no good global open dataset. Draw abstract great-circle edges between facility metros instead.
- **Data centers.** Use PeeringDB `fac`, with OSM `telecom=data_center` as a supplement.

## 7. Measurement platforms

- **Cloudflare Radar API (D).**
  - Free with a token, but the data is **CC BY-NC 4.0**, so it is non-commercial.
  - Useful endpoints: `entities/asns/{asn}/rel`, `bgp/routes/upstreams/{asn}`, `http/top/ases`, `ranking/*`.
- **RIPE Atlas (D).**
  - Public traceroute results at `atlas.ripe.net/api/v2/measurements/{id}/results/`.
  - Probe metadata at `/probes/?asn_v4=`.
  - Commercial use is under RIPE NCC's default permission.
- **M-Lab (V, bucket listing).** About 14M traceroutes per day from servers toward end users, in `gs://archive-measurement-lab/ndt/scamper1/` and BigQuery.

## 8. Eyeball weighting

- **APNIC per-AS user population (D).**
  - JSON at `stats.labs.apnic.net/cgi-bin/aspopjson?c=XX`, updated daily.
  - It identifies the largest access network per country 94% of the time.
  - No license is published, so **ask APNIC first**.

## 9. RIR delegated stats

These are free and have no restrictions in practice.

- Combined NRO file: `ftp.ripe.net/pub/stats/ripencc/nro-stats/latest/nro-delegated-stats`
- Format: `registry|cc|type|start|value|date|status|opaque-id`. The opaque-id groups resources by holder.

## Recommended tier-1 set

| Layer | Source |
|---|---|
| AS nodes, country, org | RIR delegated stats, ipverse asn-info (CC0), CAIDA as2org (opt-in) |
| Prefix → AS, address-space weight | iptoasn / sapics origin-asn (PDDL) |
| AS edges and relationship types | CAIDA as-rel2 (opt-in, AUA). Clean alternative: run ASRank/ProbLink-style inference ourselves over RouteViews RIBs (CC BY) through BGPKIT. |
| Hierarchy / "altitude" | Customer-cone size computed from as-rel |
| Eyeball weight | APNIC aspop (opt-in) |
| Cloud/CDN nodes | Provider range files |
| IXP/facility geo anchors | PeeringDB (opt-in, aggregate output only) |
| Submarine | OSM (ODbL) for production. TeleGeography for prototyping only. |

## Approximating the route from home to a destination (valley-free / Gao-Rexford)

1. **Map both ends to ASes.** The user IP maps to a source AS. The destination service maps to its serving AS: a cloud or CDN range, else the origin AS.
2. **Prefer an observed path.** If RouteViews/RIS (or RIPEstat `looking-glass`) has a path from the source AS or one of its upstreams, use it.
3. **Otherwise simulate.** Route propagation is BGPsim-style:
   1. Customer routes propagate upward.
   2. One peer hop.
   3. Provider routes propagate downward.
   4. Each AS prefers customer, then peer, then provider routes, then the shorter path, then a deterministic tie-break.

   Siblings (same org) count as free transit. Published exact-path accuracy is about 30–70%, and higher for the first and last hops. Show alternates.
4. **Geo-place hops.** Use PeeringDB `netixlan` for IX crossings and submarine cables between countries.
5. **Optional ground truth.** Use RIPE Atlas probes in the source AS, and M-Lab paths to clients in the user's AS.

## License summary

| Class | Datasets |
|---|---|
| Clean | RIR stats, RouteViews (CC BY), iptoasn/origin-asn (PDDL), ipverse (CC0), DB-IP Lite (CC BY), cloud range files |
| Share-alike | IPinfo Lite, OSM |
| Default-grant | RIPE RIS, RIPEstat, RIPE Atlas |
| Ask first | CAIDA, APNIC aspop, PeeringDB, bgp.tools, PCH |
| Non-commercial or paid | Cloudflare Radar, TeleGeography data, MaxMind redistribution, ITDK |
