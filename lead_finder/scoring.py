from collections.abc import Mapping

from .utils import clamp


def matches_exclusion_keyword(name: str, excluded_keywords: list[str]) -> bool:
    lowered_name = (name or "").lower()
    return any(keyword.lower() in lowered_name for keyword in excluded_keywords if keyword.strip())


def tier_from_score(score: int) -> str:
    if score >= 60:
        return "A"
    if score >= 40:
        return "B"
    return "C"


def calculate_lead_score(
    lead: Mapping[str, object],
    excluded_keywords: list[str],
) -> tuple[int, str, bool]:
    score = 0
    website_status = str(lead.get("website_status") or "unknown")
    review_count = int(lead.get("review_count") or 0)
    phone = str(lead.get("phone") or "")
    niche_pack = str(lead.get("niche_pack") or "")
    excluded = matches_exclusion_keyword(str(lead.get("nama_usaha") or ""), excluded_keywords)

    if website_status == "none":
        score += 35
    elif website_status == "social_only":
        score += 25
    elif website_status == "error":
        score += 20
    elif website_status == "owned_domain_weak":
        score += 10
    elif website_status == "owned_domain_ok":
        score -= 15

    if phone and phone != "-":
        score += 10
    if niche_pack:
        score += 10
    if 5 <= review_count <= 200:
        score += 5
    if excluded:
        score -= 20

    final_score = clamp(score, 0, 100)
    return final_score, tier_from_score(final_score), excluded
