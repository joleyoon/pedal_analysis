"""
Scrape The Gear Page search results for a given gear query using Selenium.

The script launches a Selenium-controlled Chrome browser, performs a keyword
search, iterates through result pages, and saves every page's posts as a JSON
file. ChromeDriver must be installed and available on PATH.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    BeautifulSoup = None  # type: ignore

SEARCH_URL = "https://www.thegearpage.net/board/index.php?search/&type=post"
BASE_URL = "https://www.thegearpage.net"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape TheGearPage.net post search results into JSON files."
    )
    parser.add_argument(
        "query",
        help="Gear name or any search string to submit to The Gear Page search form.",
    )
    parser.add_argument(
        "-p",
        "--pages",
        type=int,
        default=5,
        help="Maximum number of result pages to capture (default: 5).",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between pagination requests (default: 2.0).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("scraped_results"),
        help="Directory where JSON files will be written (default: ./scraped_results).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run Chrome with a visible browser window.",
    )
    parser.set_defaults(headless=True)
    return parser.parse_args()


def slugify(value: str) -> str:
    """Convert a search query into a filesystem-friendly slug."""
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "search"


def create_driver(headless: bool = True) -> Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def submit_search(driver: Chrome, query: str, *, timeout: int = 15) -> None:
    driver.get(SEARCH_URL)
    wait = WebDriverWait(driver, timeout)
    search_input = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='keywords']"))
    )
    search_input.clear()
    search_input.send_keys(query)
    search_input.send_keys(Keys.RETURN)


def wait_for_results(driver: Chrome, *, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (
                By.CSS_SELECTOR,
                "div.structItem, div.contentRow, li.block-row",
            )
        )
    )


def extract_struct_items(soup: Any) -> Iterable[Dict[str, Optional[str]]]:
    for item in soup.select("div.structItem"):
        title = item.select_one(".structItem-title")
        link = title.select_one("a") if title else None
        snippet = item.select_one(".structItem-snippet, .structItem-minor")
        author = item.select_one(".username")
        timestamp = item.select_one("time")
        if not link:
            continue
        yield {
            "title": title.get_text(strip=True) if title else None,
            "snippet": snippet.get_text(" ", strip=True) if snippet else None,
            "author": author.get_text(strip=True) if author else None,
            "posted": timestamp["datetime"] if timestamp and timestamp.has_attr("datetime") else None,
            "link": urljoin(BASE_URL, link.get("href")),
        }


def extract_content_rows(soup: Any) -> Iterable[Dict[str, Optional[str]]]:
    for row in soup.select("div.contentRow"):
        title = row.select_one(".contentRow-title a")
        snippet = row.select_one(".contentRow-snippet")
        author = row.select_one(".contentRow-extra > span")
        timestamp = row.select_one("time")
        if not title:
            continue
        yield {
            "title": title.get_text(" ", strip=True),
            "snippet": snippet.get_text(" ", strip=True) if snippet else None,
            "author": author.get_text(strip=True) if author else None,
            "posted": timestamp["datetime"] if timestamp and timestamp.has_attr("datetime") else None,
            "link": urljoin(BASE_URL, title.get("href")),
        }


def parse_results(page_source: str) -> List[Dict[str, Optional[str]]]:
    if BeautifulSoup is None:
        raise RuntimeError(
            "BeautifulSoup4 is required. Install it with `pip install beautifulsoup4`."
        )
    soup = BeautifulSoup(page_source, "html.parser")
    results: List[Dict[str, Optional[str]]] = []
    seen_links = set()

    def add_result(item: Dict[str, Optional[str]]) -> None:
        link = item.get("link")
        if link and link not in seen_links:
            seen_links.add(link)
            results.append(item)

    for item in extract_struct_items(soup):
        add_result(item)
    for item in extract_content_rows(soup):
        add_result(item)

    # XenForo sometimes renders fallback rows in li.block-row
    for row in soup.select("li.block-row"):
        title = row.select_one("a")
        if not title:
            continue
        snippet = row.select_one(".listHeap") or row
        timestamp = row.select_one("time")
        add_result(
            {
                "title": title.get_text(" ", strip=True),
                "snippet": snippet.get_text(" ", strip=True) if snippet else None,
                "author": None,
                "posted": timestamp["datetime"] if timestamp and timestamp.has_attr("datetime") else None,
                "link": urljoin(BASE_URL, title.get("href")),
            }
        )

    return results


def click_next_page(driver: Chrome) -> bool:
    selectors = [
        "a.pageNav-jump--next",
        "a.pageNav-next",
        "a[rel='next']",
    ]
    for selector in selectors:
        try:
            next_button = driver.find_element(By.CSS_SELECTOR, selector)
            driver.execute_script("arguments[0].click();", next_button)
            return True
        except NoSuchElementException:
            continue
    return False


def save_results(
    query: str, page_number: int, results: List[Dict[str, Optional[str]]], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(query)
    file_path = output_dir / f"{slug}-page-{page_number:03d}.json"
    payload = {
        "query": query,
        "page": page_number,
        "result_count": len(results),
        "results": results,
    }
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return file_path


def scrape(
    query: str,
    *,
    max_pages: int,
    delay: float,
    headless: bool,
    output_dir: Path,
) -> None:
    driver = create_driver(headless=headless)
    try:
        print(f"[info] Searching for '{query}' (up to {max_pages} pages)...")
        submit_search(driver, query)
        wait_for_results(driver)

        for page in range(1, max_pages + 1):
            wait_for_results(driver)
            results = parse_results(driver.page_source)
            if not results:
                print(f"[warn] No results found on page {page}; stopping.")
                break
            output_path = save_results(query, page, results, output_dir)
            print(f"[info] Saved {len(results)} posts to {output_path}")

            if page == max_pages:
                print("[info] Reached requested page limit.")
                break
            if not click_next_page(driver):
                print("[info] No additional pages detected; scraping complete.")
                break
            time.sleep(delay)
    finally:
        driver.quit()


def main() -> None:
    args = parse_arguments()
    try:
        scrape(
            args.query,
            max_pages=max(1, args.pages),
            delay=max(0.5, args.delay),
            headless=args.headless,
            output_dir=args.output_dir,
        )
    except TimeoutException as exc:
        print(f"[error] Timed out waiting for content: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - runtime guardrail
        print(f"[error] Scraper failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()