# Providers: verified contracts and sources

Checked **12 September 2026** against the official documentation linked below.
The Postman collection was retrieved directly to inspect request examples and
query-parameter descriptions. Live Austrian checks passed on **13 September 2026**
for prices, load, generation and DE_LU→AT flows over 1 September 2026 (UTC).

## Query contract

Production endpoint: `https://web-api.tp.entsoe.eu/api`. Use HTTPS GET and
`SECURITY_TOKEN` header authentication (the official collection includes an
explicit GET header-auth example). Query parameter names are case-sensitive.
Every request includes `periodStart` and `periodEnd` in UTC `yyyyMMddHHmm` format.

| Dataset | documentType | Other parameters |
| --- | --- | --- |
| Day-ahead prices | A44 | in_Domain=zone, out_Domain=zone, contract_MarketAgreement.type=A01 |
| Actual total load | A65 | processType=A16, outBiddingZone_Domain=zone |
| Actual generation per type | A75 | processType=A16, in_Domain=zone |
| Physical flows | A11 | out_Domain=origin, in_Domain=destination |

Prices now cover day-ahead and intraday products, so GridScope explicitly selects
A01. The current collection documents 100 TimeSeries per price response and an
`offset` parameter. GridScope follows pages and splits long ranges into 31-day
queries. For AT and DE_LU, the connector also requests
`classificationSequence_AttributeInstanceComponent.position=1`, the SDAC market
identified in ENTSO-E’s official explanatory notes. Sequence 2 is the separate EXAA
auction. The selected sequence is retained in `source_auction_sequence`.

The live Austrian response contained repeated sequence-1 publications. Only price
series identical in their XML metadata and values (ignoring the series mRID and
formatting whitespace) are collapsed within each response. The original mRID
remains in `source_series`, with repeats in `duplicate_source_series` and a point
note. Different prices, metadata, or period definitions still trigger overlap
errors. Nothing is averaged or selected by response order.

Generation series with `inBiddingZone_Domain` represent output; those with only
`outBiddingZone_Domain` represent consumption and are excluded. Flow API responses
are directional, unlike netted web views. Querying both directions requires two
requests. Availability is dataset-specific; an EIC entry is not proof of coverage.

## Verified area identifiers

| Public code | EIC | Area |
| --- | --- | --- |
| AT | 10YAT-APG------L | Austria |
| DE_LU | 10Y1001A1001A82H | Germany–Luxembourg |
| CZ | 10YCZ-CEPS-----N | Czechia |
| SK | 10YSK-SEPS-----K | Slovakia |
| HU | 10YHU-MAVIR----U | Hungary |
| SI | 10YSI-ELES-----O | Slovenia |
| IT_NORTH | 10Y1001A1001A73I | Northern Italy |
| CH | 10YCH-SWISSGRIDZ | Switzerland |

These initial mappings represent bidding zones. The v0.2 additions below also
include country areas explicitly labeled as such. Historic configurations and
individual control areas may differ. GridScope does not auto-substitute them.

The official A75 query description defines B01–B20 as biomass, lignite, coal gas,
gas, coal, oil, oil shale, peat, geothermal, pumped storage, run-of-river hydro,
reservoir hydro, marine, nuclear, other renewable, solar, waste, offshore wind,
onshore wind and other, respectively. B25 is energy storage. These map to readable
domain categories; unrecognized codes are preserved as unknown.

## Time, quality and rate behavior

Source time is UTC. Some responses cover complete local market days beyond the
query; points are clipped to the requested half-open interval by interval start.
A01 fixed blocks and A03 variable blocks are decoded separately. A03 carry-forward
is provider-defined block decoding, never a general missing-data fill.

The current rate guide specifies 400 requests/minute **per token**, including
requests across multiple machines. GridScope throttles each instance to at most
five starts/second and retries transient failures with bounded backoff. Callers
sharing a token across instances must coordinate usage. Long cooldowns return a
rate-limit error without retrying early. No raw provider payload or token is
included in GridScope exceptions.

## Reuse and attribution

The currently linked terms are dated 29 March 2023, and the free-reuse list is dated
18 October 2023. That list grants CC-BY-4.0 for eligible listed datasets with
attribution and indication of changes, subject to geographical/interconnector
exceptions. Physical flows (Article 12.1.G) appear as item 18. **Actual load,
actual generation and day-ahead energy prices are not listed there**; the registry
marks their primary-owner permission/reuse conditions as requiring verification.
Do not infer their license from the general public availability of the platform.

Credit `Source: ENTSO-E Transparency Platform`, retain the source URL and identify
normalization and derived calculations. Review the current terms and relevant
primary-owner conditions before redistribution or commercial reuse. This is a
source registry and implementation note, not legal advice. No project software
license is selected by this initial build; choose one deliberately before releases.

## Official references

- [Current help page and dataset-specific links](https://transparencyplatform.zendesk.com/hc/en-us/articles/17260622859412-Transparency-Platform-Help-page)
- [Official Postman REST API collection](https://documenter.getpostman.com/view/7009892/2s93JtP3F6)
- [Request endpoint](https://transparencyplatform.zendesk.com/hc/en-us/articles/15696677194644-Request-Endpoint)
- [Area list / EIC registry](https://transparencyplatform.zendesk.com/hc/en-us/articles/15885757676308-Area-List-with-Energy-Identification-Code-EIC)
- [UTC time interval parameters](https://transparencyplatform.zendesk.com/hc/en-us/articles/12783280128404-Request-Parameters-Time-Interval)
- [Response time zones](https://transparencyplatform.zendesk.com/hc/en-us/articles/12786431986964-Response-Time-Zone)
- [A01 and A03 curve semantics](https://transparencyplatform.zendesk.com/hc/en-us/articles/30262342482961-CurveType-A01-vs-CurveType-A03)
- [Rate limits](https://transparencyplatform.zendesk.com/hc/en-us/articles/12783148966036-API-Rate-Limit-Part-1)
- [Query size limits](https://transparencyplatform.zendesk.com/hc/en-us/articles/15854536354964-API-Query-Size-Limit)
- [Energy price definitions](https://transparencyplatform.zendesk.com/hc/en-us/articles/16647234190100-Energy-Prices-12-1-D)
- [Terms and free-reuse list](https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions)
- [18 October 2023 free-reuse list PDF](https://transparencyplatform.zendesk.com/hc/en-us/article_attachments/40921869379729)
- [Official XML examples](https://gitlab.entsoe.eu/transparency/xml-examples)

- [Official explanatory notes: SDAC and EXAA auction sequences](https://eepublicdownloads.blob.core.windows.net/tp-reporting-exports/Explanatory%20Notes.xlsx)

## v0.2 coverage

Checked **27 October 2026**. The additional EIC mappings were checked against the
[official area list](https://transparencyplatform.zendesk.com/hc/en-us/articles/15885757676308-Area-List-with-Energy-Identification-Code-EIC).

| Public code | EIC | Scope |
| --- | --- | --- |
| DE | 10Y1001A1001A83F | German country area; load/generation |
| LU | 10YLU-CEGEDEL-NQ | Luxembourg country/control area; no independent price zone |
| FR | 10YFR-RTE------C | France |
| BE | 10YBE----------2 | Belgium |
| NL | 10YNL----------L | Netherlands |
| PL | 10YPL-AREA-----S | Poland |
| DK1 | 10YDK-1--------W | Western Denmark |
| DK2 | 10YDK-2--------M | Eastern Denmark |
| NO2 | 10YNO-2--------T | Southern Norway |
| SE4 | 10Y1001A1001A47J | Southern Sweden |

Live checks used the UTC day 1 September 2026, plus German local days 29 March
and 25 October 2026 for DST load/generation checks. This validates particular
publications, not perpetual or comprehensive availability.

| Dataset / scope | ENTSO-E | SMARD |
| --- | --- | --- |
| Prices: DE_LU, AT, FR, BE, NL, PL, DK1, NO2, SE4, CZ, CH | Verified | Verified |
| Prices: DK2 | Ambiguous overlapping publications rejected | Verified |
| DE load and generation | Verified, including both DST transitions | Verified, including both DST transitions |
| Physical flows: DE_LU ↔ AT, DE_LU ↔ FR | Verified in both directions | Verified in both directions |

DST load returned 92/100 quarter-hour observations (23/25 hours); explicit hourly
resampling preserves the integrated energy. Swiss ENTSO-E prices were hourly;
SMARD supplied its quarter-hour chart cadence. German SMARD generation included
11 published categories; the unavailable nuclear series is reported in warnings,
not manufactured as zero. Other mapped zones/dates/datasets remain subject to
provider publication availability. LU is mapped but not included in this live matrix.

The DK2 ENTSO-E response included unclassified and sequence-2 publications with
slightly different prices. The official notes inspected did not establish a safe
selection rule for this case. These are not exact duplicates; GridScope rejects
the overlap. Choose `provider=smard` explicitly for verified DK2 coverage. No
rounding, averaging or provider substitution is used to conceal the ambiguity.

Run `RUN_LIVE_V02_TESTS=1 uv run pytest tests/integration/test_live_v02.py -m live`
to repeat the supported coverage matrix and DST energy-conservation checks.

## SMARD connector

SMARD is the Bundesnetzagentur market-data portal. The connector reads the public
JSON interface used by the official website; no API token is needed. This is an
observed public website interface, not a promised versioned developer API.
Mappings were verified against the official
[market-data configuration](https://www.smard.de/app/chart_configuration/market_data_configuration.json)
and [region definitions](https://www.smard.de/app/chart_configuration/regions.json).

```text
https://www.smard.de/app/chart_data/{filter}/{region}/index_quarterhour.json
https://www.smard.de/app/chart_data/{filter}/{region}/{filter}_{region}_quarterhour_{anchor}.json
```

The index supplies weekly epoch-millisecond anchors. Select intersecting chunks
using those anchors: a local week crossing DST is not necessarily 168 UTC hours.
Values are `[epoch_milliseconds, number_or_null]` pairs. Point timestamps normalize
to UTC; half-open query bounds trim by interval start. Invalid timestamps, nonfinite
values, invalid signs and conflicting duplicates fail with safe structured errors.
Absent timestamps remain gaps, explicit nulls remain missing, and coverage warnings
are returned. Errors do not include source bodies or credentials.

### Filters and normalization

| Dataset | Filters | Reporting region / meaning |
| --- | --- | --- |
| Load | 410 | DE, DE-LU, AT, LU; realized grid load |
| Generation | 4066 biomass, 4067 onshore, 4068 solar, 1223 lignite, 4069 coal, 4071 gas, 4070 pumped storage, 1226 hydro, 1228 other renewable, 1227 other, 1225 offshore, 1224 nuclear | DE, DE-LU, AT, LU; only technologies configured for that region |
| Prices | 4169 DE_LU, 4170 AT, 252 DK1, 253 DK2, 254 FR, 255 IT_NORTH, 256 NL, 257 PL, 258 SE4, 259 CH, 260 SI, 261 CZ, 262 HU, 4996 BE, 4997 NO2 | Requested market identified by filter; charts requested in region DE |

The generation/load/flow chart unit is **MWh per 15-minute interval**, converted
to average MW by dividing by 0.25 hours. Prices are already EUR/MWh and are not
scaled. Chart resolution is PT15M even when SMARD repeats an older hourly auction
value. This source cadence is disclosed in point notes and metadata; GridScope
does not perform its own upsampling or claim a finer native market product.

Hydro filter 1226 is aggregated hydro, not an invented split into river/reservoir
output. The separate pumped-storage filter is excluded from renewable-share
numerators. Nuclear/lignite/offshore filters are not requested for Austria or
Luxembourg when absent from the official regional configuration.

Physical flows use the **Physikalischer Stromfluss** filters, not commercial trade
or net-export filters. Supported bidirectional borders are:

- DE_LU with AT, BE, CH, CZ, DK1, DK2, FR, NL, NO2, PL and SE4.
- DE with AT, BE, CH, CZ, FR, LU, NL and PL.
- AT with CH, CZ, DE, DE_LU, HU, IT_NORTH and SI.
- LU with BE and DE.

The exact filter/reporting-region pairs live in
[`providers/smard/mappings.py`](../src/gridscope/providers/smard/mappings.py).
For example, DE_LU→AT uses 4829/DE-LU and AT→DE_LU uses 4848/DE-LU. Import charts
publish negative values; their sign is explicitly reversed into positive named
direction MW, with a note retained. Unexpected signs fail validation instead of
being indiscriminately made absolute. Aggregate country DK/NO/SE flow filters are
not relabeled as DK1/NO2/SE4.

`source_document` retains the chart URL, `source_series` the filter/region and
`source_revision` the chart's `meta_data.created` milliseconds. This creation
timestamp is a source publication marker, not an ENTSO-E document revision number.
Retrieval timestamps survive in-memory cache hits. The provider has a bounded
128-entry response cache, per-instance 200 ms request spacing, configurable
timeouts and bounded retries. This pacing is GridScope's conservative policy, not
a claimed official SMARD quota. Missing capabilities never fall back to ENTSO-E.

### SMARD attribution

The official [data-use terms](https://www.smard.de/home/datennutzung) publish SMARD
market data under **CC BY 4.0**. Credit **Bundesnetzagentur | SMARD.de**, preserve
the source and license, and identify GridScope's unit/sign conversions, resampling
and derived calculations. This source-specific grant does not change ENTSO-E's
separate reuse conditions. The `/v1/sources` registry records both providers.
