from pydantic import BaseModel

DOCS = "https://documenter.getpostman.com/view/7009892/2s93JtP3F6"
TERMS = "https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions"


class SourceDataset(BaseModel):
    provider: str = "ENTSOE"
    dataset: str
    description: str
    geographical_coverage: str = "Austria first; other registered zones subject to availability"
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
