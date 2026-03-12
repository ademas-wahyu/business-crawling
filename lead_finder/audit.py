import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib import error, request

from .defaults import SOCIAL_AGGREGATOR_DOMAINS
from .models import LeadAudit
from .utils import extract_domain

LogCallback = Callable[[str], None]


class HTMLSignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.in_script = False
        self.in_style = False
        self.title_chunks: list[str] = []
        self.text_chunks: list[str] = []
        self.has_viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
            return
        if tag == "script":
            self.in_script = True
            return
        if tag == "style":
            self.in_style = True
            return
        if tag != "meta":
            return

        attr_map = {key.lower(): (value or "") for key, value in attrs}
        if attr_map.get("name", "").lower() == "viewport":
            self.has_viewport = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if not clean:
            return
        if self.in_title:
            self.title_chunks.append(clean)
            return
        if self.in_script or self.in_style:
            return
        self.text_chunks.append(clean)

    @property
    def title(self) -> str:
        return " ".join(self.title_chunks).strip()

    @property
    def text_length(self) -> int:
        return len(" ".join(self.text_chunks).strip())


@dataclass
class _FetchedPage:
    final_url: str
    status_code: int
    html: str


def _is_social_domain(domain: str) -> bool:
    return any(domain.endswith(candidate) for candidate in SOCIAL_AGGREGATOR_DOMAINS)


def classify_page_result(
    input_url: str,
    final_url: str,
    status_code: int | None,
    html: str,
    error_message: str = "",
) -> LeadAudit:
    initial_domain = extract_domain(input_url)
    final_domain = extract_domain(final_url or input_url)

    if not input_url or input_url == "-":
        return LeadAudit(website_status="none")

    if _is_social_domain(initial_domain) or _is_social_domain(final_domain):
        return LeadAudit(
            website_status="social_only",
            final_url=final_url or input_url,
            final_domain=final_domain or initial_domain,
            http_status=status_code,
        )

    if error_message:
        return LeadAudit(
            website_status="error",
            final_url=final_url or input_url,
            final_domain=final_domain or initial_domain,
            http_status=status_code,
            error_message=error_message,
        )

    if status_code and status_code >= 400:
        return LeadAudit(
            website_status="error",
            final_url=final_url or input_url,
            final_domain=final_domain or initial_domain,
            http_status=status_code,
            error_message=f"HTTP {status_code}",
        )

    parser = HTMLSignalParser()
    parser.feed(html or "")
    parser.close()

    if not final_domain:
        return LeadAudit(
            website_status="unknown",
            final_url=final_url or input_url,
            http_status=status_code,
            title=parser.title,
            has_viewport=parser.has_viewport,
            text_length=parser.text_length,
        )

    website_status = "owned_domain_ok"
    if not parser.title or not parser.has_viewport or parser.text_length < 250:
        website_status = "owned_domain_weak"

    return LeadAudit(
        website_status=website_status,
        final_url=final_url or input_url,
        final_domain=final_domain,
        http_status=status_code,
        title=parser.title,
        has_viewport=parser.has_viewport,
        text_length=parser.text_length,
    )


class WebsiteAuditor:
    def __init__(
        self,
        timeout: float = 8.0,
        max_retries: int = 2,
        max_workers: int = 5,
        logger: Optional[LogCallback] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.log = logger or (lambda _message: None)
        self.ssl_context = ssl.create_default_context()

    def audit_many(self, leads: list[dict[str, object]]) -> dict[int, LeadAudit]:
        results: dict[int, LeadAudit] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {
                executor.submit(self.audit_url, str(lead.get("website_url") or "")): lead
                for lead in leads
            }
            for future in as_completed(future_map):
                lead = future_map[future]
                lead_id = int(lead["id"])
                try:
                    results[lead_id] = future.result()
                except Exception as exc:
                    results[lead_id] = LeadAudit(
                        website_status="error",
                        final_url=str(lead.get("website_url") or ""),
                        error_message=str(exc),
                    )
        return results

    def audit_url(self, url: str) -> LeadAudit:
        if not url or url == "-":
            return LeadAudit(website_status="none")

        initial_domain = extract_domain(url)
        if _is_social_domain(initial_domain):
            return LeadAudit(
                website_status="social_only",
                final_url=url,
                final_domain=initial_domain,
            )

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                fetched = self._fetch(url)
                return classify_page_result(
                    input_url=url,
                    final_url=fetched.final_url,
                    status_code=fetched.status_code,
                    html=fetched.html,
                )
            except error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if attempt >= self.max_retries:
                    return classify_page_result(
                        input_url=url,
                        final_url=exc.geturl(),
                        status_code=exc.code,
                        html="",
                        error_message=last_error,
                    )
            except (error.URLError, TimeoutError, ValueError, OSError) as exc:
                last_error = str(exc)
                if attempt >= self.max_retries:
                    return classify_page_result(
                        input_url=url,
                        final_url=url,
                        status_code=None,
                        html="",
                        error_message=last_error,
                    )

        return classify_page_result(
            input_url=url,
            final_url=url,
            status_code=None,
            html="",
            error_message=last_error or "Unknown error",
        )

    def _fetch(self, url: str) -> _FetchedPage:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }
        req = request.Request(url, headers=headers)
        with request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
            body = response.read(1024 * 1024)
            html = body.decode("utf-8", errors="ignore")
            return _FetchedPage(
                final_url=response.geturl(),
                status_code=getattr(response, "status", 200),
                html=html,
            )
