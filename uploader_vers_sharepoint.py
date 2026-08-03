import os
import requests
from sharepoint_auth import obtenir_token

SITE_ID        = os.environ["SHAREPOINT_SITE_ID"]
CHEMIN_FICHIER = "Veille AO/veille_ao_resultats.xlsx"
CHEMIN_LOCAL   = "veille_ao_resultats.xlsx"

def uploader():
    if not os.path.exists(CHEMIN_LOCAL):
        print(f"[UPLOAD] Fichier local {CHEMIN_LOCAL} introuvable -> rien a envoyer")
        return

    token = obtenir_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:/{CHEMIN_FICHIER}:/content"

    with open(CHEMIN_LOCAL, "rb") as f:
        resp = requests.put(url, headers=headers, data=f.read())

    resp.raise_for_status()
    print(f"[UPLOAD] Fichier envoye vers SharePoint : {CHEMIN_FICHIER}")

if __name__ == "__main__":
    uploader()