DEFAULT_DB_PATH = "lead_finder.db"
DEFAULT_NICHE_PACKS_PATH = "niche_packs.json"

DEFAULT_NICHE_PACKS = {
    "Kesehatan": ["klinik", "klinik gigi", "dokter gigi", "dokter umum", "apotek"],
    "Kuliner": ["cafe", "restoran", "bakery", "catering", "coffee shop"],
    "Beauty": ["salon", "barbershop", "spa", "nail art"],
    "Jasa Rumah": ["kontraktor", "interior", "bengkel", "cleaning service", "laundry"],
    "Edukasi": ["kursus", "bimbel", "daycare", "tempat les"],
}

DEFAULT_EXCLUSION_KEYWORDS = [
    "indomaret",
    "alfamart",
    "starbucks",
    "kfc",
    "mcdonald",
    "transmart",
    "superindo",
    "mitra10",
    "rumah sakit",
    "hotel",
    "mall",
]

SOCIAL_AGGREGATOR_DOMAINS = [
    "instagram.com",
    "facebook.com",
    "wa.me",
    "linktr.ee",
    "tiktok.com",
    "tokopedia.com",
    "shopee.co.id",
]

WORKFLOW_STATUSES = ["new", "reviewed", "shortlisted", "contacted", "discarded"]
WEBSITE_STATUSES = [
    "none",
    "social_only",
    "error",
    "owned_domain_weak",
    "owned_domain_ok",
    "unknown",
]
LEAD_TIERS = ["A", "B", "C"]

DEFAULT_EXPORT_COLUMNS = [
    "opportunity_fit",
    "opportunity_reason",
    "lead_tier",
    "lead_score",
    "nama_usaha",
    "kategori",
    "alamat",
    "city",
    "website_url",
    "website_status",
    "audit_http_status",
    "nomor_telepon",
    "rating",
    "review_count",
    "workflow_status",
    "notes",
    "maps_url",
]


def default_niche_payload() -> dict[str, object]:
    return {
        "packs": DEFAULT_NICHE_PACKS,
        "excluded_keywords": DEFAULT_EXCLUSION_KEYWORDS,
    }
