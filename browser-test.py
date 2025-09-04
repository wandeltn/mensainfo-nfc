from selenium import webdriver


def test_basic_service():
    service = webdriver.FirefoxService()
    driver = webdriver.Firefox(service=service)

    driver.quit()


def test_driver_location(firefoxdriver_bin, firefox_bin):
    options = get_default_firefox_options()
    options.binary_location = firefox_bin

    service = webdriver.FirefoxService(executable_path="/usr/local/bin/geckodriver")

    driver = webdriver.Firefox(service=service, options=options)

    driver.quit()


def test_driver_port():
    service = webdriver.FirefoxService(port=1234)

    driver = webdriver.Firefox(service=service)

    driver.quit()


def get_default_firefox_options():
    options = webdriver.FirefoxOptions()
    options.add_argument("--no-sandbox")
    return options

def get_default_chrome_options():
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    return options

test_basic_service()
test_driver_location()
test_driver_port()