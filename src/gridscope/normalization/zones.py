from gridscope.errors import InvalidQuery
from gridscope.models.zone import Zone

ZONES = {
    z.code: z
    for z in [
        Zone(
            code="DE",
            name="Germany",
            countries=("DE",),
            timezone="Europe/Berlin",
            area_type="country",
        ),
        Zone(
            code="LU",
            name="Luxembourg",
            countries=("LU",),
            timezone="Europe/Luxembourg",
            area_type="country",
        ),
        Zone(code="FR", name="France", countries=("FR",), timezone="Europe/Paris"),
        Zone(code="BE", name="Belgium", countries=("BE",), timezone="Europe/Brussels"),
        Zone(code="NL", name="Netherlands", countries=("NL",), timezone="Europe/Amsterdam"),
        Zone(code="PL", name="Poland", countries=("PL",), timezone="Europe/Warsaw"),
        Zone(code="DK1", name="Western Denmark", countries=("DK",), timezone="Europe/Copenhagen"),
        Zone(code="DK2", name="Eastern Denmark", countries=("DK",), timezone="Europe/Copenhagen"),
        Zone(code="NO2", name="Southern Norway", countries=("NO",), timezone="Europe/Oslo"),
        Zone(code="SE4", name="Southern Sweden", countries=("SE",), timezone="Europe/Stockholm"),
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
