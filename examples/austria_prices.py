"""Run with: uv run python examples/austria_prices.py --start 2026-09-01 --end 2026-09-02"""

import argparse
import asyncio

from gridscope import GridScope
from gridscope.errors import GridScopeError


async def main(start: str, end: str) -> None:
    async with GridScope() as gs:
        prices = await gs.prices("AT", start, end)
        print(prices.to_dataframe()[["value", "unit", "quality"]].to_string())
        for warning in prices.meta.warnings:
            print(f"Note: {warning}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Austrian day-ahead prices.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.start, args.end))
    except GridScopeError as exc:
        parser.exit(1, f"{exc.code}: {exc}\n")
