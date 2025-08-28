import json
import logging
import time
import requests
from pathlib import Path
from urllib.parse import urljoin
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from requests.exceptions import RequestException

# Configure logging
logging.basicConfig(filename="output/scraper.log", level=logging.INFO, 
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- HELPER FUNCTIONS ----------

def get_driver(browser):
    options = Options()
    options.add_argument("--headless")
    try:
        if browser.lower() == "chrome":
            return webdriver.Chrome(options=options)
        elif browser.lower() == "firefox":
            return webdriver.Firefox(options=options)
        elif browser.lower() == "safari":
            return webdriver.Safari(options=options)
        else:
            raise ValueError(f"Unsupported browser: {browser}")
    except Exception as e:
        logging.error(f"Failed to initialize {browser} driver: {e}")
        raise

# ---------- SCRAPER FUNCTIONS ----------

def scrape_static(url, selectors, pagination_selector=None, limit=5):
    results = []
    current_url = url
    pages_scraped = 0

    while current_url and pages_scraped < limit:
        try:
            response = requests.get(current_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            response.raise_for_status()
        except RequestException as e:
            logging.error(f"Failed to fetch {current_url}: {e}")
            break

        soup = BeautifulSoup(response.text, "html.parser")

        data = {}
        any_data_found = False
        for name, selector in selectors.items():
            elements = soup.select(selector)
            if elements:
                any_data_found = True
                if name.lower() in ["images", "colors", "sizes"]:
                    data[name] = [el.get("src") if name.lower() == "images" else el.get_text(strip=True) for el in elements]
                else:
                    texts = [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]
                    data[name] = texts if len(texts) > 1 else texts[0] if texts else None
            else:
                data[name] = None
        if any_data_found:
            results.append(data)

        if pagination_selector:
            next_page = soup.select_one(pagination_selector)
            if next_page and next_page.get("href"):
                current_url = urljoin(url, next_page["href"])
            else:
                current_url = None
        else:
            current_url = None

        pages_scraped += 1
        logging.info(f"Scraped static page {pages_scraped} from {current_url}")

    return results

def scrape_dynamic(url, selectors, pagination_selector=None, limit=5, browser="chrome"):
    driver = get_driver(browser)
    results = []
    current_url = url
    pages_scraped = 0

    try:
        while current_url and pages_scraped < limit:
            driver.get(current_url)
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.ty-product-block-title bdi")))
            except Exception as e:
                logging.error(f"Timeout waiting for elements on {current_url}: {e}")
                break

            # --- Base data without variations ---
            base_data = {}
            any_data_found = False
            for name, selector in selectors.items():
                if name in ["color_variation", "size_variation"]:
                    continue
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        any_data_found = True
                        if name.lower() in ["images"]:
                            base_data[name] = [el.find_element(By.TAG_NAME, "img").get_attribute("src") for el in elements if el.find_element(By.TAG_NAME, "img").get_attribute("src")]
                        elif name.lower() in ["colors", "sizes"]:
                            base_data[name] = [el.text.strip() for el in elements if el.text.strip()]
                        else:
                            texts = [el.text.strip() for el in elements if el.text.strip()]
                            base_data[name] = texts[0] if texts else None
                    else:
                        base_data[name] = None
                except Exception as e:
                    logging.warning(f"Error scraping {name} on {current_url}: {e}")
                    base_data[name] = None
            if any_data_found:
                results.append(base_data)

            # --- Variation combinations (colors and sizes) ---
            color_variation_selector = selectors.get("color_variation")
            size_variation_selector = selectors.get("size_variation")
            if color_variation_selector or size_variation_selector:
                color_elements = driver.find_elements(By.CSS_SELECTOR, color_variation_selector) if color_variation_selector else [None]
                size_elements = driver.find_elements(By.CSS_SELECTOR, size_variation_selector) if size_variation_selector else [None]

                for color_idx, color_el in enumerate(color_elements):
                    if color_el:
                        try:
                            driver.execute_script("arguments[0].click();", color_el)
                            WebDriverWait(driver, 5).until(EC.staleness_of(color_el) or EC.presence_of_element_located((By.CSS_SELECTOR, "h1.ty-product-block-title bdi")))
                        except Exception as e:
                            logging.warning(f"Error clicking color {color_idx} on {current_url}: {e}")
                            continue

                    for size_idx, size_el in enumerate(size_elements):
                        if size_el:
                            try:
                                driver.execute_script("arguments[0].click();", size_el)
                                WebDriverWait(driver, 5).until(EC.staleness_of(size_el) or EC.presence_of_element_located((By.CSS_SELECTOR, "h1.ty-product-block-title bdi")))
                            except Exception as e:
                                logging.warning(f"Error clicking size {size_idx} on {current_url}: {e}")
                                continue

                        var_data = {
                            "variation_color": color_el.text.strip() if color_el else "N/A",
                            "variation_size": size_el.text.strip() if size_el else "N/A"
                        }
                        any_var_data_found = False
                        for name, selector in selectors.items():
                            if name in ["color_variation", "size_variation"]:
                                continue
                            try:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                if elements:
                                    any_var_data_found = True
                                    if name.lower() in ["images"]:
                                        var_data[name] = [el.find_element(By.TAG_NAME, "img").get_attribute("src") for el in elements if el.find_element(By.TAG_NAME, "img").get_attribute("src")]
                                    elif name.lower() in ["colors", "sizes"]:
                                        var_data[name] = [el.text.strip() for el in elements if el.text.strip()]
                                    else:
                                        texts = [el.text.strip() for el in elements if el.text.strip()]
                                        var_data[name] = texts[0] if texts else None
                                else:
                                    var_data[name] = None
                            except Exception as e:
                                logging.warning(f"Error scraping {name} for variation (color {color_idx}, size {size_idx}) on {current_url}: {e}")
                                var_data[name] = None
                        if any_var_data_found:
                            results.append(var_data)

            if pagination_selector:
                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR, pagination_selector)
                    driver.execute_script("arguments[0].click();", next_btn)
                    WebDriverWait(driver, 5).until(EC.url_changes(current_url))
                    current_url = driver.current_url
                except Exception as e:
                    logging.info(f"No next page found on {current_url}: {e}")
                    current_url = None
            else:
                current_url = None

            pages_scraped += 1
            logging.info(f"Scraped dynamic page {pages_scraped} from {current_url}")

    finally:
        driver.quit()

    return results

def scrape_api(url, json_path, headers=None, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers or {}, timeout=10)
            response.raise_for_status()
            data = response.json()
            for key in json_path:
                data = data.get(key, {})
            logging.info(f"Successfully fetched API data from {url}")
            return [data] if isinstance(data, dict) else data
        except RequestException as e:
            logging.warning(f"API attempt {attempt + 1} failed for {url}: {e}")
            if attempt == retries - 1:
                logging.error(f"API failed after {retries} attempts: {url}")
                return None
            time.sleep(2)

# ---------- MAIN SCRAPER ----------

def run_scraper(config_file="config.json", output_file="output/scraped_data.xlsx"):
    Path("output").mkdir(exist_ok=True)

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            configs = json.load(f)
    except Exception as e:
        logging.error(f"Failed to load config file {config_file}: {e}")
        return

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for idx, site in enumerate(configs.get("websites", [])):
            if not all(key in site for key in ["url", "type", "selectors"]):
                logging.error(f"Invalid config for {site.get('name', 'unknown')}: missing required fields")
                continue

            logging.info(f"Scraping {site['url']} (type: {site['type']})")
            data = []

            if site["type"] == "static":
                data = scrape_static(site["url"], site["selectors"],
                                   site.get("pagination"), site.get("limit", 5))
            elif site["type"] == "dynamic":
                data = scrape_dynamic(site["url"], site["selectors"],
                                    site.get("pagination"), site.get("limit", 5),
                                    site.get("browser", "chrome"))
            elif site["type"] == "api":
                headers = {"Authorization": f"Bearer {site['api_key']}"} if "api_key" in site else {}
                data = scrape_api(site["url"], site["json_path"], headers)
            else:
                logging.warning(f"Unknown type: {site['type']} for {site['url']}")
                continue

            if data:
                df = pd.DataFrame(data)
                if df.empty:
                    logging.warning(f"No valid data to save for {site['url']}")
                    continue
                for col in df.columns:
                    df[col] = df[col].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
                df.insert(0, "url", site["url"])
                sheet_name = site.get("name", f"{site['url'].replace('https://', '').replace('http://', '').split('/')[0]}_{idx}")[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                logging.info(f"Saved data to sheet {sheet_name} in {output_file}")
            else:
                logging.warning(f"No data scraped for {site['url']}")

    logging.info(f"Completed scraping. Data saved to {output_file}")

if __name__ == "__main__":
    run_scraper()