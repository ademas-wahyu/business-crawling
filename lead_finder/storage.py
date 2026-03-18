import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_EXPORT_COLUMNS
from .models import LeadAudit, LeadFilters, RawPlaceRecord, ScrapeConfig
from .scoring import describe_opportunity
from .utils import ensure_csv_path, ensure_parent_dir, extract_domain, guess_city, now_utc_iso


class LeadDatabase:
    def __init__(self, db_path: str) -> None:
        self.path = ensure_parent_dir(db_path)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def __enter__(self) -> "LeadDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                total_found INTEGER NOT NULL DEFAULT 0,
                total_scored INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                maps_url TEXT NOT NULL UNIQUE,
                niche_pack TEXT NOT NULL DEFAULT '',
                nama_usaha TEXT NOT NULL DEFAULT '',
                kategori TEXT NOT NULL DEFAULT '',
                alamat TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                website_url TEXT NOT NULL DEFAULT '',
                website_domain TEXT NOT NULL DEFAULT '',
                rating REAL,
                review_count INTEGER NOT NULL DEFAULT 0,
                website_status TEXT NOT NULL DEFAULT 'unknown',
                audit_http_status INTEGER,
                audit_final_url TEXT NOT NULL DEFAULT '',
                audit_title TEXT NOT NULL DEFAULT '',
                audit_has_viewport INTEGER NOT NULL DEFAULT 0,
                audit_text_length INTEGER NOT NULL DEFAULT 0,
                lead_score INTEGER NOT NULL DEFAULT 0,
                lead_tier TEXT NOT NULL DEFAULT 'C',
                workflow_status TEXT NOT NULL DEFAULT 'new',
                notes TEXT NOT NULL DEFAULT '',
                last_contacted_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_audited_at TEXT,
                excluded_by_keyword INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS lead_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                search_query TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT '',
                UNIQUE(lead_id, run_id, keyword, search_query),
                FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )
        self.connection.commit()

    def start_run(self, config: ScrapeConfig) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO runs (started_at, status, config_json)
            VALUES (?, ?, ?)
            """,
            (now_utc_iso(), "running", json.dumps(config.to_dict(), ensure_ascii=False)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        total_found: int,
        total_scored: int,
        error_message: str = "",
    ) -> None:
        self.connection.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, total_found = ?, total_scored = ?, error_message = ?
            WHERE id = ?
            """,
            (now_utc_iso(), status, total_found, total_scored, error_message, run_id),
        )
        self.connection.commit()

    def upsert_lead(self, record: RawPlaceRecord, run_id: int) -> int:
        now = now_utc_iso()
        website_url = "" if record.website_url == "-" else record.website_url
        city = guess_city(record.alamat, record.city)
        website_domain = extract_domain(website_url)
        existing = self.connection.execute(
            "SELECT id FROM leads WHERE maps_url = ?",
            (record.maps_url,),
        ).fetchone()

        if existing:
            lead_id = int(existing["id"])
            self.connection.execute(
                """
                UPDATE leads
                SET niche_pack = ?, nama_usaha = ?, kategori = ?, alamat = ?, city = ?, phone = ?,
                    website_url = ?, website_domain = ?, rating = ?, review_count = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    record.niche_pack,
                    record.nama_usaha,
                    record.kategori,
                    record.alamat,
                    city,
                    "" if record.nomor_telepon == "-" else record.nomor_telepon,
                    website_url,
                    website_domain,
                    record.rating,
                    record.review_count or 0,
                    now,
                    lead_id,
                ),
            )
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO leads (
                    maps_url, niche_pack, nama_usaha, kategori, alamat, city, phone, website_url,
                    website_domain, rating, review_count, first_seen_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.maps_url,
                    record.niche_pack,
                    record.nama_usaha,
                    record.kategori,
                    record.alamat,
                    city,
                    "" if record.nomor_telepon == "-" else record.nomor_telepon,
                    website_url,
                    website_domain,
                    record.rating,
                    record.review_count or 0,
                    now,
                    now,
                ),
            )
            lead_id = int(cursor.lastrowid)

        self.connection.execute(
            """
            INSERT OR IGNORE INTO lead_sources (lead_id, run_id, keyword, search_query, city)
            VALUES (?, ?, ?, ?, ?)
            """,
            (lead_id, run_id, record.keyword, record.search_query, city),
        )
        self.connection.commit()
        return lead_id

    def get_lead(self, lead_id: int) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if row is None:
            raise KeyError(f"Lead {lead_id} tidak ditemukan")
        return dict(row)

    def get_leads_by_ids(self, lead_ids: list[int]) -> list[dict[str, Any]]:
        if not lead_ids:
            return []
        placeholders = ",".join("?" for _ in lead_ids)
        rows = self.connection.execute(
            f"SELECT * FROM leads WHERE id IN ({placeholders})",
            tuple(lead_ids),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_audit(self, lead_id: int, audit: LeadAudit) -> None:
        self.connection.execute(
            """
            UPDATE leads
            SET website_status = ?, audit_http_status = ?, audit_final_url = ?, audit_title = ?,
                audit_has_viewport = ?, audit_text_length = ?, website_domain = ?, last_audited_at = ?
            WHERE id = ?
            """,
            (
                audit.website_status,
                audit.http_status,
                audit.final_url,
                audit.title,
                int(audit.has_viewport),
                audit.text_length,
                audit.final_domain,
                now_utc_iso(),
                lead_id,
            ),
        )
        self.connection.commit()

    def save_score(self, lead_id: int, score: int, tier: str, excluded: bool) -> None:
        self.connection.execute(
            """
            UPDATE leads
            SET lead_score = ?, lead_tier = ?, excluded_by_keyword = ?
            WHERE id = ?
            """,
            (score, tier, int(excluded), lead_id),
        )
        self.connection.commit()

    def list_filter_values(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for field in ("city", "niche_pack", "workflow_status", "lead_tier", "website_status"):
            rows = self.connection.execute(
                f"SELECT DISTINCT {field} AS value FROM leads WHERE {field} != '' ORDER BY {field}"
            ).fetchall()
            result[field] = [str(row["value"]) for row in rows if row["value"] is not None]
        return result

    def list_leads(self, filters: LeadFilters) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        values: list[Any] = []

        if filters.city:
            where_clauses.append("city = ?")
            values.append(filters.city)
        if filters.niche_pack:
            where_clauses.append("niche_pack = ?")
            values.append(filters.niche_pack)
        if filters.workflow_status:
            where_clauses.append("workflow_status = ?")
            values.append(filters.workflow_status)
        if filters.lead_tier:
            where_clauses.append("lead_tier = ?")
            values.append(filters.lead_tier)
        if filters.website_status:
            where_clauses.append("website_status = ?")
            values.append(filters.website_status)
        if filters.text_query:
            where_clauses.append(
                "(nama_usaha LIKE ? OR kategori LIKE ? OR alamat LIKE ? OR city LIKE ?)"
            )
            values.extend([f"%{filters.text_query}%"] * 4)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        rows = self.connection.execute(
            f"""
            SELECT *
            FROM leads
            {where_sql}
            ORDER BY lead_score DESC, last_seen_at DESC, nama_usaha ASC
            """,
            tuple(values),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_lead_workflow(
        self,
        lead_id: int,
        workflow_status: str,
        notes: str,
        mark_contacted_now: bool = False,
    ) -> None:
        last_contacted_at = now_utc_iso() if mark_contacted_now else None
        if mark_contacted_now:
            self.connection.execute(
                """
                UPDATE leads
                SET workflow_status = ?, notes = ?, last_contacted_at = ?
                WHERE id = ?
                """,
                (workflow_status, notes.strip(), last_contacted_at, lead_id),
            )
        else:
            self.connection.execute(
                """
                UPDATE leads
                SET workflow_status = ?, notes = ?
                WHERE id = ?
                """,
                (workflow_status, notes.strip(), lead_id),
            )
        self.connection.commit()

    def export_leads(
        self,
        filters: LeadFilters,
        output_path: str,
        opportunity_fit_filter: str = "",
    ) -> tuple[Path, int]:
        rows = self.list_leads(filters)
        return self._export_rows(rows, output_path, opportunity_fit_filter)

    def export_leads_by_ids(
        self,
        lead_ids: list[int],
        output_path: str,
        opportunity_fit_filter: str = "",
    ) -> tuple[Path, int]:
        unique_ids = list(dict.fromkeys(lead_ids))
        rows = self.get_leads_by_ids(unique_ids)
        rows.sort(
            key=lambda row: (
                -int(row.get("lead_score") or 0),
                str(row.get("nama_usaha") or "").lower(),
            )
        )
        return self._export_rows(rows, output_path, opportunity_fit_filter)

    def _export_rows(
        self,
        rows: list[dict[str, Any]],
        output_path: str,
        opportunity_fit_filter: str = "",
    ) -> tuple[Path, int]:
        csv_rows: list[dict[str, Any]] = []
        for row in rows:
            opportunity_fit, opportunity_reason = describe_opportunity(row)
            if opportunity_fit_filter and opportunity_fit != opportunity_fit_filter:
                continue
            csv_rows.append(
                {
                    "opportunity_fit": opportunity_fit,
                    "opportunity_reason": opportunity_reason,
                    "lead_tier": row["lead_tier"],
                    "lead_score": row["lead_score"],
                    "nama_usaha": row["nama_usaha"],
                    "kategori": row["kategori"],
                    "alamat": row["alamat"],
                    "city": row["city"],
                    "website_url": row["website_url"] or "-",
                    "website_status": row["website_status"],
                    "audit_http_status": row["audit_http_status"],
                    "nomor_telepon": row["phone"] or "-",
                    "rating": row["rating"],
                    "review_count": row["review_count"],
                    "workflow_status": row["workflow_status"],
                    "notes": row["notes"],
                    "maps_url": row["maps_url"],
                }
            )

        csv_path = ensure_csv_path(output_path)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=DEFAULT_EXPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(csv_rows)
        return csv_path, len(csv_rows)
