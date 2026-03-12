import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def parse_multiline_text(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def normalize_maps_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def ensure_parent_dir(path: str | Path) -> Path:
    path_obj = Path(path).expanduser()
    if not path_obj.is_absolute():
        path_obj = Path.cwd() / path_obj
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return path_obj


def ensure_csv_path(path: str | Path) -> Path:
    path_obj = ensure_parent_dir(path)
    if path_obj.suffix.lower() != ".csv":
        path_obj = path_obj.with_suffix(".csv")
    return path_obj


def extract_domain(url: str) -> str:
    if not url or url == "-":
        return ""
    value = url if "://" in url else f"https://{url}"
    try:
        return urlsplit(value).netloc.lower().lstrip("www.")
    except ValueError:
        return ""


def guess_city(address: str, fallback: str = "") -> str:
    if fallback and fallback != "-":
        return fallback
    if not address or address == "-":
        return "-"
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return "-"
    if len(parts) >= 2:
        return parts[-2]
    return parts[-1]


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def write_csv_rows(path: str | Path, fieldnames: list[str], rows: list[dict[str, object]]) -> Path:
    csv_path = ensure_csv_path(path)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return csv_path
