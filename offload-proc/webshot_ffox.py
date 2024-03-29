
import time
from selenium import webdriver
from selenium.webdriver import FirefoxOptions
# from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

class WebScreenshotFirefox:
    def __init__(self):
        self.driver = None
        options = FirefoxOptions()
        options.add_argument("--headless")
        # options = Options()
        # options.headless = True
        geckodriver_path = Service('/usr/bin/geckodriver')
        self.driver = webdriver.Firefox(service=geckodriver_path, options=options)

    def __del__(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    def take(self, url, img_path, delay_s, width, height = None):
        self.driver.get(url)
        time.sleep(1.0) # Load delay
        if height is None:
            height = int(self.driver.execute_script("return document.body.clientHeight;"))
        self.driver.set_window_position(0, 0)
        self.driver.set_window_size(width, height)
        # self.driver.refresh()
        time.sleep(delay_s)
        self.driver.save_screenshot(img_path)
        # if page_wd == 0:
        #     page_wd = int(driver.execute_script("return document.body.clientWidth;"))
        #     # page_wd = int(driver.execute_script("return document.body.scrollWidth;"))
        # if page_ht == 0:
        #     # driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        #     page_ht = int(driver.execute_script("return document.body.clientHeight;"))
        #     # page_ht = int(driver.execute_script("return document.body.scrollHeight;"))
