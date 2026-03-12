import tempfile
import unittest
from pathlib import Path

from lead_finder.audit import classify_page_result
from lead_finder.models import RawPlaceRecord, ScrapeConfig
from lead_finder.scoring import calculate_lead_score
from lead_finder.scraper import GoogleMapsScraper
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
    def test_none_website_scores_tier_a(self) -> None:
        lead = {
            "website_status": "none",
            "phone": "08123456",
            "niche_pack": "Kuliner",
            "review_count": 15,
            "nama_usaha": "Cafe Mawar",
        }
        score, tier, excluded = calculate_lead_score(lead, ["indomaret"])
        self.assertEqual(score, 60)
        self.assertEqual(tier, "A")
        self.assertFalse(excluded)

    def test_excluded_keyword_penalty(self) -> None:
        lead = {
            "website_status": "social_only",
            "phone": "08123456",
            "niche_pack": "Kuliner",
            "review_count": 20,
            "nama_usaha": "Starbucks Braga",
        }
        score, tier, excluded = calculate_lead_score(lead, ["starbucks"])
        self.assertTrue(excluded)
        self.assertEqual(score, 30)
        self.assertEqual(tier, "C")


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


def configured_filters():
    from lead_finder.models import LeadFilters

    return LeadFilters()


if __name__ == "__main__":
    unittest.main()
