from datetime import timedelta

import pytest
from conftest import END, FIXTURES, START

from gridscope.errors import MalformedResponse, NoData, ProviderRejected
from gridscope.models import (
    DataQuality,
    FlowPoint,
    GenerationPoint,
    GenerationType,
    LoadPoint,
    PricePoint,
)
from gridscope.providers.entsoe.parser import parse


def parsed(kind="prices", xml=None, **kwargs):
    model = {
        "prices": PricePoint,
        "load": LoadPoint,
        "generation": GenerationPoint,
        "flows": FlowPoint,
    }[kind]
    return parse(
        xml or (FIXTURES / f"{kind}.xml").read_bytes(),
        model,
        start=kwargs.pop("start", START),
        end=kwargs.pop("end", END),
        retrieved_at=START,
        dataset=kind,
        **({"from_zone": "DE_LU", "to_zone": "AT"} if kind == "flows" else {"zone": "AT"}),
        **kwargs,
    )


@pytest.mark.parametrize("kind", ["prices", "load", "generation", "flows"])
def test_fixture(kind):
    points = parsed(kind)
    assert len(points) == (12 if kind == "generation" else 4)
    assert points[0].timestamp == START
    assert points[0].source_document == "synthetic-fixture"
    assert points[0].source_revision == "1"
    assert points[0].timestamp.tzinfo is not None


def test_consumption_excluded():
    assert all(p.value != 9999 for p in parsed("generation"))


def test_missing_a01_vs_constant_a03():
    xml = (FIXTURES / "prices.xml").read_bytes()
    xml = xml.replace(
        (
            b"<Point>\n        <position>2</position>\n"
            b"        <price.amount>20</price.amount>\n      </Point>"
        ),
        b"",
    )
    assert parsed(xml=xml)[1].quality == DataQuality.MISSING
    points = parsed(xml=xml.replace(b"<curveType>A01", b"<curveType>A03"))
    assert points[1].value == -10
    assert "constant block" in points[1].notes[0]


def test_explicit_missing_stops_a03_carry():
    xml = (
        (FIXTURES / "prices.xml")
        .read_bytes()
        .replace(b"<curveType>A01", b"<curveType>A03")
        .replace(b"<price.amount>20</price.amount>", b"")
    )
    assert parsed(xml=xml)[1].value is None


def test_interval_end_exclusive():
    points = parsed(start=START + timedelta(minutes=15), end=END - timedelta(minutes=15))
    assert [p.value for p in points] == [20, 40]


@pytest.mark.parametrize(
    "old,new",
    [
        (b"<position>2</position>", b"<position>1</position>"),
        (b"<position>1</position>", b"<position>0</position>"),
        (b"<resolution>PT15M", b"<resolution>PT5M"),
        (b"<currency_Unit.name>EUR", b"<currency_Unit.name>USD"),
        (b"<price.amount>20", b"<price.amount>NaN"),
        (b"<type>A44", b"<type>A65"),
        (b"<curveType>A01", b"<curveType>A99"),
        (b"10YAT-APG------L", b"WRONG"),
    ],
)
def test_reject_bad_xml_semantics(old, new):
    xml = (FIXTURES / "prices.xml").read_bytes().replace(old, new)
    with pytest.raises(MalformedResponse):
        parsed(xml=xml)


def test_unknown_production_preserved():
    xml = (FIXTURES / "generation.xml").read_bytes().replace(b"<psrType>B16", b"<psrType>B99")
    p = parsed("generation", xml)[0]
    assert p.generation_type == GenerationType.UNKNOWN
    assert p.production_code == "B99"


def test_acknowledgement_and_invalid_xml():
    for reason, exception in [
        ("No matching data found", NoData),
        ("Invalid parameter", ProviderRejected),
    ]:
        xml = (
            f"<Acknowledgement_MarketDocument><Reason><code>999</code><text>{reason}</text>"
            "</Reason></Acknowledgement_MarketDocument>"
        ).encode()
        with pytest.raises(exception):
            parsed(xml=xml)
    with pytest.raises(MalformedResponse):
        parsed(xml=b"<html>broken")
    with pytest.raises(MalformedResponse):
        parsed(xml=b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')


def test_flow_direction_verified():
    xml = (FIXTURES / "flows.xml").read_bytes().replace(b"10Y1001A1001A82H", b"WRONG")
    with pytest.raises(MalformedResponse):
        parsed("flows", xml)


def duplicate_price_xml(*, conflicting=False, sequence="1"):
    from copy import deepcopy
    from xml.etree.ElementTree import SubElement, tostring

    from gridscope.providers.entsoe.parser import read_xml

    root = read_xml((FIXTURES / "prices.xml").read_bytes())
    ts = root.find("TimeSeries")
    SubElement(ts, "classificationSequence_AttributeInstanceComponent.position").text = sequence
    other = deepcopy(ts)
    other.find("mRID").text = "duplicate-2"
    if conflicting:
        other.find("Period/Point/price.amount").text = "999"
    root.append(other)
    return tostring(root)


def test_identical_price_publications_preserve_provenance():
    points = parsed(xml=duplicate_price_xml())
    assert len(points) == 4
    assert points[0].value == -10
    assert points[0].source_auction_sequence == 1
    assert points[0].source_series == "1"
    assert points[0].duplicate_source_series == ("duplicate-2",)
    assert any("collapsed" in note for note in points[0].notes)


def test_conflicting_price_publications_still_fail():
    with pytest.raises(MalformedResponse, match="Overlapping"):
        parsed(xml=duplicate_price_xml(conflicting=True))


def test_other_auction_sequence_is_not_silently_used():
    with pytest.raises(MalformedResponse, match="sequence 1"):
        parsed(xml=duplicate_price_xml(sequence="2"))
