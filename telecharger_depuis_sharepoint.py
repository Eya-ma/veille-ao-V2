import os
import requests
from sharepoint_auth import obtenir_token

SITE_ID     = os.environ["SHAREPOINT_SITE_ID"]
CHEMIN_FICHIER = "Veille AO/veille_ao_resultats.xlsx"  # chemin relatif dans la bibliotheque "Documents"
CHEMIN_LOCAL   = "resultats_veille.xlsx"  # adapte au nom que main.py attend en local

def telecharger():
    token = obtenir_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:/{CHEMIN_FICHIER}:/content"

    resp = requests.get(url, headers=headers)

    if resp.status_code == 404:
        print("[TELECHARGEMENT] Aucun fichier trouve sur SharePoint -> le script va en creer un nouveau")
        return

    resp.raise_for_status()
    with open(CHEMIN_LOCAL, "wb") as f:
        f.write(resp.content)
    print(f"[TELECHARGEMENT] Fichier recupere depuis SharePoint -> {CHEMIN_LOCAL}")

if __name__ == "__main__":
    telecharger()