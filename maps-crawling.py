import argparse

from lead_finder.app import load_niche_payload
from lead_finder.defaults import DEFAULT_NICHE_PACKS_PATH
from lead_finder.headless import load_keywords_csv, load_locations_text, run_city_batch
from lead_finder.models import ScrapeConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl Google Maps per kombinasi kota dan kata kunci dari file input."
    )
    parser.add_argument(
        "locations",
        nargs="*",
        help="Subset kota yang ingin dijalankan. Jika kosong, semua kota di lokasi.txt dipakai.",
    )
    parser.add_argument(
        "--locations-file",
        default="lokasi.txt",
        help="File teks daftar lokasi, satu baris satu kota.",
    )
    parser.add_argument(
        "--keywords-csv",
        default="kata-kunci.csv",
        help="File CSV daftar kata kunci.",
    )
    parser.add_argument(
        "--niche-path",
        default=DEFAULT_NICHE_PACKS_PATH,
        help="Dipakai hanya untuk exclusion keyword scoring.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Folder output CSV final per kombinasi kota dan kata kunci.",
    )
    parser.add_argument(
        "--db-path",
        default="data/lead_finder.db",
        help="Path SQLite untuk penyimpanan lead dan skor.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=0,
        help="Batas total lead unik per kota. 0 berarti tanpa batas global.",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=0,
        help="Batas scroll per query. 0 berarti scroll sampai stagnan.",
    )
    parser.add_argument(
        "--stagnation-limit",
        type=int,
        default=5,
        help="Berhenti jika hasil tidak bertambah setelah beberapa putaran scroll.",
    )
    parser.add_argument("--scroll-pause", type=float, default=1.5, help="Jeda antar scroll.")
    parser.add_argument("--detail-pause", type=float, default=2.0, help="Jeda saat buka detail.")
    parser.add_argument(
        "--audit-timeout",
        type=float,
        default=8.0,
        help="Timeout audit website per lead.",
    )
    parser.add_argument(
        "--audit-workers",
        type=int,
        default=5,
        help="Jumlah worker paralel untuk audit website.",
    )
    parser.add_argument(
        "--audit-stale-days",
        type=int,
        default=14,
        help="Audit ulang website jika data audit lebih lama dari jumlah hari ini.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Jumlah retry saat audit website gagal.",
    )
    parser.add_argument(
        "--captcha-wait-seconds",
        type=int,
        default=120,
        help="Jeda saat kena CAPTCHA sebelum auto-resume lagi.",
    )
    parser.add_argument(
        "--error-wait-seconds",
        type=int,
        default=300,
        help="Jeda saat kena error runtime sebelum auto-retry job yang sama.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Lewati audit website setelah crawling.",
    )
    parser.add_argument(
        "--no-expand-locations",
        action="store_true",
        help="Matikan variasi otomatis pusat/utara/selatan/timur/barat.",
    )
    parser.add_argument(
        "--hot-only",
        action="store_true",
        help="Jika aktif, CSV final per job hanya berisi lead hot.",
    )
    return parser


def resolve_locations(cli_locations: list[str], locations_file: str) -> list[str]:
    if cli_locations:
        return [location.strip() for location in cli_locations if location.strip()]
    return load_locations_text(locations_file)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    locations = resolve_locations(args.locations, args.locations_file)
    keywords = load_keywords_csv(args.keywords_csv)
    if not locations:
        parser.error("Tidak ada lokasi untuk dijalankan.")
    if not keywords:
        parser.error("Tidak ada kata kunci untuk dijalankan.")

    niche_payload = load_niche_payload(args.niche_path)
    excluded_keywords = [str(item) for item in niche_payload.get("excluded_keywords") or []]
    template_config = ScrapeConfig(
        selected_niche_packs=["CSV Keywords"],
        niche_packs={"CSV Keywords": keywords},
        locations=[],
        excluded_keywords=excluded_keywords,
        db_path=args.db_path,
        max_scrolls=args.max_scrolls,
        max_results=args.max_results,
        scroll_pause=args.scroll_pause,
        detail_pause=args.detail_pause,
        stagnation_limit=args.stagnation_limit,
        headless=True,
        expand_locations=not args.no_expand_locations,
        audit_websites=not args.no_audit,
        request_timeout=args.audit_timeout,
        max_retries=args.max_retries,
        audit_max_workers=args.audit_workers,
        audit_stale_after_days=args.audit_stale_days,
    )

    print(f"Total kota: {len(locations)}")
    print(f"Total keyword: {len(keywords)}")
    print(f"Total job kota x keyword: {len(locations) * len(keywords)}")
    print(f"Mode export: {'hot-only' if args.hot_only else 'all'}")
    print(
        f"Mode hasil per job: {'tanpa batas global' if args.max_results == 0 else args.max_results}"
    )

    summaries = run_city_batch(
        cities=locations,
        keywords=keywords,
        template_config=template_config,
        data_dir=args.data_dir,
        export_hot_only=args.hot_only,
        captcha_wait_seconds=args.captcha_wait_seconds,
        error_wait_seconds=args.error_wait_seconds,
        logger=print,
    )

    success_count = sum(1 for item in summaries if item["status"] == "success")
    blocked_count = sum(1 for item in summaries if item["status"] == "blocked")
    exported_total = sum(int(item.get("total_exported") or 0) for item in summaries)

    print(f"Job selesai: {success_count}")
    print(f"Job masih blocked: {blocked_count}")
    print(f"Total baris diekspor: {exported_total}")
    return 0 if blocked_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
