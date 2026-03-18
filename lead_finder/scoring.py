from collections.abc import Mapping

from .utils import clamp


def matches_exclusion_keyword(name: str, excluded_keywords: list[str]) -> bool:
    lowered_name = (name or "").lower()
    return any(keyword.lower() in lowered_name for keyword in excluded_keywords if keyword.strip())


def tier_from_score(score: int) -> str:
    if score >= 70:
        return "A"
    if score >= 45:
        return "B"
    return "C"


def describe_opportunity(lead: Mapping[str, object]) -> tuple[str, str]:
    website_status = str(lead.get("website_status") or "unknown")
    rating = _as_float(lead.get("rating"))
    review_count = int(lead.get("review_count") or 0)

    reasons: list[str] = []
    if website_status == "none":
        reasons.append("website belum dicantumkan")
    elif website_status == "error":
        reasons.append("website mati/error")
    elif website_status == "social_only":
        reasons.append("website masih social-only")
    elif website_status == "owned_domain_weak":
        reasons.append("website lemah")
    elif website_status == "owned_domain_ok":
        reasons.append("website sudah cukup baik")
    else:
        reasons.append("status website belum jelas")

    if rating is not None:
        reasons.append(f"rating {rating:.1f}")
    if review_count > 0:
        reasons.append(f"{review_count} ulasan")

    if website_status in {"none", "error"} and (rating or 0.0) >= 4.2 and review_count >= 10:
        return "hot", ", ".join(reasons)
    if website_status in {"none", "error", "social_only", "owned_domain_weak"} and (
        (rating or 0.0) >= 4.0 and review_count >= 5
    ):
        return "warm", ", ".join(reasons)
    return "low", ", ".join(reasons)


def calculate_lead_score(
    lead: Mapping[str, object],
    excluded_keywords: list[str],
) -> tuple[int, str, bool]:
    score = 0
    website_status = str(lead.get("website_status") or "unknown")
    review_count = int(lead.get("review_count") or 0)
    rating = _as_float(lead.get("rating"))
    phone = str(lead.get("phone") or "")
    niche_pack = str(lead.get("niche_pack") or "")
    excluded = matches_exclusion_keyword(str(lead.get("nama_usaha") or ""), excluded_keywords)

    if website_status == "none":
        score += 38
    elif website_status == "error":
        score += 34
    elif website_status == "social_only":
        score += 18
    elif website_status == "owned_domain_weak":
        score += 6
    elif website_status == "owned_domain_ok":
        score -= 18

    if rating is not None:
        if rating >= 4.7:
            score += 22
        elif rating >= 4.4:
            score += 18
        elif rating >= 4.2:
            score += 14
        elif rating >= 4.0:
            score += 8
        elif rating < 3.8:
            score -= 10

    if phone and phone != "-":
        score += 8
    if niche_pack:
        score += 6

    if review_count >= 100:
        score += 18
    elif review_count >= 30:
        score += 14
    elif review_count >= 10:
        score += 10
    elif review_count >= 5:
        score += 6

    if excluded:
        score -= 25

    final_score = clamp(score, 0, 100)
    return final_score, tier_from_score(final_score), excluded


def _as_float(value: object) -> float | None:
    if value in ("", None, "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
