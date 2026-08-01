from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.globaltenders.com/tender-login/sign-up", wait_until="domcontentloaded")
    time.sleep(3)
    print("URL:", page.url)
    print("Titre:", page.title())
    inputs = page.locator("input")
    for i in range(inputs.count()):
        el = inputs.nth(i)
        print(f"input[{i}] type={el.get_attribute('type')} name={el.get_attribute('name')} id={el.get_attribute('id')}")
    buttons = page.locator("button, input[type=submit]")
    for i in range(buttons.count()):
        el = buttons.nth(i)
        print(f"bouton[{i}] type={el.get_attribute('type')} text={el.inner_text()[:50]}")
    input("Appuie ENTREE pour fermer")
    browser.close()
