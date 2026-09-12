"""Decode fixed and variable blocks without interpolating missing publications."""

from datetime import datetime
from typing import TypeVar
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pydantic import ValidationError

from gridscope.errors import InvalidQuery, MalformedResponse, NoData, ProviderRejected
from gridscope.models import DataQuality, FlowPoint, GenerationPoint, GenerationType, PricePoint
from gridscope.models.common import Point
from gridscope.normalization.time import resolution_delta, utc
from gridscope.normalization.units import power_mw, price_eur_mwh
from gridscope.providers.entsoe.mappings import AREA_CODES, PRODUCTION_TYPES

P = TypeVar("P", bound=Point)


def read_xml(xml: bytes) -> Element:
    try:
        root = fromstring(xml)
        for element in root.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        return root
    except (ParseError, DefusedXmlException):
        raise MalformedResponse("ENTSO-E returned invalid or unsafe XML.") from None


def text(element: Element, path: str, default: str = "") -> str:
    return (element.findtext(path) or default).strip()


def check_acknowledgement(root: Element) -> None:
    if root.tag == "Acknowledgement_MarketDocument":
        reasons = " ".join(text(r, "text").lower() for r in root.findall(".//Reason"))
        # Code 999 is used for multiple rejection reasons, not exclusively no data.
        if "no matching data" in reasons or "no data found" in reasons:
            raise NoData("ENTSO-E has no data for the requested period and area.")
        raise ProviderRejected(
            "ENTSO-E rejected the query; check dataset availability and parameters."
        )


def series_count(xml: bytes) -> int:
    root = read_xml(xml)
    check_acknowledgement(root)
    return len(root.findall("TimeSeries"))


def parse(
    xml: bytes,
    model: type[P],
    *,
    start: datetime,
    end: datetime,
    retrieved_at: datetime,
    dataset: str,
    zone: str | None = None,
    from_zone: str | None = None,
    to_zone: str | None = None,
) -> list[P]:
    root = read_xml(xml)
    check_acknowledgement(root)
    expected = {"prices": "A44", "load": "A65", "generation": "A75", "flows": "A11"}
    if text(root, "type") != expected[dataset]:
        raise MalformedResponse("Unexpected ENTSO-E document type.")
    if dataset in {"load", "generation"} and text(root, "process.processType") != "A16":
        raise MalformedResponse("Expected realised data, received a different process type.")
    results: list[P] = []
    seen: set[tuple[datetime, str]] = set()
    try:
        for ts in root.findall("TimeSeries"):
            extra: dict[str, object] = {}
            if zone:
                extra["zone"] = zone
            if model is GenerationPoint:
                incoming = text(ts, "inBiddingZone_Domain.mRID")
                outgoing = text(ts, "outBiddingZone_Domain.mRID")
                if outgoing and not incoming:
                    continue  # Pumping/consumption is not electricity generation.
                if not zone or incoming != AREA_CODES[zone] or outgoing:
                    raise MalformedResponse("Unexpected generation area or direction.")
                production_code = text(ts, "MktPSRType/psrType")
                if not production_code:
                    raise MalformedResponse("Missing generation production type.")
                extra["generation_type"] = PRODUCTION_TYPES.get(
                    production_code, GenerationType.UNKNOWN
                )
                extra["production_code"] = production_code
            elif model is FlowPoint:
                if (
                    not from_zone
                    or not to_zone
                    or text(ts, "out_Domain.mRID") != AREA_CODES[from_zone]
                    or text(ts, "in_Domain.mRID") != AREA_CODES[to_zone]
                ):
                    raise MalformedResponse("Unexpected physical flow direction or area.")
                extra.update(from_zone=from_zone, to_zone=to_zone)
            elif model is PricePoint:
                if (
                    not zone
                    or text(ts, "in_Domain.mRID") != AREA_CODES[zone]
                    or text(ts, "out_Domain.mRID") != AREA_CODES[zone]
                ):
                    raise MalformedResponse("Unexpected price area.")
                contract = text(ts, "contract_MarketAgreement.type")
                if contract and contract != "A01":
                    raise MalformedResponse("Expected day-ahead price data.")
            elif not zone or text(ts, "outBiddingZone_Domain.mRID") != AREA_CODES[zone]:
                raise MalformedResponse("Unexpected load area.")
            curve = text(ts, "curveType")
            if curve not in {"A01", "A03"}:
                raise MalformedResponse("Only A01 and A03 time-series curves are supported.")
            periods = ts.findall("Period")
            if not periods:
                raise MalformedResponse("Time series has no periods.")
            for period in periods:
                a = utc(text(period, "timeInterval/start"))
                b = utc(text(period, "timeInterval/end"))
                res = text(period, "resolution").replace("PT1H", "PT60M")
                step = resolution_delta(res)
                count = (b - a) / step
                if count <= 0 or count != int(count) or count > 366 * 96:
                    raise MalformedResponse("Invalid period duration or resolution.")
                values: dict[int, float | None] = {}
                for point in period.findall("Point"):
                    pos = int(text(point, "position"))
                    if pos in values or pos < 1 or pos > count:
                        raise MalformedResponse("Duplicate or out-of-range point position.")
                    raw = text(point, "price.amount" if model is PricePoint else "quantity")
                    values[pos] = float(raw) if raw else None
                previous: float | None = None
                for pos in range(1, int(count) + 1):
                    timestamp = a + (pos - 1) * step
                    if pos in values:
                        previous = values[pos]
                    value = values.get(pos) if curve == "A01" else previous
                    if not start <= timestamp < end:
                        continue
                    notes: list[str] = []
                    if curve == "A03" and pos not in values and value is not None:
                        notes.append("Expanded provider-defined constant block (A03).")
                    if extra.get("generation_type") == GenerationType.UNKNOWN:
                        notes.append(
                            "Unmapped provider production type; excluded from renewable numerator."
                        )
                    if model is PricePoint:
                        value = price_eur_mwh(
                            value,
                            text(ts, "currency_Unit.name"),
                            text(ts, "price_Measure_Unit.name"),
                        )
                    else:
                        value = power_mw(value, text(ts, "quantity_Measure_Unit.name"))
                    identity = (timestamp, str(extra.get("production_code", "")))
                    if identity in seen:
                        raise MalformedResponse("Overlapping series cannot be safely combined.")
                    seen.add(identity)
                    results.append(
                        model.model_validate(
                            dict(
                                timestamp=timestamp,
                                value=value,
                                resolution=res,
                                source="ENTSOE",
                                source_dataset=dataset,
                                retrieved_at=retrieved_at,
                                quality=DataQuality.OBSERVED
                                if value is not None
                                else DataQuality.MISSING,
                                source_document=text(root, "mRID") or None,
                                source_revision=text(root, "revisionNumber") or None,
                                source_series=text(ts, "mRID") or None,
                                source_curve=curve,
                                notes=notes,
                                **extra,
                            )
                        )
                    )
    except (ValueError, TypeError, ValidationError, InvalidQuery):
        raise MalformedResponse(
            "ENTSO-E data contains invalid timestamps, units or point values."
        ) from None
    if not results:
        raise NoData("No matching points in the requested interval.")
    return sorted(results, key=lambda p: p.timestamp)
