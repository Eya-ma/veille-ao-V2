from playwright.sync_api import sync_playwright
import time

URL = (
    "https://www.globaltenders.com/gt-search"
    "?status=menu&limit=0&sector%5B%5D=21"
    "&region_name%5B%5D=REG0101&region_name%5B%5D=REG0102&region_name%5B%5D=REG0104"
    "&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc"
    "&cpv=&bidding_type=&tender_type=live"
    "&postrange=&deadline=&posting_id=&est_cost_currency=USD&est_cost="
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.globaltenders.com/tender-login/sign-up", wait_until="domcontentloaded")
    print(">>> Connecte-toi manuellement dans le navigateur, puis appuie ENTREE ici")
    input()
    print(">>> URL apres login:", page.url)
    page.goto(URL, wait_until="domcontentloaded")
    time.sleep(8)
    texte = page.inner_text("body")
    print(texte[1500:5000])
    open("gt_result.html", "w", encoding="utf-8").write(page.content())
    print(">>> HTML sauvegarde")
    browser.close()
