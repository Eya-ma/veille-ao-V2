from playwright.sync_api import sync_playwright
import time, json

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
    ctx = browser.new_context()
    page = ctx.new_page()
    print(">>> Ouverture login page...")
    page.goto("https://www.globaltenders.com/login", wait_until="domcontentloaded")
    print(">>> Connecte-toi manuellement dans le navigateur (tu as 60s)...")
    time.sleep(60)
    cookies = ctx.cookies()
    with open("gt_cookies.json", "w") as f:
        json.dump(cookies, f)
    print(f">>> {len(cookies)} cookies sauvegardes dans gt_cookies.json")
    page.goto(URL, wait_until="domcontentloaded")
    time.sleep(8)
    html = page.content()
    with open("gt_result.html", "w", encoding="utf-8") as f:
        f.write(html)
    texte = page.inner_text("body")
    print(texte[2000:5000])
    print(">>> HTML sauvegarde dans gt_result.html")
    browser.close()
