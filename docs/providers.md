# ENTSO-E connector: verified contract and sources

Checked **12 September 2026** against the official documentation linked below.
The Postman collection was retrieved directly to inspect request examples and
query-parameter descriptions. No live API credential was available for this build.

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
queries. It does not select an arbitrary price classification when overlapping
series are returned: ambiguous overlaps are rejected for investigation.

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

These are bidding-zone mappings. Historic configurations, country aggregates and
individual control areas may differ. v0.1 does not auto-substitute them.

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
