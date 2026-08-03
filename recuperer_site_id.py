import os
import requests
from dotenv import load_dotenv

load_dotenv()

TENANT_ID     = os.environ["SHAREPOINT_TENANT_ID"]
CLIENT_ID     = os.environ["SHAREPOINT_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHAREPOINT_CLIENT_SECRET"]

url_token = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope": "https://graph.microsoft.com/.default",
    "grant_type": "client_credentials",
}
resp = requests.post(url_token, data=data)
resp.raise_for_status()
token = resp.json()["access_token"]

headers = {"Authorization": f"Bearer {token}"}
url_site = "https://graph.microsoft.com/v1.0/sites/steamine.sharepoint.com:/sites/Commercial"
resp = requests.get(url_site, headers=headers)
print(resp.status_code)
print(resp.json())