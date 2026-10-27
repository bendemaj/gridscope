from pydantic import BaseModel

DOCS = "https://documenter.getpostman.com/view/7009892/2s93JtP3F6"
TERMS = "https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions"


class SourceDataset(BaseModel):
    provider: str = "ENTSOE"
    dataset: str
    description: str
    geographical_coverage: str = (
        "Germany, Austria and registered neighboring markets; dataset-specific availability"
    )
    resolutions: tuple[str, ...] = ("PT15M", "PT30M", "PT60M")
    update_frequency: str = "Provider publications and revisions; no guaranteed polling SLA"
    documentation_url: str = DOCS
    terms_url: str = TERMS
    license: str = (
        "Requires verification with primary data owner; not listed for automatic CC-BY reuse"
    )
    attribution: str = "Source: ENTSO-E Transparency Platform. Normalized by GridScope."
    commercial_reuse: str = (
        "Verify applicable primary-owner rights and current terms before commercial reuse."
    )
    redistribution: str = "Verify applicable primary-owner rights before redistribution."
    verified_on: str = "2026-09-12"


SOURCES = [
    SourceDataset(dataset="prices", description="Day-ahead energy prices, Article 12.1.D"),
    SourceDataset(dataset="load", description="Actual total load, Article 6.1.A"),
    SourceDataset(dataset="generation", description="Actual generation per type, Article 16.1.B&C"),
    SourceDataset(
        dataset="flows",
        description="Directional physical flows, Article 12.1.G",
        license="CC-BY-4.0 for listed eligible data (18 October 2023 list); exceptions apply",
        commercial_reuse=(
            "Permitted for eligible listed data with attribution and indication of changes."
        ),
        redistribution=(
            "Permitted for eligible listed data under CC-BY-4.0; retain attribution and terms."
        ),
    ),
]


SOURCES += [
    SourceDataset(
        provider="SMARD",
        dataset=dataset,
        description=description,
        geographical_coverage=coverage,
        resolutions=("PT15M",),
        documentation_url="https://www.smard.de/home/downloadcenter/download-marktdaten",
        terms_url="https://www.smard.de/home/datennutzung",
        license="CC BY 4.0",
        attribution="Bundesnetzagentur | SMARD.de. Normalized by GridScope.",
        commercial_reuse="Permitted under CC BY 4.0 with attribution and indication of changes.",
        redistribution="Permitted under CC BY 4.0; retain attribution, license and changes.",
        verified_on="2026-10-27",
    )
    for dataset, description, coverage in [
        (
            "prices",
            "Day-ahead prices at SMARD chart cadence",
            "DE_LU, AT, BE, CZ, CH, DK1, DK2, FR, HU, IT_NORTH, NL, NO2, PL, SE4, SI",
        ),
        ("load", "Realized grid load; MWh converted to average MW", "DE, DE_LU, AT, LU"),
        (
            "generation",
            "Realized generation by SMARD technology; MWh converted to MW",
            "DE, DE_LU, AT, LU; technologies vary by region",
        ),
        (
            "flows",
            "Directional physical flows; MWh converted to average MW",
            "Mapped borders of DE, DE_LU, AT and LU; see provider documentation",
        ),
    ]
]
