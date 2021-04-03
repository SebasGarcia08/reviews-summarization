import sys
import csv
import time
import random
import logging
import traceback
import os

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

import pandas as pd
import numpy as np

# path to the Chrome driver
PATH = "/usr/bin/chromedriver"


class RestaurantReviewsScraper(object):

    def __init__(self, url, csv_writer, restaurant, driver_opts=None, debug=False, max_num_retries=3):
        """
        Creates a RestaurantReviewsScraper object

        :param url: str, url to scrape
        :param csv_writer: csv.writer object
        :param restaurant: str, restaurant name
        :param driver_opts: chrome.options.Options object
        :param debug: bool, whether to print or not
        :param max_num_retries: int, maximum number of retries to the url
        """
        self.finished = False
        self.csv_writer = csv_writer
        self.debug = debug
        self.restaurant_name = restaurant
        self.url = url
        self.max_num_retries = max_num_retries

        self.reviews_div = None
        self.num_last_page = None

        self.num_curr_page = 1
        self.num_retries = 0

        self.NUM_REVIEWS_PER_PAGE = 10

        logging.basicConfig(
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        if driver_opts is not None:
            self.driver = webdriver.Chrome(PATH, **driver_opts)
        else:
            self.driver = webdriver.Chrome(PATH)

    @staticmethod
    def expand_reviews(locator, base_element):
        element = WebDriverWait(base_element, timeout=10).until(
            EC.presence_of_element_located(locator)
        )
        if element is not None:
            element.click()

    def _get_field(self, jth_container, xpath, element_name):
        try:
            field = jth_container.find_element_by_xpath(xpath)
        except Exception as e:
            self.logger.error(f"Could not get {element_name}")
            self.logger.error(e)
            field = None
        return field

    def _get_fields(self, rev_container):
        # TITLE
        title = self._get_field(rev_container, ".//span[@class='noQuotes']", "title")
        if title is not None:
            title = title.text

        # REVIEW
        date = self._get_field(rev_container, ".//span[contains(@class, 'ratingDate')]", "date")
        if date is not None:
            try:
                date = date.get_attribute("title")
            except Exception as e:
                self.logger.error("Could not load date")
                self.logger.error(e)

        # RATING
        rating = self._get_field(rev_container, ".//span[contains(@class, 'ui_bubble_rating bubble_')]", "rating")
        if rating is not None:
            rating = rating.get_attribute("class").split("_")[3]

        # REVIEW
        try:
            try:
                review = rev_container.find_element_by_xpath(
                    ".//span[@class='postSnippet']").text.replace("\n", " ")
            except:
                review = rev_container.find_element_by_xpath(
                    ".//p[@class='partial_entry']").text.replace("\n", " ")

        except Exception as e:
            review = None
            self.logger.error("Could not get review")
            self.logger.error(e)

        return [date, rating, title, review]

    def _wait_reviews_loading(self, container):
        # Check that all 10 reviews are loaded if we are not in the last page
        if len(container) < self.NUM_REVIEWS_PER_PAGE and self.num_curr_page < self.num_last_page:
            max_num_tries = 5
            num_tries = 0

            while len(container) != self.NUM_REVIEWS_PER_PAGE and num_tries < max_num_tries:
                time.sleep(1)
                try:
                    container = self.driver.find_elements_by_xpath(
                        ".//div[@class='review-container']")
                except Exception as e:
                    self.logger.log(
                        f"Could not load container with 10 reviews, retrying {num_tries} of {max_num_tries}")
                    self.logger.log(e)
                    pass
                num_tries += 1

    def _read_page(self):
        # expand the review
        more_span = "//span[@class='taLnk ulBlueLinks']"
        expand_locator = (By.XPATH, more_span)
        try:
            self.expand_reviews(expand_locator,
                                base_element=self.reviews_div)
        except Exception as e:
            try:
                self.expand_reviews(expand_locator,
                                    base_element=self.reviews_div)
            except:
                self.logger.info("Could not find 'more' button "
                                 "in order to expand reviews")

        # Wait for the expansion of reviews to take place
        time.sleep(2)
        container = self.driver.find_elements_by_xpath(
            ".//div[@class='review-container']"
        )

        # Make sure that all the reviews are loaded
        self._wait_reviews_loading(container)

        # Get the fields for each review in review container
        for j in range(len(container)):
            date, rating, title, review = self._get_fields(container[j])
            if self.debug:
                print([self.restaurant_name, date, rating, title, review])
            self.csv_writer.writerow([self.restaurant_name, date, rating,
                                      title, review, self.url, str(self.num_curr_page)])

    def _click_next_page(self):
        if self.num_curr_page < self.num_last_page:
            # Change the page
            try:
                WebDriverWait(self.reviews_div, timeout=5).until(
                    EC.element_to_be_clickable((By.XPATH, './/a[@class="nav next ui_button primary"]'))
                ).click()
                time.sleep(random.randint(1, 3))

                # Advance page counter
                self.num_curr_page += 1

            except Exception as e:
                self.logger.error(
                    "Could not find and click next button even without "
                    "being in the last page and waited to load")
                self.logger.error(e)
        else:
            self.logger.info("Reached end of all pages")
            self.finished = True

    def scrape_url(self):
        # Begin trial to scrape
        while not self.finished and self.num_retries < self.max_num_retries:
            try:
                self.driver.get(self.url)
                self.reviews_div = WebDriverWait(self.driver, timeout=10).until(
                    EC.presence_of_element_located((By.ID, "REVIEWS"))
                )
                try:
                    num_pages_el = WebDriverWait(self.reviews_div, timeout=10).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "pageNum.last"))
                    )
                    self.num_last_page = int(num_pages_el.text)
                    self.logger.info(f"Found a maximum of {self.num_last_page} pages")
                except Exception as e:
                    self.logger.error(
                        "Could not find maximum page. This page may only have one page of reviews")
                    self.logger.error(e)
                    self.num_last_page = 1

                # change the value inside the range to save more or less reviews
                while self.num_curr_page <= self.num_last_page:
                    self._read_page()
                    self._click_next_page()

            except TimeoutException as e:
                self.logger.error(
                    f"Could not load this page, retrying... {self.num_retries + 1} of {self.max_num_retries}")
                self.logger.error(e)
                self.num_retries += 1
                time.sleep(random.randint(1, 60))

            self.driver.close()
            time.sleep(random.randint(1, 3))


def run():
    # default path to file to store data
    path_to_file = "../datasets/scraped_final_list_URL_TripAdvisor.csv"
    df = pd.read_csv(path_to_file, sep=";")

    # Open the file to save the review
    csvFile = open(path_to_file, 'a', encoding="utf-8")
    csvWriter = csv.writer(csvFile)

    for i, row in df.iterrows():
        url = row["NYC_extract.TripAdvisor.URL"]
        if not url.startswith("http"):
            continue
        print(url)

        opts = Options()
        opts.add_argument('--no-sandbox')
        opts.add_argument('--headless')
        opts.add_argument('--disable-dev-shm-usage')
        driver_opts = {"options": opts}

        restaurant_name = row["NYC_extract.DBA"]
        scraper = RestaurantReviewsScraper(url, csvWriter, restaurant_name, driver_opts)
        scraper.scrape_url()


def test():
    url = "https://www.tripadvisor.com/Restaurant_Review-g60763-d477302-Reviews-Umberto_s_Clam_House-New_York_City_New_York.html"
    file = open("../datasets/test.csv", 'a', encoding="utf-8")
    csv_writer = csv.writer(file, delimiter="\t")
    scraper = RestaurantReviewsScraper(url, csv_writer, "test", debug=True)
    scraper.scrape_url()


if __name__ == "__main__":
    test()