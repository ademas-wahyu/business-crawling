import csv
import tempfile
import unittest
from pathlib import Path

import lead_finder.headless as headless_module
import lead_finder.scraper as scraper_module
from lead_finder.audit import classify_page_result
from lead_finder.headless import (
    append_raw_record,
    load_checkpoint,
    load_keywords_csv,
    load_locations_text,
    load_raw_records,
    run_city_batch,
    save_checkpoint,
)
from lead_finder.models import RawPlaceRecord, ScrapeConfig
from lead_finder.scoring import calculate_lead_score, describe_opportunity
from lead_finder.scraper import CaptchaDetectedError, GoogleMapsScraper
from lead_finder.storage import LeadDatabase


class QueryBuilderTests(unittest.TestCase):
    def test_query_builder_expands_locations(self) -> None:
        config = ScrapeConfig(
            selected_niche_packs=["Test"],
            niche_packs={"Test": ["klinik"]},
            locations=["Bandung"],
            expand_locations=True,
        )
        scraper = GoogleMapsScraper(config=config)
        queries = scraper.build_queries()

        self.assertEqual(len(queries), 12)
        self.assertIn("klinik di Bandung", [item.query for item in queries])
        self.assertIn("klinik Bandung utara", [item.query for item in queries])


class AuditClassificationTests(unittest.TestCase):
    def test_social_only_classification(self) -> None:
        audit = classify_page_result(
            input_url="https://instagram.com/bisnisbagus",
            final_url="https://instagram.com/bisnisbagus",
            status_code=200,
            html="",
        )
        self.assertEqual(audit.website_status, "social_only")

    def test_error_classification(self) -> None:
        audit = classify_page_result(
            input_url="https://contoh.invalid",
            final_url="https://contoh.invalid",
            status_code=404,
            html="",
            error_message="HTTP 404",
        )
        self.assertEqual(audit.website_status, "error")

    def test_owned_domain_weak_and_ok(self) -> None:
        weak = classify_page_result(
            input_url="https://bisnislemah.com",
            final_url="https://bisnislemah.com",
            status_code=200,
            html="<html><head><title>Halo</title></head><body>Halo</body></html>",
        )
        ok = classify_page_result(
            input_url="https://bisnisbagus.com",
            final_url="https://bisnisbagus.com",
            status_code=200,
            html=(
                "<html><head><title>Bisnis Bagus</title><meta name='viewport' "
                "content='width=device-width, initial-scale=1'></head><body>"
                + ("Konten " * 60)
                + "</body></html>"
            ),
        )
        self.assertEqual(weak.website_status, "owned_domain_weak")
        self.assertEqual(ok.website_status, "owned_domain_ok")


class ScoringTests(unittest.TestCase):
    def test_none_website_with_good_rating_is_hot_tier_a(self) -> None:
        lead = {
            "website_status": "none",
            "phone": "08123456",
            "niche_pack": "Kuliner",
            "review_count": 44,
            "nama_usaha": "Cafe Mawar",
            "rating": 4.6,
        }
        score, tier, excluded = calculate_lead_score(lead, ["indomaret"])
        fit, reason = describe_opportunity(lead)
        self.assertGreaterEqual(score, 70)
        self.assertEqual(tier, "A")
        self.assertFalse(excluded)
        self.assertEqual(fit, "hot")
        self.assertIn("website belum dicantumkan", reason)
        self.assertIn("rating 4.6", reason)

    def test_excluded_keyword_penalty(self) -> None:
        lead = {
            "website_status": "social_only",
            "phone": "08123456",
            "niche_pack": "Kuliner",
            "review_count": 20,
            "nama_usaha": "Starbucks Braga",
            "rating": 4.5,
        }
        score, tier, excluded = calculate_lead_score(lead, ["starbucks"])
        self.assertTrue(excluded)
        self.assertLess(score, 45)
        self.assertEqual(tier, "C")

    def test_error_404_with_good_reviews_is_hot(self) -> None:
        lead = {
            "website_status": "error",
            "phone": "08123456",
            "niche_pack": "Beauty",
            "review_count": 18,
            "nama_usaha": "Salon Melati",
            "rating": 4.7,
        }
        score, tier, excluded = calculate_lead_score(lead, [])
        fit, reason = describe_opportunity(lead)
        self.assertFalse(excluded)
        self.assertEqual(tier, "A")
        self.assertEqual(fit, "hot")
        self.assertIn("website mati/error", reason)


class StorageTests(unittest.TestCase):
    def test_upsert_keeps_single_lead(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "lead.db"
            config = ScrapeConfig(
                selected_niche_packs=["Test"],
                niche_packs={"Test": ["klinik"]},
                locations=["Bandung"],
                db_path=str(db_path),
            )
            first = RawPlaceRecord(
                niche_pack="Test",
                keyword="klinik",
                search_query="klinik Bandung",
                nama_usaha="Klinik Sehat",
                kategori="Klinik",
                alamat="Jl. Test, Bandung",
                city="Bandung",
                website_url="https://kliniksehat.test",
                nomor_telepon="0811",
                maps_url="https://maps.google.com/place/abc",
                rating=4.5,
                review_count=10,
            )
            second = RawPlaceRecord(
                niche_pack="Test",
                keyword="klinik",
                search_query="klinik di Bandung",
                nama_usaha="Klinik Sehat Update",
                kategori="Klinik",
                alamat="Jl. Test, Bandung",
                city="Bandung",
                website_url="https://kliniksehat.test",
                nomor_telepon="0811",
                maps_url="https://maps.google.com/place/abc",
                rating=4.7,
                review_count=12,
            )

            with LeadDatabase(str(db_path)) as database:
                run_one = database.start_run(config)
                lead_id_one = database.upsert_lead(first, run_one)
                database.finish_run(run_one, "success", 1, 1)

                run_two = database.start_run(config)
                lead_id_two = database.upsert_lead(second, run_two)
                database.finish_run(run_two, "success", 1, 1)

                rows = database.list_leads(configured_filters())
                source_count = database.connection.execute(
                    "SELECT COUNT(*) AS total FROM lead_sources WHERE lead_id = ?",
                    (lead_id_one,),
                ).fetchone()["total"]

            self.assertEqual(lead_id_one, lead_id_two)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["nama_usaha"], "Klinik Sehat Update")
            self.assertEqual(source_count, 2)

    def test_export_leads_by_ids_can_filter_hot_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "lead.db"
            export_path = Path(tmpdir) / "data" / "hot.csv"
            config = ScrapeConfig(
                selected_niche_packs=["Test"],
                niche_packs={"Test": ["klinik"]},
                locations=["Bandung"],
                db_path=str(db_path),
                audit_websites=False,
            )
            hot_record = RawPlaceRecord(
                niche_pack="Test",
                keyword="klinik",
                search_query="klinik Bandung",
                nama_usaha="Klinik Panen Review",
                kategori="Klinik",
                alamat="Jl. Test, Bandung",
                city="Bandung",
                website_url="-",
                nomor_telepon="0811",
                maps_url="https://maps.google.com/place/hot",
                rating=4.7,
                review_count=50,
            )
            low_record = RawPlaceRecord(
                niche_pack="Test",
                keyword="klinik",
                search_query="klinik Bandung",
                nama_usaha="Klinik Website Bagus",
                kategori="Klinik",
                alamat="Jl. Test 2, Bandung",
                city="Bandung",
                website_url="https://klinikbagus.test",
                nomor_telepon="0812",
                maps_url="https://maps.google.com/place/low",
                rating=4.1,
                review_count=4,
            )

            from lead_finder.app import LeadFinderService

            service = LeadFinderService()
            summary = service.process_raw_records(config, [hot_record, low_record])
            raw_lead_ids = summary["lead_ids"]
            lead_ids = raw_lead_ids if isinstance(raw_lead_ids, list) else []
            csv_file, exported_count = service.export_leads_by_ids(
                str(db_path),
                lead_ids,
                str(export_path),
                opportunity_fit_filter="hot",
            )

            with csv_file.open("r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(exported_count, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["nama_usaha"], "Klinik Panen Review")
            self.assertEqual(rows[0]["opportunity_fit"], "hot")
            self.assertEqual(rows[0]["website_url"], "-")


class HeadlessStorageTests(unittest.TestCase):
    def test_raw_csv_and_checkpoint_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw" / "session.csv"
            checkpoint_path = Path(tmpdir) / "raw" / "session.checkpoint.json"
            record = RawPlaceRecord(
                niche_pack="Test",
                keyword="klinik",
                search_query="klinik Bandung",
                nama_usaha="Klinik Mawar",
                kategori="Klinik",
                alamat="Jl. Mawar, Bandung",
                city="Bandung",
                website_url="https://klinikmawar.test",
                nomor_telepon="08123",
                maps_url="https://maps.google.com/place/mawar",
                rating=4.8,
                review_count=22,
            )

            append_raw_record(raw_path, record)
            loaded_records = load_raw_records(raw_path)
            self.assertEqual(len(loaded_records), 1)
            self.assertEqual(loaded_records[0].nama_usaha, "Klinik Mawar")

            from lead_finder.models import (
                DiscoveredPlace,
                ScrapeCheckpoint,
                SearchQuery,
            )

            checkpoint = ScrapeCheckpoint(
                session_name="session",
                query_cursor=3,
                discovered_places=[
                    DiscoveredPlace(
                        maps_url=record.maps_url,
                        search_query=SearchQuery(
                            niche_pack="Test",
                            keyword="klinik",
                            base_location="Bandung",
                            location_variant="Bandung",
                            query="klinik Bandung",
                        ),
                    )
                ],
                scraped_urls=[record.maps_url],
                status="blocked",
                blocked_reason="captcha",
            )
            save_checkpoint(checkpoint_path, checkpoint)
            loaded_checkpoint = load_checkpoint(checkpoint_path)
            self.assertIsNotNone(loaded_checkpoint)

            checkpoint_result = loaded_checkpoint
            assert checkpoint_result is not None

            self.assertEqual(checkpoint_result.session_name, "session")
            self.assertEqual(checkpoint_result.scraped_urls, [record.maps_url])
            self.assertEqual(checkpoint_result.status, "blocked")

    def test_load_keywords_and_locations_from_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            keywords_path = Path(tmpdir) / "kata-kunci.csv"
            locations_path = Path(tmpdir) / "lokasi.txt"
            keywords_path.write_text(
                "Kata_Kunci\nKlinik\nSalon\nKlinik\n", encoding="utf-8"
            )
            locations_path.write_text("Bandung\nJakarta\nBandung\n", encoding="utf-8")

            self.assertEqual(load_keywords_csv(keywords_path), ["Klinik", "Salon"])
            self.assertEqual(
                load_locations_text(locations_path), ["Bandung", "Jakarta"]
            )


class BatchRunnerTests(unittest.TestCase):
    def test_run_city_batch_retries_after_blocked_per_city_keyword(self) -> None:
        original_runner = headless_module.run_headless_session
        self.addCleanup(
            setattr, headless_module, "run_headless_session", original_runner
        )

        calls: list[str] = []
        sleeps: list[float] = []

        def fake_runner(config, session_name, data_dir, export_hot_only, logger):
            calls.append(session_name)
            if session_name == "Bandung Klinik" and calls.count(session_name) == 1:
                return {
                    "status": "blocked",
                    "message": "captcha",
                    "session_name": session_name,
                    "processed_csv_path": "data/bandung-klinik.csv",
                    "checkpoint_path": ".state/bandung-klinik.checkpoint.json",
                    "db_path": "data/lead_finder.db",
                    "total_raw": 10,
                    "total_processed": 10,
                    "total_exported": 10,
                    "total_audited": 0,
                    "run_id": 1,
                    "export_hot_only": export_hot_only,
                }
            return {
                "status": "success",
                "message": "",
                "session_name": session_name,
                "processed_csv_path": f"data/{session_name}.csv",
                "checkpoint_path": f".state/{session_name}.checkpoint.json",
                "db_path": "data/lead_finder.db",
                "total_raw": 12,
                "total_processed": 12,
                "total_exported": 12,
                "total_audited": 0,
                "run_id": 2,
                "export_hot_only": export_hot_only,
            }

        headless_module.run_headless_session = fake_runner

        template = ScrapeConfig(
            selected_niche_packs=["CSV Keywords"],
            niche_packs={"CSV Keywords": ["Klinik", "Salon"]},
            locations=[],
        )
        summaries = run_city_batch(
            cities=["Bandung"],
            keywords=["Klinik", "Salon"],
            template_config=template,
            data_dir="data",
            captcha_wait_seconds=120,
            logger=lambda _message: None,
            sleeper=lambda seconds: sleeps.append(seconds),
        )

        self.assertEqual(calls, ["Bandung Klinik", "Bandung Klinik", "Bandung Salon"])
        self.assertEqual(sleeps, [120])
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["status"], "success")
        self.assertEqual(summaries[0]["city"], "Bandung")
        self.assertEqual(summaries[0]["keyword"], "Klinik")
        self.assertEqual(summaries[1]["keyword"], "Salon")

    def test_run_city_batch_retries_after_unexpected_error(self) -> None:
        original_runner = headless_module.run_headless_session
        self.addCleanup(
            setattr, headless_module, "run_headless_session", original_runner
        )

        calls: list[str] = []
        sleeps: list[float] = []

        def fake_runner(config, session_name, data_dir, export_hot_only, logger):
            calls.append(session_name)
            if calls.count(session_name) == 1:
                raise RuntimeError("chrome crashed")
            return {
                "status": "success",
                "message": "",
                "session_name": session_name,
                "processed_csv_path": f"data/{session_name}.csv",
                "checkpoint_path": f".state/{session_name}.checkpoint.json",
                "db_path": "data/lead_finder.db",
                "total_raw": 12,
                "total_processed": 12,
                "total_exported": 12,
                "total_audited": 0,
                "run_id": 2,
                "export_hot_only": export_hot_only,
            }

        headless_module.run_headless_session = fake_runner

        template = ScrapeConfig(
            selected_niche_packs=["CSV Keywords"],
            niche_packs={"CSV Keywords": ["Klinik"]},
            locations=[],
        )
        summaries = run_city_batch(
            cities=["Bandung"],
            keywords=["Klinik"],
            template_config=template,
            data_dir="data",
            captcha_wait_seconds=120,
            error_wait_seconds=45,
            logger=lambda _message: None,
            sleeper=lambda seconds: sleeps.append(seconds),
        )

        self.assertEqual(calls, ["Bandung Klinik", "Bandung Klinik"])
        self.assertEqual(sleeps, [45])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["status"], "success")
        self.assertEqual(summaries[0]["city"], "Bandung")
        self.assertEqual(summaries[0]["keyword"], "Klinik")


class ResumableScraperTests(unittest.TestCase):
    def test_resume_after_captcha_skips_scraped_url(self) -> None:
        original_webdriver = scraper_module.webdriver
        scraper_module.webdriver = object()
        self.addCleanup(setattr, scraper_module, "webdriver", original_webdriver)

        config = ScrapeConfig(
            selected_niche_packs=["Test"],
            niche_packs={"Test": ["klinik"]},
            locations=["Bandung"],
            max_results=10,
        )

        from lead_finder.models import ScrapeCheckpoint, SearchQuery

        class FakeDriver:
            def quit(self) -> None:
                return None

        class FakeScraper(GoogleMapsScraper):
            shared_detail_attempts: dict[str, int] = {}

            def __init__(self, config: ScrapeConfig) -> None:
                super().__init__(config=config)

            def _build_driver(self):
                return FakeDriver()

            def build_queries(self) -> list[SearchQuery]:
                return [
                    SearchQuery("Test", "klinik", "Bandung", "Bandung", "query-1"),
                    SearchQuery("Test", "klinik", "Bandung", "Bandung", "query-2"),
                ]

            def _collect_place_urls(self, query: str, per_query_limit):
                if query == "query-1":
                    return ["https://maps.google.com/place/one"]
                return ["https://maps.google.com/place/two"]

            def _scrape_place_detail(
                self,
                url: str,
                search_query: SearchQuery,
                position: int,
                total: int,
            ) -> RawPlaceRecord:
                attempt = self.shared_detail_attempts.get(url, 0)
                self.shared_detail_attempts[url] = attempt + 1
                if url.endswith("/two") and attempt == 0:
                    raise CaptchaDetectedError("captcha")
                return RawPlaceRecord(
                    niche_pack=search_query.niche_pack,
                    keyword=search_query.keyword,
                    search_query=search_query.query,
                    nama_usaha=f"Lead {position}",
                    kategori="Klinik",
                    alamat="Jl. Test, Bandung",
                    city="Bandung",
                    website_url="-",
                    nomor_telepon="-",
                    maps_url=url,
                    rating=4.5,
                    review_count=10,
                )

        scraper = FakeScraper(config=config)
        checkpoint = ScrapeCheckpoint(session_name="resume-test")
        saved_states: list[ScrapeCheckpoint] = []
        saved_records: list[RawPlaceRecord] = []

        with self.assertRaises(CaptchaDetectedError):
            scraper.run_resumable(
                checkpoint=checkpoint,
                existing_records=[],
                on_checkpoint=lambda state: saved_states.append(
                    ScrapeCheckpoint.from_dict(state.to_dict())
                ),
                on_record=lambda record: saved_records.append(record),
            )

        self.assertEqual(len(saved_records), 1)
        self.assertTrue(saved_states)

        resumed_scraper = FakeScraper(config=config)
        resumed_records = resumed_scraper.run_resumable(
            checkpoint=saved_states[-1],
            existing_records=saved_records,
        )

        self.assertEqual(len(resumed_records), 2)
        self.assertEqual(
            [record.maps_url for record in resumed_records],
            [
                "https://maps.google.com/place/one",
                "https://maps.google.com/place/two",
            ],
        )


def configured_filters():
    from lead_finder.models import LeadFilters

    return LeadFilters()


if __name__ == "__main__":
    unittest.main()
