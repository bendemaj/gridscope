from gridscope.models.points import GenerationType

# Verified against ENTSO-E's area list and Postman PSR parameter list; see docs/providers.md.
AREA_CODES = {
    "DE": "10Y1001A1001A83F",
    "LU": "10YLU-CEGEDEL-NQ",
    "FR": "10YFR-RTE------C",
    "BE": "10YBE----------2",
    "NL": "10YNL----------L",
    "PL": "10YPL-AREA-----S",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "NO2": "10YNO-2--------T",
    "SE4": "10Y1001A1001A47J",
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
