# Research: public datasets for the service and web layer

Status as of 2026-10-04.

- **V** = fetched and inspected from the build container.
- **D** = confirmed from documentation or search only.

## 1. Top-site rankings

| Dataset | Access | Size / cadence | License | Fields |
|---|---|---|---|---|
| **CrUX top lists (V)** | `raw.githubusercontent.com/zakird/crux-top-lists/main/data/global/current.csv.gz`, plus per-country lists under `data/country/` | 8.7 MB, 1M origins, monthly | **CC BY 4.0** (Google) | `origin,rank`. The rank is a bucket: 1k, 5k, 10k, 50k, 100k, 500k or 1M. |
| Tranco (D) | `tranco-list.eu/top-1m.csv.zip` | Daily | No open license; citation requested. It is partly derived from NC sources. Use it only as an internal sort key. | `rank,domain` |
| Cloudflare Radar ranking (D) | API token required | Weekly buckets | **CC BY-NC 4.0** | domain, bucket, categories |
| Majestic Million (D) | `downloads.majestic.com/majestic_million.csv` | Daily, about 80 MB | **CC BY 3.0** | GlobalRank, Domain, RefSubNets… |
| Cisco Umbrella top 1M (V) | `s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip` | Daily, 13 MB | "Free of charge"; no formal license | `rank,fqdn` (passive DNS). Shows the API and CDN hostnames behind a brand. |
| Open PageRank / DomCop (D) | `domcop.com/files/top/top10milliondomains.csv.zip` | Irregular | Unclear | — |

## 2. Categorization

| Dataset | Access | License | Notes |
|---|---|---|---|
| **Wikidata (D)** | SPARQL `query.wikidata.org/sparql`; dumps | **CC0** | P856 website, P31 instance-of, P127/P749 owner and parent, P154 logo. Gives 60–75% coverage of the top 10k. |
| UT1 blacklists (V via GitHub mirror `olbat/ut1-blacklists`) | Daily | **CC BY-SA 4.0** | 66 functional categories: social_networks, webmail, bank, audio-video, shopping, ai, games, press… Share-alike applies, so provenance is tagged per row. |
| Cloudflare Radar categories (D) | API | CC BY-NC 4.0 | Best coverage, but non-commercial |
| IAB Content Taxonomy 3.x (V) | GitHub | CC BY 3.0 | Vocabulary only |
| Wappalyzer categories (V) | `HTTPArchive/wappalyzer` | GPL-3.0 | Technology taxonomy |
| Curlie / DMOZ | Possible dump via OpenWebSearch.eu (unverified) | CC BY 3.0 (historic) | Content topics, not service function |
| Shallalist | Dead since 2022 | — | — |

## 3. Web graph

- **Common Crawl host and domain graphs (D).**
  - Releases come every 1–3 months. The latest seen is `cc-main-2026-may-jun-jul`, with 118M domain nodes and 2.8B edges.
  - URL pattern: `data.commoncrawl.org/projects/hyperlinkgraph/{release}/{host|domain}/`.
  - `{release}-domain-ranks.txt.gz` (harmonic centrality and PageRank) is the most useful file.
  - Licensed under the Common Crawl ToU, which allows derived data.
  - Use it for service↔service affinity edges, after filtering to the snapshot's node set.

## 4. Service → infrastructure

| Dataset | Status | License | Use |
|---|---|---|---|
| HTTP Archive (D) | BigQuery `httparchive.crawl.pages`, monthly. Includes `_cdn_provider` and `technologies`. | "Use freely" | CDN, PaaS and third-party services per site |
| OpenINTEL (D) | Toplist forward DNS as Parquet: `openintel.nl/download/forward-dns/basis=toplist/source=.../` | Confirm before commercial use | domain → A/AAAA/CNAME without resolving anything ourselves |
| Rapid7 Sonar | No longer public | — | Skip |
| Censys | No free API | — | Skip |
| iptoasn / origin-asn | See doc 01 | PDDL | IP → ASN |

## 5. Corporate grouping

- **Wikidata P127 / P749 / P355 (CC0).** The cleanest source for owner and parent organisation.
- **DuckDuckGo Tracker Radar (V).**
  - Files: `build-data/generated/entity_map.json` (19,148 entities) and per-domain categories.
  - License: **CC BY-NC-SA 4.0.**
  - Only used with `--allow-noncommercial`.
- **Disconnect entities.json (V).** 1,892 entities. **CC BY-NC-SA.**
- **Public Suffix List (V).** `raw.githubusercontent.com/publicsuffix/list/main/public_suffix_list.dat`. MPL-2.0. Used to collapse an origin to its eTLD+1.

## 6. Logos

- **simple-icons (V).** CC0 project with 3,465 brands. The logos themselves remain trademarks.
- **Wikidata P154.** License is per file on Commons.

## 7. Developer-facing APIs

- **APIs.guru (V repo).** `api.apis.guru/v2/list.json`. CC0. About 2,500 APIs.
- **public-apis (V).** MIT. About 1,400 APIs in 50 categories.

## Tier-1 pipeline recommendation

1. **Service universe.** Take CrUX (CC BY) and collapse each origin to its eTLD+1 with the PSL. Top up from Majestic (CC BY).
2. **Category and organisation.**
   - Start with the curated seed catalogue (ours).
   - Add Wikidata (CC0).
   - Fill gaps from UT1 (CC BY-SA, provenance-tagged).
3. **Domain → IP → ASN.** Use OpenINTEL toplist DNS together with iptoasn.
4. **CDN and tech stack.** Use HTTP Archive.
5. **Logos and the developer API layer.** Use simple-icons and APIs.guru.

Sources that must stay out of a commercially redistributable snapshot: Cloudflare Radar, Tracker Radar and Disconnect (all NC).
