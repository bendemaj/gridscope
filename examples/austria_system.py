"""Austrian system report. All numbers come from the selected provider response."""

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Sequence

from gridscope import GridScope
from gridscope.errors import GridScopeError, NoData
from gridscope.intelligence.metrics import (
    RENEWABLES,
    price_spread,
    price_volatility,
    renewable_share,
    residual_load,
)
from gridscope.models import GenerationPoint
from gridscope.models.common import Point
from gridscope.normalization.time import resolution_delta


def weighted_average(points: Sequence[Point]) -> float | None:
    valid = [p for p in points if p.value is not None]
    hours = sum(resolution_delta(p.resolution).total_seconds() for p in valid)
    return (
        sum(
            p.value * resolution_delta(p.resolution).total_seconds()
            for p in valid
            if p.value is not None
        )
        / hours
        if hours
        else None
    )


def show(value: float | None, unit: str, scale: float = 1) -> str:
    return f"{value / scale:,.2f} {unit}" if value is not None else "unavailable"


def generation_totals(points: Sequence[GenerationPoint], renewable: bool = False) -> list[Point]:
    groups = defaultdict(list)
    expected = {(p.generation_type, p.production_code) for p in points}
    for p in points:
        groups[p.timestamp].append(p)
    totals = []
    for group in groups.values():
        complete = {(p.generation_type, p.production_code) for p in group} == expected and all(
            p.value is not None for p in group
        )
        value = (
            sum(
                p.value
                for p in group
                if p.value is not None and (not renewable or p.generation_type in RENEWABLES)
            )
            if complete
            else None
        )
        totals.append(group[0].model_copy(update={"value": value}))
    return totals


async def report(gs: GridScope, start: str, end: str) -> str:
    load = await gs.load("AT", start, end)
    generation = await gs.generation("AT", start, end)
    prices = await gs.prices("AT", start, end)
    shares = renewable_share(generation.data)
    residual = residual_load(load.data, generation.data)
    volatility = price_volatility(prices.data, window=4)
    spreads = price_spread(prices.data)
    peak_load = max((p.value for p in load.data if p.value is not None), default=None)
    total_generation = weighted_average(generation_totals(generation.data))
    renewable_generation = weighted_average(generation_totals(generation.data, True))
    lines = [
        "AUSTRIA",
        f"Period (UTC): {load.meta.start} to {load.meta.end}",
        "",
        f"Average reported load:       {show(weighted_average(load.data), 'GW', 1000)}",
        f"Peak reported load:          {show(peak_load, 'GW', 1000)}",
        f"Average reported generation: {show(total_generation, 'GW', 1000)}",
        f"Average renewable output:    {show(renewable_generation, 'GW', 1000)}",
        f"Average renewable share:     {show(weighted_average(shares), '%')}",
        f"Average residual load:       {show(weighted_average(residual), 'GW', 1000)}",
        f"Average day-ahead price:     {show(weighted_average(prices.data), 'EUR/MWh')}",
    ]
    for p in spreads:
        lines.append(f"Price spread {p.timestamp.date()}:    {show(p.value, p.unit)} ({p.quality})")
    lines.append(f"Latest volatility (4 MTUs):  {show(volatility[-1].value, 'EUR/MWh')}")
    warnings = [*load.meta.warnings, *generation.meta.warnings, *prices.meta.warnings]
    try:
        imports = await gs.net_imports("AT", start, end, neighbors=["DE_LU"])
        lines.append(
            f"Net imports, DE_LU only:     {show(weighted_average(imports.data), 'GW', 1000)}"
        )
        warnings.extend(imports.meta.warnings)
    except NoData:
        lines.append("Net imports, DE_LU only:     unavailable")
    if any(p.value is None for p in [*shares, *residual, *load.data, *prices.data]):
        warnings.append("Incomplete observations: averages use available values only.")
    lines.extend(
        [
            "",
            "Source: ENTSO-E Transparency Platform. Calculations by GridScope.",
            "Averages are duration-weighted over returned intervals; "
            "share is an average of interval shares.",
        ]
    )
    lines.extend(f"Note: {w}" for w in dict.fromkeys(warnings))
    return "\n".join(lines)


async def main(start: str, end: str) -> None:
    async with GridScope() as gs:
        print(await report(gs, start, end))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="What happened in the Austrian electricity system?"
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.start, args.end))
    except GridScopeError as exc:
        parser.exit(1, f"{exc.code}: {exc}\n")
