from playwright.sync_api import sync_playwright
import time

URL = (
    "https://www.globaltenders.com/gt-search"
    "?status=menu&limit=0"
    "&sector%5B%5D=21"
    "&region_name%5B%5D=REG0101&region_name%5B%5D=REG0102&region_name%5B%5D=REG0104"
    "&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc"
    "&cpv=&bidding_type=&tender_type=live"
    "&postrange=&deadline=&posting_id=&est_cost_currency=USD&est_cost="
)

appels = []

def capturer(req):
    url = req.url
    if any(x in url for x in ["search", "tender", "result", "api", "ajax", "query", "data", "gt-"]):
        appels.append({"method": req.method, "url": url})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.on("request", capturer)
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    print(">>> Connecte-toi manuellement puis attends les resultats...")
    time.sleep(30)
    print(f"\n>>> {len(appels)} requetes capturees :")
    for a in appels:
        print(f"  [{a['method']}] {a['url']}")
    input("\nAppuie ENTREE pour fermer")
    browser.close()
