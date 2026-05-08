from __future__ import annotations

import argparse
import re
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


_STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "for",
    "from",
    "help",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self._in_title = False
        self._in_heading = False
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "title":
            self._in_title = True
        elif tag in {"h1", "h2", "h3"}:
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"h1", "h2", "h3"}:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._in_heading:
            self.heading_parts.append(text)


def fetch_url(url: str, timeout: float = 10.0) -> str:
    """Fetch URL content as UTF-8 text.

    Raises:
        OSError: Propagated network/HTTP errors from urllib.
    """
    request = Request(url, headers={"User-Agent": "helpguideschecker/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _normalize_word(word: str) -> str | None:
    clean = re.sub(r"[^a-z0-9]+", "", word.lower())
    if len(clean) < 3 or clean in _STOPWORDS:
        return None
    return clean


def _terms_from_path(url: str) -> set[str]:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    words = re.split(r"[-_\W]+", " ".join(segments))
    return {term for token in words if (term := _normalize_word(token))}


def _terms_from_html(html: str) -> tuple[set[str], list[str]]:
    parser = _Extractor()
    parser.feed(html)
    combined = " ".join(parser.title_parts + parser.heading_parts)
    words = re.split(r"[^a-zA-Z0-9]+", combined)
    terms = {term for token in words if (term := _normalize_word(token))}
    return terms, parser.links


def crawl_site(
    start_url: str,
    max_pages: int,
    fetcher: Callable[[str], str],
) -> dict[str, set[str]]:
    parsed_start = urlparse(start_url)
    domain = parsed_start.netloc
    queue: deque[str] = deque([start_url.rstrip("/")])
    visited: set[str] = set()
    page_terms: dict[str, set[str]] = {}

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            html = fetcher(url)
        except Exception:
            continue

        terms, links = _terms_from_html(html)
        terms |= _terms_from_path(url)
        page_terms[url] = terms

        for link in links:
            absolute = urljoin(url, link).split("#", 1)[0].rstrip("/")
            if not absolute or absolute in visited:
                continue
            parsed = urlparse(absolute)
            if parsed.netloc != domain or not parsed.scheme.startswith("http"):
                continue
            queue.append(absolute)

    return page_terms


def compare_sites(
    app_pages: dict[str, set[str]],
    help_pages: dict[str, set[str]],
) -> list[dict[str, object]]:
    help_terms: set[str] = set()
    help_paths = {urlparse(url).path.rstrip("/") for url in help_pages}
    for terms in help_pages.values():
        help_terms.update(terms)

    missing: list[dict[str, object]] = []
    for app_url, app_terms in sorted(app_pages.items()):
        missing_terms = sorted(term for term in app_terms if term not in help_terms)
        app_path = urlparse(app_url).path.rstrip("/")
        path_missing = bool(app_path and app_path not in help_paths)
        if path_missing or missing_terms:
            missing.append(
                {
                    "app_url": app_url,
                    "path_missing": path_missing,
                    "missing_terms": missing_terms,
                }
            )
    return missing


def _safe_filename(url: str) -> str:
    parsed = urlparse(url)
    base = parsed.path.strip("/") or "home"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", base) + ".md"


def write_markdown_reports(missing_details: list[dict[str, object]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_lines = ["# Missing Help Guide Details", ""]
    if not missing_details:
        summary_lines.append("No missing details were detected.")
    else:
        summary_lines.append("The following app pages appear to be missing from help documentation:")
        summary_lines.append("")

    for entry in missing_details:
        app_url = str(entry["app_url"])
        filename = _safe_filename(app_url)
        summary_lines.append(f"- [{app_url}]({filename})")

        detail_lines = [
            f"# Missing details for {app_url}",
            "",
            "## Findings",
        ]
        if entry["path_missing"]:
            detail_lines.append("- Matching help guide path was not found.")
        raw_missing_terms = entry.get("missing_terms", [])
        missing_terms = list(raw_missing_terms) if isinstance(raw_missing_terms, list) else []
        if missing_terms:
            detail_lines.append("- Potentially undocumented terms:")
            detail_lines.extend(f"  - `{term}`" for term in missing_terms)
        if not entry["path_missing"] and not missing_terms:
            detail_lines.append("- No obvious missing details detected.")

        (output_dir / filename).write_text("\n".join(detail_lines) + "\n", encoding="utf-8")

    (output_dir / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def run_check(
    docs_url: str,
    app_url: str,
    output_dir: Path,
    max_help_pages: int = 75,
    max_app_pages: int = 75,
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    def _fetcher(url: str) -> str:
        return fetch_url(url, timeout=timeout)

    help_pages = crawl_site(docs_url, max_help_pages, _fetcher)
    app_pages = crawl_site(app_url, max_app_pages, _fetcher)
    missing = compare_sites(app_pages, help_pages)
    write_markdown_reports(missing, output_dir)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare SmartSurvey app functionality with help guide coverage.",
    )
    parser.add_argument("--docs-url", default="https://help.smartsurvey.co.uk")
    parser.add_argument("--app-url", default="https://app.smartsurvey.co.uk")
    parser.add_argument("--output-dir", default="missing-help-guides")
    parser.add_argument("--max-help-pages", type=int, default=75)
    parser.add_argument("--max-app-pages", type=int, default=75)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    missing = run_check(
        docs_url=args.docs_url,
        app_url=args.app_url,
        output_dir=Path(args.output_dir),
        max_help_pages=args.max_help_pages,
        max_app_pages=args.max_app_pages,
        timeout=args.timeout,
    )

    print(f"Compared {args.app_url} against {args.docs_url}")
    total_files = len(list(Path(args.output_dir).glob("*.md")))
    print(f"Generated {total_files} report files in {args.output_dir}")


if __name__ == "__main__":
    main()
