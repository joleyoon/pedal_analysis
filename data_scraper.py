from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import json


class GearSearchScraper:
    SEARCH_URL = "https://www.thegearpage.net/board/index.php?search/&type=post"

    def __init__(self, gear_query: str, *, headless: bool = False, timeout: int = 10) -> None:
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
            search_input = wait.until(
                EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[2]/div[2]/div[4]/div/div[3]/div[2]/div[2]/form/div/div/dl[1]/dd/ul/li[1]/input'))
            )
        except TimeoutException as exc:
            raise RuntimeError("Search input not found.") from exc

        search_input.send_keys(self.gear_query)

        try:
            search_button = self.driver.find_element(By.XPATH, '/html/body/div[1]/div[2]/div[2]/div[4]/div/div[3]/div[2]/div[2]/form/div/dl/dd/div/div[2]/button')
        except NoSuchElementException as exc:
            raise RuntimeError("Search button not found.") from exc

        wait.until(EC.element_to_be_clickable(search_button))
        search_button.click()

        return self.gather_hrefs(max_results=50)

        
    def gather_hrefs(self, *, max_results: int | None = None) -> list[str]:
        """Collect hrefs inside '.block-body' sections, optionally bounded by max_results."""

        contentRow = WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.CLASS_NAME, "block-container")))
        all_links = contentRow.find_elements(By.TAG_NAME, "a")

        links = []
        for link in all_links:
            links.append(link.get_attribute("href"))

        return links

    def close(self) -> None:
        """Close down the driver when we're done."""

        self.driver.quit()


if __name__ == "__main__":
    # gear = input("Enter the gear you want to search for: ").strip()
    # gear = "prs silver sky"
    # if not gear:
    #     raise SystemExit("Gear search query cannot be empty.")

    # scraper = GearSearchScraper(gear_query=gear, headless=False)
    # export_list = scraper.perform_search()

    # print(export_list)

    # with open("something.json", 'w', encoding="utf-8") as f:
    #     json.dump(f, export_list)
    #     print("done")

    driver = webdriver.Chrome()
    driver.get("https://www.thegearpage.net/board/index.php?search/17445187/&q=prs+silver+sky&t=post&o=relevance")

    contentRow = WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.CLASS_NAME, "block-container")))
    all_links = contentRow.find_elements(By.TAG_NAME, "a")

    links = []
    for link in all_links:
        links.append(link.get_attribute("href"))

    print(len(links))

    while True:
        pass






