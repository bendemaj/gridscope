from gridscope.models.points import GenerationType

# Verified against ENTSO-E's area list and Postman PSR parameter list; see docs/providers.md.
AREA_CODES = {
    "AT": "10YAT-APG------L",
    "DE_LU": "10Y1001A1001A82H",
    "CZ": "10YCZ-CEPS-----N",
    "SK": "10YSK-SEPS-----K",
    "HU": "10YHU-MAVIR----U",
    "SI": "10YSI-ELES-----O",
    "IT_NORTH": "10Y1001A1001A73I",
    "CH": "10YCH-SWISSGRIDZ",
}
PRODUCTION_TYPES = dict(
    zip(
        [f"B{i:02}" for i in range(1, 21)],
        list(GenerationType)[:20],
        strict=True,
    )
)

PRODUCTION_TYPES["B25"] = GenerationType.ENERGY_STORAGE
