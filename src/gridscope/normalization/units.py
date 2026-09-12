from gridscope.errors import MalformedResponse


def power_mw(value: float | None, unit: str) -> float | None:
    factors = {"MAW": 1, "MW": 1, "KWT": 0.001, "KW": 0.001, "GW": 1000}
    if unit not in factors:
        raise MalformedResponse("Expected power units; energy values cannot be treated as MW.")
    return value * factors[unit] if value is not None else None


def price_eur_mwh(value: float | None, currency: str, unit: str) -> float | None:
    if currency != "EUR" or unit != "MWH":
        raise MalformedResponse("Only EUR/MWh prices are supported; no implicit FX conversion.")
    return value
