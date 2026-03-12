from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .defaults import DEFAULT_DB_PATH, DEFAULT_EXCLUSION_KEYWORDS, DEFAULT_NICHE_PACKS


@dataclass(frozen=True)
class SearchQuery:
    niche_pack: str
    keyword: str
    base_location: str
    location_variant: str
    query: str


@dataclass
class ScrapeConfig:
    selected_niche_packs: list[str]
    niche_packs: dict[str, list[str]] = field(
        default_factory=lambda: {key: value[:] for key, value in DEFAULT_NICHE_PACKS.items()}
    )
    locations: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=lambda: DEFAULT_EXCLUSION_KEYWORDS[:])
    db_path: str = DEFAULT_DB_PATH
    max_scrolls: int = 18
    max_results: int = 250
    scroll_pause: float = 1.5
    detail_pause: float = 2.0
    stagnation_limit: int = 3
    headless: bool = True
    expand_locations: bool = True
    audit_websites: bool = True
    request_timeout: float = 8.0
    max_retries: int = 2
    audit_max_workers: int = 5
    audit_stale_after_days: int = 14

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawPlaceRecord:
    niche_pack: str
    keyword: str
    search_query: str
    nama_usaha: str
    kategori: str
    alamat: str
    city: str
    website_url: str
    nomor_telepon: str
    maps_url: str
    rating: Optional[float] = None
    review_count: Optional[int] = None


@dataclass
class LeadAudit:
    website_status: str
    final_url: str = ""
    final_domain: str = ""
    http_status: Optional[int] = None
    title: str = ""
    has_viewport: bool = False
    text_length: int = 0
    error_message: str = ""


@dataclass
class LeadFilters:
    city: str = ""
    niche_pack: str = ""
    workflow_status: str = ""
    lead_tier: str = ""
    website_status: str = ""
    text_query: str = ""
