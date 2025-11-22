from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from bs4 import BeautifulSoup
import requests
import json
import time
import re


class GearSearchScraper:
    SEARCH_URL = "https://www.thegearpage.net/board/index.php?search/&type=post"
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    def __init__(self, gear_query: str, *, headless: bool = False, timeout: int = 5) -> None:
        self.gear_query = gear_query
        self.headless = headless
        self.timeout = timeout
        self.driver = self._build_driver()

    def _build_driver(self) -> Chrome:
        """Create a Chrome driver instance configured for scraping."""

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        return webdriver.Chrome(options=chrome_options)

    def open_search_page(self) -> None:
        """Navigate to the search URL."""

        self.driver.get("https://www.thegearpage.net/board/index.php?search/&type=post")

    def perform_search(self) -> list[str]:
        """Fill the search box with the gear query and click search."""
        self.open_search_page()
        wait = WebDriverWait(self.driver, self.timeout)

        try:
            # why does this not work when headless?
            search_input = wait.until(
                EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[2]/div[2]/div[4]/div/div[3]/div[2]/div[2]/form/div/div/dl[1]/dd/ul/li[1]/input'))
            )
        except TimeoutException as exc:
            raise RuntimeError("Search input not found.") from exc
        search_input.send_keys(self.gear_query)
        # this is the button part and quite honestly i have no idea how this works, cuz it just sends something and it searches itself
        # starting from there? i have no idea, i thought it was suppose to press the button but i guess not either way it works so ima
        # move on, if it doesnt work in the future cuz the search button isn't being pressed, do this part

        self.press_search_button(wait)
        time.sleep(5)

        return self.gather_hrefs()

    def press_search_button(self, wait) -> None:
        try:
            search_button = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[2]/div[2]/div[4]/div/div[3]/div[2]/div[2]/form/div/dl/dd/div/div[2]/button')
        except NoSuchElementException as exc:
            raise RuntimeError("Search button not found.") from exc

        wait.until(EC.element_to_be_clickable(search_button))
        search_button.click()

        
    def gather_hrefs(self) -> list[str]:
        """Collect hrefs inside '.block-body' sections, optionally bounded by max_results."""
        contentRow = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "block-container")))
        all_links = contentRow.find_elements(By.TAG_NAME, "a")
        links = []
        for link in all_links:
            links.append(link.get_attribute("href"))

        return links
    
    def gather_data_from_post(self, link):
        """Takes link as input and gathers the information from that post and format into json"""
        response = requests.get(link, headers=self.DEFAULT_HEADERS, timeout=self.timeout * 5)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        first_post = soup.select_one("article.message")
        title_elem = soup.select_one("h1.p-title-value")
        author_elem = first_post.select_one("a.username") if first_post else None
        time_elem = first_post.select_one("time.u-dt") if first_post else None
        body_elem = first_post.select_one(".bbWrapper") if first_post else None

        return {
            "url": link,
            "title": title_elem.get_text(strip=True) if title_elem else None,
            "author": author_elem.get_text(strip=True) if author_elem else None,
            "posted_on": time_elem.get("datetime") if time_elem else None,
            "content": body_elem.get_text("\n", strip=True) if body_elem else None,
        }
        return

    @classmethod
    def fetch_post_markup(cls, url: str, *, timeout: int = 30) -> tuple[str, str]:
        """Return the markup body and the source type ('html' or 'snapshot')."""

        response = requests.get(url, headers=cls.DEFAULT_HEADERS, timeout=timeout)
        try:
            response.raise_for_status()
            return response.text, "html"
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 406:
                raise

        fallback_url = f"https://r.jina.ai/{requests.utils.requote_uri(url)}"
        fallback_response = requests.get(fallback_url, timeout=timeout * 2)
        fallback_response.raise_for_status()
        return fallback_response.text, "snapshot"

    @staticmethod
    def parse_snapshot(url: str, text_snapshot: str) -> dict:
        """Parse the plaintext snapshot served by r.jina.ai if the site blocks us."""

        payload = {"url": url, "title": None, "author": None, "posted_on": None, "content": None}
        lines = [line.strip() for line in text_snapshot.splitlines()]

        for line in lines:
            if line.startswith("Title:"):
                payload["title"] = line.split("Title:", 1)[1].strip() or None
                break

        for line in lines:
            if line.startswith("Published Time:"):
                payload["posted_on"] = line.split("Published Time:", 1)[1].strip() or None
                break

        author_block_index = None
        for idx, line in enumerate(lines):
            if line.startswith("#### ["):
                match = re.search(r"\[(.*?)\]", line)
                if match:
                    payload["author"] = match.group(1).strip()
                author_block_index = idx
                break

        if author_block_index is not None:
            content_start = None
            for idx in range(author_block_index, len(lines)):
                if "[#1]" in lines[idx]:
                    content_start = idx + 2
                    break
            if content_start is None:
                content_start = author_block_index

            content_end = len(lines)
            for idx in range(content_start, len(lines)):
                if idx == content_start:
                    continue
                if lines[idx].startswith("#### ["):
                    content_end = idx
                    break
                if lines[idx].startswith("Share:"):
                    content_end = idx
                    break

            payload["content"] = "\n".join(lines[content_start:content_end]).strip() or None

        return payload


if __name__ == "__main__":
    target_link = "https://www.thegearpage.net/board/index.php?threads/2025-prs-silver-sky-tungsten.2713931/"

    markup, source_type = GearSearchScraper.fetch_post_markup(target_link)
    if source_type == "html":
        soup = BeautifulSoup(markup, "html.parser")
        first_post = soup.select_one("article.message")
        title_elem = soup.select_one("h1.p-title-value")
        author_elem = first_post.select_one("a.username") if first_post else None
        time_elem = first_post.select_one("time.u-dt") if first_post else None
        body_elem = first_post.select_one(".bbWrapper") if first_post else None

        post_payload = {
            "url": target_link,
            "title": title_elem.get_text(strip=True) if title_elem else None,
            "author": author_elem.get_text(strip=True) if author_elem else None,
            "posted_on": time_elem.get("datetime") if time_elem else None,
            "content": body_elem.get_text("\n", strip=True) if body_elem else None,
        }
    else:
        post_payload = GearSearchScraper.parse_snapshot(target_link, markup)

    print(json.dumps(post_payload, indent=2))
