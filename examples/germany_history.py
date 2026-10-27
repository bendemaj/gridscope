"""Fetch German data with SMARD, resample explicitly, then reopen stored observations."""

import argparse
import asyncio
from pathlib import Path

from gridscope import GridScope
from gridscope.config import Settings
from gridscope.models import TimeResolution


async def run(start: str, end: str, path: Path) -> None:
    settings = Settings(storage_path=path)
    async with GridScope("smard", settings=settings) as gs:
        load = await gs.load("DE", start, end, resolution=TimeResolution.HOUR)
        await gs.prices("DE_LU", start, end)
        await gs.generation("DE", start, end)
        print(load.to_dataframe()[["value", "unit", "quality"]])
        captures = gs.history("load", start, end, zone="DE")
        cutoff = captures[-1].recorded_at
        print(f"Load capture: {cutoff.isoformat()}")
    async with GridScope(
        "smard", settings=settings, mode="stored", as_of=cutoff, resolution=TimeResolution.HOUR
    ) as gs:
        replay = await gs.load("DE", start, end)
        assert replay.data == load.data
        print(f"Reopened {len(replay.data)} hourly observations from {path}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-09-01")
    parser.add_argument("--end", default="2026-09-02")
    parser.add_argument("--database", type=Path, default=Path("data/gridscope.sqlite3"))
    args = parser.parse_args()
    asyncio.run(run(args.start, args.end, args.database))
