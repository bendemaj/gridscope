from gridscope.errors import InvalidQuery
from gridscope.models.zone import Zone

ZONES = {
    z.code: z
    for z in [
        Zone(code="AT", name="Austria", countries=("AT",), timezone="Europe/Vienna"),
        Zone(
            code="DE_LU",
            name="Germany–Luxembourg",
            countries=("DE", "LU"),
            timezone="Europe/Berlin",
        ),
        Zone(code="CZ", name="Czechia", countries=("CZ",), timezone="Europe/Prague"),
        Zone(code="SK", name="Slovakia", countries=("SK",), timezone="Europe/Bratislava"),
        Zone(code="HU", name="Hungary", countries=("HU",), timezone="Europe/Budapest"),
        Zone(code="SI", name="Slovenia", countries=("SI",), timezone="Europe/Ljubljana"),
        Zone(code="IT_NORTH", name="Northern Italy", countries=("IT",), timezone="Europe/Rome"),
        Zone(code="CH", name="Switzerland", countries=("CH",), timezone="Europe/Zurich"),
    ]
}


def zone_code(value: str) -> str:
    code = value.strip().upper().replace("-", "_")
    if code not in ZONES:
        raise InvalidQuery(f"Unknown zone {value!r}. Supported: {', '.join(ZONES)}.")
    return code
