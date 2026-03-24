import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .app import LeadFinderService
from .models import RawPlaceRecord, ScrapeCheckpoint, ScrapeConfig
from .scraper import CaptchaDetectedError, GoogleMapsScraper
from .utils import now_utc_iso

LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], None]

RAW_CSV_COLUMNS = [
    "niche_pack",
    "keyword",
    "search_query",
    "nama_usaha",
    "kategori",
    "alamat",
    "city",
    "website_url",
    "nomor_telepon",
    "maps_url",
    "rating",
    "review_count",
]


@dataclass(frozen=True)
class SessionPaths:
    session_name: str
    raw_csv_path: Path
    processed_csv_path: Path
    checkpoint_path: Path
    db_path: Path


def slugify_session_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return (
        normalized or f"crawl-{now_utc_iso().replace(':', '-').replace('+00:00', 'z')}"
    )


def build_session_paths(
    session_name: str,
    data_dir: str = "data",
    db_path: Optional[str] = None,
) -> SessionPaths:
    data_dir_path = Path(data_dir).expanduser()
    state_dir_path = Path.cwd() / ".state"
    if not data_dir_path.is_absolute():
        data_dir_path = Path.cwd() / data_dir_path
    data_dir_path.mkdir(parents=True, exist_ok=True)
    state_dir_path.mkdir(parents=True, exist_ok=True)

    session_slug = slugify_session_name(session_name)
    resolved_db_path = (
        Path(db_path).expanduser() if db_path else data_dir_path / "lead_finder.db"
    )
    if not resolved_db_path.is_absolute():
        resolved_db_path = Path.cwd() / resolved_db_path
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)

    return SessionPaths(
        session_name=session_slug,
        raw_csv_path=state_dir_path / f"{session_slug}.working.csv",
        processed_csv_path=data_dir_path / f"{session_slug}.csv",
        checkpoint_path=state_dir_path / f"{session_slug}.checkpoint.json",
        db_path=resolved_db_path,
    )


def append_raw_record(path: str | Path, record: RawPlaceRecord) -> Path:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_CSV_COLUMNS)
        if should_write_header:
            writer.writeheader()
        writer.writerow(record.to_dict())
    return csv_path


def load_raw_records(path: str | Path) -> list[RawPlaceRecord]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [RawPlaceRecord.from_dict(dict(row)) for row in reader]


def count_csv_rows(path: str | Path) -> int:
    csv_path = Path(path)
    if not csv_path.exists():
        return 0
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


def save_checkpoint(path: str | Path, checkpoint: ScrapeCheckpoint) -> Path:
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = checkpoint.to_dict()
    with checkpoint_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return checkpoint_path


def load_checkpoint(path: str | Path) -> Optional[ScrapeCheckpoint]:
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return None

    with checkpoint_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return None
    return ScrapeCheckpoint.from_dict(payload)


def load_keywords_csv(path: str | Path) -> list[str]:
    csv_path = Path(path)
    if not csv_path.is_absolute():
        csv_path = Path.cwd() / csv_path
    if not csv_path.exists():
        raise FileNotFoundError(f"File kata kunci tidak ditemukan: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        first_column = reader.fieldnames[0]
        keywords = [str(row.get(first_column) or "").strip() for row in reader]
    return [keyword for keyword in dict.fromkeys(keywords) if keyword]


def load_locations_text(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = Path.cwd() / file_path
    if not file_path.exists():
        raise FileNotFoundError(f"File lokasi tidak ditemukan: {file_path}")
    return [
        location
        for location in dict.fromkeys(
            line.strip()
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    ]


def run_headless_session(
    config: ScrapeConfig,
    session_name: str,
    data_dir: str = "data",
    export_hot_only: bool = True,
    logger: Optional[LogCallback] = None,
) -> dict[str, object]:
    log = logger or (lambda _message: None)
    paths = build_session_paths(
        session_name=session_name,
        data_dir=data_dir,
        db_path=config.db_path,
    )
    config.db_path = str(paths.db_path)

    checkpoint = load_checkpoint(paths.checkpoint_path)
    if checkpoint is None:
        checkpoint = ScrapeCheckpoint(
            session_name=paths.session_name,
            started_at=now_utc_iso(),
            raw_output_path=str(paths.raw_csv_path),
            processed_output_path=str(paths.processed_csv_path),
            status="running",
        )
    checkpoint.session_name = paths.session_name
    checkpoint.raw_output_path = str(paths.raw_csv_path)
    checkpoint.processed_output_path = str(paths.processed_csv_path)
    if not checkpoint.started_at:
        checkpoint.started_at = now_utc_iso()

    raw_records = load_raw_records(paths.raw_csv_path)
    checkpoint.scraped_urls = list(
        dict.fromkeys(
            checkpoint.scraped_urls
            + [record.maps_url for record in raw_records if record.maps_url]
        )
    )

    if raw_records:
        log(
            f"Resume sesi `{paths.session_name}` dengan {len(raw_records)} raw record tersimpan."
        )
    if checkpoint.status == "completed" and paths.processed_csv_path.exists():
        return {
            "status": "success",
            "message": "Sesi sudah selesai sebelumnya, dilewati.",
            "session_name": paths.session_name,
            "processed_csv_path": str(paths.processed_csv_path),
            "checkpoint_path": str(paths.checkpoint_path),
            "db_path": str(paths.db_path),
            "total_raw": len(raw_records),
            "total_processed": len(raw_records),
            "total_exported": count_csv_rows(paths.processed_csv_path),
            "total_audited": 0,
            "run_id": None,
            "export_hot_only": export_hot_only,
        }

    def persist_checkpoint(state: ScrapeCheckpoint) -> None:
        state.session_name = paths.session_name
        state.raw_output_path = str(paths.raw_csv_path)
        state.processed_output_path = str(paths.processed_csv_path)
        state.updated_at = now_utc_iso()
        save_checkpoint(paths.checkpoint_path, state)

    def persist_record(record: RawPlaceRecord) -> None:
        append_raw_record(paths.raw_csv_path, record)

    scraper = GoogleMapsScraper(config=config, logger=log)
    status = "success"
    message = ""
    try:
        scraper.run_resumable(
            checkpoint=checkpoint,
            existing_records=raw_records,
            on_checkpoint=persist_checkpoint,
            on_record=persist_record,
        )
        checkpoint.status = "completed"
        checkpoint.blocked_reason = ""
        persist_checkpoint(checkpoint)
    except CaptchaDetectedError as exc:
        status = "blocked"
        message = str(exc)
        checkpoint.status = "blocked"
        checkpoint.blocked_reason = message
        persist_checkpoint(checkpoint)
        log(message)
    except Exception as exc:
        checkpoint.status = "error"
        checkpoint.blocked_reason = str(exc)
        persist_checkpoint(checkpoint)
        raise

    raw_records = load_raw_records(paths.raw_csv_path)
    processing_summary: dict[str, object] = {
        "run_id": None,
        "total_found": len(raw_records),
        "total_scored": 0,
        "audited": 0,
        "lead_ids": [],
    }
    lead_ids: list[int] = []
    total_processed = 0
    total_audited = 0
    if raw_records:
        service = LeadFinderService(logger=log)
        processing_summary = service.process_raw_records(config, raw_records)

        raw_lead_ids = processing_summary.get("lead_ids")
        if isinstance(raw_lead_ids, list):
            lead_ids = [item for item in raw_lead_ids if isinstance(item, int)]

        raw_total_processed = processing_summary.get("total_scored")
        if isinstance(raw_total_processed, int):
            total_processed = raw_total_processed

        raw_total_audited = processing_summary.get("audited")
        if isinstance(raw_total_audited, int):
            total_audited = raw_total_audited

        _, exported_count = service.export_leads_by_ids(
            config.db_path,
            lead_ids,
            str(paths.processed_csv_path),
            opportunity_fit_filter="hot" if export_hot_only else "",
        )
    else:
        exported_count = 0

    return {
        "status": status,
        "message": message,
        "session_name": paths.session_name,
        "processed_csv_path": str(paths.processed_csv_path),
        "checkpoint_path": str(paths.checkpoint_path),
        "db_path": str(paths.db_path),
        "total_raw": len(raw_records),
        "total_processed": total_processed,
        "total_exported": exported_count,
        "total_audited": total_audited,
        "run_id": processing_summary.get("run_id"),
        "export_hot_only": export_hot_only,
    }


def build_city_keyword_config(
    city: str,
    keyword: str,
    template: ScrapeConfig,
) -> ScrapeConfig:
    keyword_pack_name = "CSV Keywords"
    return ScrapeConfig(
        selected_niche_packs=[keyword_pack_name],
        niche_packs={keyword_pack_name: [keyword]},
        locations=[city],
        excluded_keywords=template.excluded_keywords[:],
        db_path=template.db_path,
        max_scrolls=template.max_scrolls,
        max_results=template.max_results,
        scroll_pause=template.scroll_pause,
        detail_pause=template.detail_pause,
        stagnation_limit=template.stagnation_limit,
        headless=template.headless,
        expand_locations=template.expand_locations,
        audit_websites=template.audit_websites,
        request_timeout=template.request_timeout,
        max_retries=template.max_retries,
        audit_max_workers=template.audit_max_workers,
        audit_stale_after_days=template.audit_stale_after_days,
    )


def run_city_batch(
    cities: list[str],
    keywords: list[str],
    template_config: ScrapeConfig,
    data_dir: str = "data",
    export_hot_only: bool = False,
    captcha_wait_seconds: int = 120,
    error_wait_seconds: int = 300,
    logger: Optional[LogCallback] = None,
    sleeper: Optional[SleepCallback] = None,
) -> list[dict[str, object]]:
    log = logger or (lambda _message: None)
    sleep_fn = sleeper or time.sleep
    summaries: list[dict[str, object]] = []

    for city in cities:
        for keyword in keywords:
            job_config = build_city_keyword_config(
                city=city, keyword=keyword, template=template_config
            )
            session_name = f"{city} {keyword}"
            while True:
                log(f"Mulai job: {city} | {keyword}")
                try:
                    summary = run_headless_session(
                        config=job_config,
                        session_name=session_name,
                        data_dir=data_dir,
                        export_hot_only=export_hot_only,
                        logger=log,
                    )
                except Exception as exc:
                    log(
                        f"Error untuk {city} | {keyword}: {type(exc).__name__}: {exc}. "
                        f"Tunggu {error_wait_seconds} detik lalu lanjutkan resume."
                    )
                    sleep_fn(error_wait_seconds)
                    continue
                summary["city"] = city
                summary["keyword"] = keyword
                if summary["status"] != "blocked":
                    break
                log(
                    f"CAPTCHA/blocked untuk {city} | {keyword}. Tunggu "
                    f"{captcha_wait_seconds} detik lalu lanjutkan resume."
                )
                sleep_fn(captcha_wait_seconds)
            summaries.append(summary)
            log(f"Selesai job: {city} | {keyword} dengan status {summary['status']}")

    return summaries
