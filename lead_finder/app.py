import json
from pathlib import Path
from typing import Callable, Optional

from .audit import WebsiteAuditor
from .defaults import DEFAULT_NICHE_PACKS_PATH, default_niche_payload
from .models import LeadAudit, LeadFilters, RawPlaceRecord, ScrapeConfig
from .scoring import calculate_lead_score
from .scraper import GoogleMapsScraper
from .storage import LeadDatabase
from .utils import days_ago, parse_iso_datetime

LogCallback = Callable[[str], None]


def load_niche_payload(path: str = DEFAULT_NICHE_PACKS_PATH) -> dict[str, object]:
    payload_path = Path(path)
    if not payload_path.is_absolute():
        payload_path = Path.cwd() / payload_path
    if not payload_path.exists():
        save_niche_payload(default_niche_payload(), str(payload_path))
        return default_niche_payload()

    with payload_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    packs = raw.get("packs") or {}
    excluded_keywords = raw.get("excluded_keywords") or []
    if not isinstance(packs, dict) or not isinstance(excluded_keywords, list):
        return default_niche_payload()

    normalized_packs: dict[str, list[str]] = {}
    for pack_name, keywords in packs.items():
        if not isinstance(pack_name, str) or not isinstance(keywords, list):
            continue
        normalized_packs[pack_name] = [str(item).strip() for item in keywords if str(item).strip()]

    return {
        "packs": normalized_packs or default_niche_payload()["packs"],
        "excluded_keywords": [str(item).strip() for item in excluded_keywords if str(item).strip()],
    }


def save_niche_payload(payload: dict[str, object], path: str = DEFAULT_NICHE_PACKS_PATH) -> Path:
    payload_path = Path(path)
    if not payload_path.is_absolute():
        payload_path = Path.cwd() / payload_path
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    with payload_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return payload_path


def _lead_needs_audit(lead: dict[str, object], stale_after_days: int) -> bool:
    website_url = str(lead.get("website_url") or "")
    if not website_url:
        return False

    last_audited_at = str(lead.get("last_audited_at") or "")
    if not last_audited_at:
        return True

    parsed = parse_iso_datetime(last_audited_at)
    if parsed is None:
        return True
    return parsed < days_ago(stale_after_days)


class LeadFinderService:
    def __init__(self, logger: Optional[LogCallback] = None) -> None:
        self.log = logger or (lambda _message: None)

    def run_search(self, config: ScrapeConfig) -> dict[str, object]:
        scraper = GoogleMapsScraper(config=config, logger=self.log)
        raw_records = scraper.run()
        return self.process_raw_records(config, raw_records)

    def process_raw_records(
        self,
        config: ScrapeConfig,
        raw_records: list[RawPlaceRecord],
    ) -> dict[str, object]:
        total_found = len(raw_records)
        total_scored = 0

        with LeadDatabase(config.db_path) as database:
            run_id = database.start_run(config)
            try:
                lead_ids: list[int] = []
                for record in raw_records:
                    lead_ids.append(database.upsert_lead(record, run_id))

                unique_lead_ids = list(dict.fromkeys(lead_ids))
                leads = database.get_leads_by_ids(unique_lead_ids)
                audits: dict[int, LeadAudit] = {}

                for lead in leads:
                    website_url = str(lead.get("website_url") or "")
                    if not website_url:
                        audits[int(lead["id"])] = LeadAudit(website_status="none")

                if config.audit_websites:
                    due_for_audit = [
                        lead
                        for lead in leads
                        if int(lead["id"]) not in audits
                        and _lead_needs_audit(lead, config.audit_stale_after_days)
                    ]
                    if due_for_audit:
                        self.log(f"Audit website untuk {len(due_for_audit)} lead...")
                        auditor = WebsiteAuditor(
                            timeout=config.request_timeout,
                            max_retries=config.max_retries,
                            max_workers=config.audit_max_workers,
                            logger=self.log,
                        )
                        audits.update(auditor.audit_many(due_for_audit))

                for lead_id, audit in audits.items():
                    database.save_audit(lead_id, audit)

                for lead_id in unique_lead_ids:
                    current = database.get_lead(lead_id)
                    score, tier, excluded = calculate_lead_score(
                        current,
                        config.excluded_keywords,
                    )
                    database.save_score(lead_id, score, tier, excluded)
                    total_scored += 1

                database.finish_run(run_id, "success", total_found, total_scored)
                return {
                    "run_id": run_id,
                    "total_found": total_found,
                    "total_scored": total_scored,
                    "audited": len(audits),
                    "lead_ids": unique_lead_ids,
                }
            except Exception as exc:
                database.finish_run(run_id, "error", total_found, total_scored, str(exc))
                raise

    def list_leads(self, db_path: str, filters: LeadFilters) -> list[dict[str, object]]:
        with LeadDatabase(db_path) as database:
            return database.list_leads(filters)

    def list_filter_values(self, db_path: str) -> dict[str, list[str]]:
        with LeadDatabase(db_path) as database:
            return database.list_filter_values()

    def update_lead_workflow(
        self,
        db_path: str,
        lead_id: int,
        workflow_status: str,
        notes: str,
        mark_contacted_now: bool = False,
    ) -> None:
        with LeadDatabase(db_path) as database:
            database.update_lead_workflow(lead_id, workflow_status, notes, mark_contacted_now)

    def export_leads(
        self,
        db_path: str,
        filters: LeadFilters,
        output_path: str,
        opportunity_fit_filter: str = "",
    ) -> tuple[Path, int]:
        with LeadDatabase(db_path) as database:
            return database.export_leads(filters, output_path, opportunity_fit_filter)

    def export_leads_by_ids(
        self,
        db_path: str,
        lead_ids: list[int],
        output_path: str,
        opportunity_fit_filter: str = "",
    ) -> tuple[Path, int]:
        with LeadDatabase(db_path) as database:
            return database.export_leads_by_ids(lead_ids, output_path, opportunity_fit_filter)
