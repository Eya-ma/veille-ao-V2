"""
Deduplication, normalisation des AO, gestion de l'historique (fichier JSON des AO
deja vus) et affichage console. Issu du decoupage de veille_ao_1_1.py (v10.18).
"""
import os
import json
import hashlib
from datetime import datetime

from config import log
from utils import normaliser_texte


def deduplicer(resultats):
    avant = len(resultats)
    vus, uniques = set(), []
    for r in resultats:
        cle = hashlib.md5(
            (r.get("titre", "") + r.get("lien", r.get("lien_avis", ""))).encode("utf-8")
        ).hexdigest()
        if cle not in vus:
            vus.add(cle)
            uniques.append(r)
    apres = len(uniques)
    if avant != apres:
        log.info(f"[DEDUPLICATION] {avant} -> {apres} ({avant - apres} doublon(s) retire(s))")
    return uniques

def dedupliquer_inter_sources(tous_les_ao):
    """Retire les AO identiques detectes sur plusieurs sources
    differentes (ex: le meme AO agrege par DevelopmentAid ET J360).
    Cle de comparaison : titre normalise + pays -- ignore volontairement
    la source et l'URL, qui different forcement d'un agregateur a
    l'autre pour le meme AO reel.

    En cas de doublon, conserve simplement le premier AO rencontre
    (ordre de scraping dans main.py), sans logique de priorite."""
    vus = set()
    resultat = []
    doublons_retires = 0

    for ao in tous_les_ao:
        cle = (normaliser_texte(ao.get("titre", "")).lower().strip(),
               normaliser_texte(ao.get("pays", "")).lower().strip())
        if cle in vus:
            doublons_retires += 1
            log.info(
                f"[DEDUP INTER-SOURCES] '{ao.get('titre','')[:60]}' "
                f"({ao.get('source','')}) ignore -- deja vu sous une autre source"
            )
            continue
        vus.add(cle)
        resultat.append(ao)

    if doublons_retires:
        log.info(f"[DEDUP INTER-SOURCES] {doublons_retires} doublon(s) inter-sources retire(s)")

    return resultat

def normaliser_ao(ao, source):
    pays_map = {"SBEE": "Benin", "AfDB": "Afrique", "DGCMEF": "Burkina Faso", "TuniSurf": "Tunisie"}
    pays = next((v for k, v in pays_map.items() if k in source), "Inconnu")
    # AfDB peut fournir un pays plus précis depuis la page détail
    if "AfDB" in source and ao.get("pays_detail"):
        pays = ao["pays_detail"]
    # [v10.17] World Bank fournit toujours un pays reel (project_ctry_name)
    if "World Bank" in source and ao.get("pays"):
        pays = ao["pays"]
    # AFD DGMarket fournit toujours un pays reel (colonne "Pays" du tableau)
    if "DGMarket" in source and ao.get("pays"):
        pays = ao["pays"]
    # OPEC Fund fournit toujours un pays reel (colonne "Country" du tableau)
    if "OPEC" in source and ao.get("pays"):
        pays = ao["pays"]
    if "IsDB" in source and ao.get("pays"):
        pays = ao["pays"]
    if "TUNEPS" in source and ao.get("pays"):
        pays = ao["pays"]
    if "DevelopmentAid" in source and ao.get("pays"):
        pays = ao["pays"]
        if pays == "Tunisia":
            pays = "Tunisie"
    # GlobalTenders fournit toujours un pays reel (extrait de la carte)
    if "GlobalTenders" in source and ao.get("pays"):
        pays = ao["pays"]
    # J360 fournit toujours un pays reel (detecte dans le titre/bloc
    # de la carte AO -- cf. _detecter_pays_cible dans scrapers/j360.py)
    if "J360" in source and ao.get("pays"):
        pays = ao["pays"]
    return {
        "source":         source,
        "pays":            pays,
        "titre":           ao.get("titre", "Sans titre")[:300],
        "reference":       ao.get("reference", ""),
        "type_marche":     ao.get("type_marche", ""),
        "date_pub":        ao.get("date_publication") or ao.get("date_pub", ""),
        "date_limite":     ao.get("date_limite", ""),
        "url_avis":        ao.get("lien_avis", ao.get("lien", "")),
        "url_dossier":     ao.get("url_dossier", ao.get("lien_dossier", "")),
        "pdf_local":       ao.get("pdf_local", ""),
        "page_pdf":        ao.get("page_pdf", ""),
        "date_ajout":      datetime.now().strftime("%d/%m/%Y %H:%M"),
        "caution":         ao.get("caution", ""),
        "acheteur_public": ao.get("acheteur_public", ""),
        "lien_generique":  ao.get("lien_generique", False),
    }


def generer_id_ao(ao):
    return hashlib.md5(
        (ao.get("titre", "") + ao.get("url_avis", "") + ao.get("source", "")).encode("utf-8")
    ).hexdigest()


def charger_historique(path):
    if not os.path.exists(path):
        log.info(f"[HISTORIQUE] Aucun fichier {path} trouve -> historique vide")
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            vus = set(data.get("vus", []))
            log.info(f"[HISTORIQUE] {len(vus)} entree(s) chargee(s) depuis {path} (derniere maj : {data.get('derniere_maj','?')})")
            return vus
    except Exception as e:
        log.error(f"[HISTORIQUE] Erreur lecture {path} : {e}")
        return set()


def sauvegarder_historique(path, vus):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"vus": list(vus), "derniere_maj": str(datetime.now()), "total": len(vus)},
                      f, ensure_ascii=False, indent=2)
        log.info(f"[HISTORIQUE] Sauvegarde OK -> {path} ({len(vus)} entrees)")
    except Exception as e:
        log.error(f"[HISTORIQUE] Erreur sauvegarde historique : {e}")


def afficher(ao):
    print("\n" + "=" * 65)
    print(f"  SOURCE      : {ao.get('source', 'N/A')}")
    print(f"  TITRE       : {ao.get('titre', 'N/A')}")
    if ao.get("reference"):    print(f"  REFERENCE   : {ao['reference']}")
    if ao.get("type_marche"):  print(f"  TYPE        : {ao['type_marche']}")
    if ao.get("date_pub"):     print(f"  PUBLICATION : {ao['date_pub']}")
    if ao.get("date_limite"):  print(f"  LIMITE DEPOT: {ao['date_limite']}")
    if ao.get("url_avis"):
        page = ao.get("page_pdf", "")
        label = f"  PAGE {page} (lien direct)" if page else "  AVIS / LIEN"
        print(f"{label} : {ao['url_avis']}")
    if ao.get("url_dossier"):  print(f"  PDF COMPLET : {ao['url_dossier']}")
    if ao.get("pdf_local"):    print(f"  PDF LOCAL   : {ao['pdf_local']}")
    print("=" * 65)