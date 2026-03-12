import re
import time
from collections import OrderedDict
from typing import Callable, Optional
from urllib.parse import quote_plus

from .models import RawPlaceRecord, ScrapeConfig, SearchQuery
from .utils import normalize_maps_url

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ModuleNotFoundError:
    webdriver = None
    TimeoutException = WebDriverException = Exception
    By = EC = WebDriverWait = None

LogCallback = Callable[[str], None]


class GoogleMapsScraper:
    def __init__(self, config: ScrapeConfig, logger: Optional[LogCallback] = None) -> None:
        self.config = config
        self.log = logger or (lambda _message: None)
        self.driver = None

    def run(self) -> list[RawPlaceRecord]:
        if webdriver is None:
            raise RuntimeError("Paket selenium belum terpasang. Jalankan: pip install selenium")

        queries = self.build_queries()
        if not queries:
            raise ValueError("Pilih minimal satu niche pack dan isi minimal satu wilayah.")

        self.driver = self._build_driver()
        place_map: OrderedDict[str, SearchQuery] = OrderedDict()
        try:
            self.log(f"Menjalankan {len(queries)} query Google Maps...")
            for index, search_query in enumerate(queries, start=1):
                if self._max_results_reached(place_map):
                    break
                remaining = self._remaining_slots(place_map)
                self.log(f"[{index}/{len(queries)}] Cari: {search_query.query}")
                urls = self._collect_place_urls(search_query.query, remaining)
                for url in urls:
                    normalized = normalize_maps_url(url)
                    if normalized not in place_map:
                        place_map[normalized] = search_query
                self.log(f"Total lead unik sementara: {len(place_map)}")

            raw_records: list[RawPlaceRecord] = []
            total = len(place_map)
            for index, (url, search_query) in enumerate(place_map.items(), start=1):
                raw_records.append(self._scrape_place_detail(url, search_query, index, total))
            return raw_records
        finally:
            if self.driver is not None:
                self.driver.quit()

    def build_queries(self) -> list[SearchQuery]:
        location_pairs = self._expand_locations(self.config.locations)
        selected_packs = self.config.selected_niche_packs or list(self.config.niche_packs.keys())
        queries: OrderedDict[str, SearchQuery] = OrderedDict()

        for niche_pack in selected_packs:
            keywords = self.config.niche_packs.get(niche_pack, [])
            for keyword in keywords:
                for base_location, location_variant in location_pairs:
                    for query in (f"{keyword} di {location_variant}", f"{keyword} {location_variant}"):
                        queries.setdefault(
                            query,
                            SearchQuery(
                                niche_pack=niche_pack,
                                keyword=keyword,
                                base_location=base_location,
                                location_variant=location_variant,
                                query=query,
                            ),
                        )
        return list(queries.values())

    def _build_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--lang=id-ID")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        if self.config.headless:
            options.add_argument("--headless=new")

        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(45)
            driver.implicitly_wait(2)
            return driver
        except WebDriverException as exc:
            raise RuntimeError(
                "Chrome/Chromedriver tidak siap. Pastikan Google Chrome terpasang."
            ) from exc

    def _expand_locations(self, locations: list[str]) -> list[tuple[str, str]]:
        expanded: OrderedDict[tuple[str, str], None] = OrderedDict()
        suffixes = ["pusat", "utara", "selatan", "timur", "barat"]
        for location in locations:
            if not location:
                continue
            expanded[(location, location)] = None
            if not self.config.expand_locations:
                continue
            for suffix in suffixes:
                expanded[(location, f"{location} {suffix}")] = None
        return list(expanded.keys())

    def _collect_place_urls(self, query: str, per_query_limit: Optional[int]) -> list[str]:
        search_url = f"https://www.google.com/maps/search/{quote_plus(query)}"
        self.driver.get(search_url)
        time.sleep(2)
        self._try_dismiss_cookie_popup()

        try:
            feed = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="feed"]'))
            )
        except TimeoutException:
            current_url = normalize_maps_url(self.driver.current_url)
            if "/maps/place/" in current_url:
                return [current_url]
            raise RuntimeError(
                "Panel hasil Google Maps tidak muncul. Bisa jadi ada CAPTCHA atau layout berubah."
            )

        collected: OrderedDict[str, None] = OrderedDict()
        stagnant_rounds = 0
        last_count = -1
        scroll_count = 0

        while True:
            for element in self.driver.find_elements(By.CSS_SELECTOR, "a.hfpxzc"):
                url = element.get_attribute("href")
                if url:
                    collected[normalize_maps_url(url)] = None

            current_count = len(collected)
            if per_query_limit and current_count >= per_query_limit:
                break

            if current_count == last_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                last_count = current_count

            if stagnant_rounds >= self.config.stagnation_limit:
                break
            if self.config.max_scrolls > 0 and scroll_count >= self.config.max_scrolls:
                break

            self.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", feed)
            scroll_count += 1
            time.sleep(self.config.scroll_pause)

        return list(collected.keys())

    def _try_dismiss_cookie_popup(self) -> None:
        selectors = [
            "button[aria-label='Accept all']",
            "button[aria-label='Terima semua']",
            "button[aria-label='Reject all']",
            "button[aria-label='Tolak semua']",
        ]
        for selector in selectors:
            try:
                self.driver.find_element(By.CSS_SELECTOR, selector).click()
                time.sleep(1)
                return
            except Exception:
                continue

    def _scrape_place_detail(
        self,
        url: str,
        search_query: SearchQuery,
        position: int,
        total: int,
    ) -> RawPlaceRecord:
        self.driver.get(url)
        time.sleep(self.config.detail_pause)

        name = self._find_text(["h1.DUwDvf", "h1.fontHeadlineLarge"], wait_seconds=10)
        category = self._find_text(
            ["button[jsaction='pane.rating.category']", "button.DkEaL", "button[jsaction*='category']"]
        )
        address = self._find_text(
            [
                "button[data-item-id='address']",
                "button[aria-label^='Address']",
                "button[aria-label^='Alamat']",
            ]
        )
        website = self._find_attribute(["a[data-item-id='authority']"], "href")
        phone = self._find_text(
            ["button[data-item-id^='phone:tel:']", "button[data-item-id='phone']"]
        )
        rating, review_count = self._extract_rating_and_reviews()

        self.log(f"[{position}/{total}] Lead: {name}")
        return RawPlaceRecord(
            niche_pack=search_query.niche_pack,
            keyword=search_query.keyword,
            search_query=search_query.query,
            nama_usaha=name,
            kategori=category,
            alamat=address,
            city=search_query.base_location,
            website_url=website,
            nomor_telepon=phone,
            maps_url=normalize_maps_url(self.driver.current_url),
            rating=rating,
            review_count=review_count,
        )

    def _extract_rating_and_reviews(self) -> tuple[float | None, int | None]:
        visible_chunks = []
        selectors = [
            "div.F7nice",
            "span[aria-label*='bintang']",
            "span[aria-label*='stars']",
        ]
        for selector in selectors:
            try:
                for element in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    visible_chunks.append(element.text)
                    aria = element.get_attribute("aria-label")
                    if aria:
                        visible_chunks.append(aria)
            except Exception:
                continue

        blob = " ".join(visible_chunks) + " " + self.driver.page_source
        rating = None
        review_count = None

        rating_match = re.search(r"([0-5](?:[.,]\d)?)\s*(?:bintang|stars)", blob, flags=re.IGNORECASE)
        if rating_match:
            rating = float(rating_match.group(1).replace(",", "."))

        review_match = re.search(
            r"(\d[\d.,]*)\s*(?:ulasan|reviews)",
            blob,
            flags=re.IGNORECASE,
        )
        if review_match:
            digits = review_match.group(1).replace(".", "").replace(",", "")
            if digits.isdigit():
                review_count = int(digits)

        return rating, review_count

    def _find_text(self, selectors: list[str], wait_seconds: int = 0) -> str:
        for index, selector in enumerate(selectors):
            try:
                if wait_seconds and index == 0:
                    element = WebDriverWait(self.driver, wait_seconds).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                else:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                text = element.text.strip()
                if text:
                    return text
            except Exception:
                continue
        return "-"

    def _find_attribute(self, selectors: list[str], attribute: str) -> str:
        for selector in selectors:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                value = (element.get_attribute(attribute) or "").strip()
                if value:
                    return value
            except Exception:
                continue
        return "-"

    def _remaining_slots(self, place_map: OrderedDict[str, SearchQuery]) -> Optional[int]:
        if self.config.max_results <= 0:
            return None
        return max(self.config.max_results - len(place_map), 0)

    def _max_results_reached(self, place_map: OrderedDict[str, SearchQuery]) -> bool:
        return self.config.max_results > 0 and len(place_map) >= self.config.max_results
