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

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SearchQuery":
        return cls(
            niche_pack=str(payload.get("niche_pack") or ""),
            keyword=str(payload.get("keyword") or ""),
            base_location=str(payload.get("base_location") or ""),
            location_variant=str(payload.get("location_variant") or ""),
            query=str(payload.get("query") or ""),
        )


@dataclass
class ScrapeConfig:
    selected_niche_packs: list[str]
    niche_packs: dict[str, list[str]] = field(
        default_factory=lambda: {
            key: value[:] for key, value in DEFAULT_NICHE_PACKS.items()
        }
    )
    locations: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(
        default_factory=lambda: DEFAULT_EXCLUSION_KEYWORDS[:]
    )
    db_path: str = DEFAULT_DB_PATH
    max_scrolls: int = 0
    max_results: int = 0
    scroll_pause: float = 1.5
    detail_pause: float = 2.0
    stagnation_limit: int = 5
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RawPlaceRecord":
        rating = payload.get("rating")
        review_count = payload.get("review_count")
        return cls(
            niche_pack=str(payload.get("niche_pack") or ""),
            keyword=str(payload.get("keyword") or ""),
            search_query=str(payload.get("search_query") or ""),
            nama_usaha=str(payload.get("nama_usaha") or ""),
            kategori=str(payload.get("kategori") or ""),
            alamat=str(payload.get("alamat") or ""),
            city=str(payload.get("city") or ""),
            website_url=str(payload.get("website_url") or ""),
            nomor_telepon=str(payload.get("nomor_telepon") or ""),
            maps_url=str(payload.get("maps_url") or ""),
            rating=float(rating) if rating not in ("", None, "-") else None,
            review_count=int(review_count)
            if review_count not in ("", None, "-")
            else None,
        )


@dataclass(frozen=True)
class DiscoveredPlace:
    maps_url: str
    search_query: SearchQuery

    def to_dict(self) -> dict[str, Any]:
        return {
            "maps_url": self.maps_url,
            "search_query": self.search_query.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiscoveredPlace":
        raw_search_query = payload.get("search_query")
        search_query_payload = (
            raw_search_query if isinstance(raw_search_query, dict) else {}
        )
        return cls(
            maps_url=str(payload.get("maps_url") or ""),
            search_query=SearchQuery.from_dict(search_query_payload),
        )


@dataclass
class ScrapeCheckpoint:
    session_name: str
    query_cursor: int = 0
    discovered_places: list[DiscoveredPlace] = field(default_factory=list)
    scraped_urls: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    raw_output_path: str = ""
    processed_output_path: str = ""
    blocked_reason: str = ""
    status: str = "running"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "query_cursor": self.query_cursor,
            "discovered_places": [place.to_dict() for place in self.discovered_places],
            "scraped_urls": self.scraped_urls,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "raw_output_path": self.raw_output_path,
            "processed_output_path": self.processed_output_path,
            "blocked_reason": self.blocked_reason,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScrapeCheckpoint":
        raw_discovered_places = payload.get("discovered_places")
        discovered_places = (
            raw_discovered_places if isinstance(raw_discovered_places, list) else []
        )
        raw_scraped_urls = payload.get("scraped_urls")
        scraped_urls = raw_scraped_urls if isinstance(raw_scraped_urls, list) else []
        return cls(
            session_name=str(payload.get("session_name") or ""),
            query_cursor=int(payload.get("query_cursor") or 0),
            discovered_places=[
                DiscoveredPlace.from_dict(item)
                for item in discovered_places
                if isinstance(item, dict)
            ],
            scraped_urls=[str(item) for item in scraped_urls if str(item).strip()],
            started_at=str(payload.get("started_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            raw_output_path=str(payload.get("raw_output_path") or ""),
            processed_output_path=str(payload.get("processed_output_path") or ""),
            blocked_reason=str(payload.get("blocked_reason") or ""),
            status=str(payload.get("status") or "running"),
        )


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
