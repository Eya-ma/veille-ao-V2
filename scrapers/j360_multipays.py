"""
Scraper J360 multi-pays complet : mapping pays -> slug URL, scraping
par pays (le site n'autorise qu'un seul pays a la fois), et filtre
d'exclusion post-scraping (electromenager/IT que le secteur "Equipements
electriques et eclairage" remonte aussi).

Ne modifie JAMAIS scrapers/j360.py -- reutilise seulement les elements
de niveau module deja definis la-bas (regex, user-agent, gestion du
defi Anubis) et duplique volontairement la boucle de pagination /
extraction, celle-ci vivant a l'interieur du corps de scraper_j360()
et ne pouvant pas etre importee sans dupliquer du code.

Schema d'URL confirme :
  https://www.j360.info/appels-d-offres/afrique/{slug}/?act={secteur}&page={n}
"""

import re
import re
import traceback
from datetime import date, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import CONFIG, DELAI_MIN_JOURS_J360, DELAI_MIN_JOURS_J360_TUNISIE, log
from utils import parse_date
from filtrage import valider_ao_structure
from scrapers.j360 import _attendre_challenge_anubis, _RE_LIEN_AO, _RE_DATE, _UA_DESKTOP
from scrapers.j360_auth import se_connecter

SLUGS_PAYS_J360 = {
    # Afrique de l'Ouest
    "Benin": "benin",                                          # confirme
    "Burkina Faso": "burkina-faso",                            # confirme
    "Niger": "niger",
    "Mali": "mali",
    "Senegal": "senegal",
    "Guinea": "guinee",
    "Guinea-Bissau": "guinee-bissau",                          # confirme
    "Sierra Leone": "sierra-leone",
    "Liberia": "liberia",
    "Cote d'Ivoire": "cote-divoire",                           # confirme
    "Ghana": "ghana",
    "Togo": "togo",
    "Gambia, The": "gambie",
    "Cabo Verde": "cap-vert",
    "Mauritania": "mauritanie",
    "Nigeria": "nigeria",
    # Afrique Centrale
    "Cameroon": "cameroun",                                    # confirme
    "Chad": "tchad",
    "Central African Republic": "republique-centrafricaine",  # [A VERIFIER]
    "Congo, Republic of": "congo",                             # confirme mais ambigu
    "Gabon": "gabon",
    # Afrique de l'Est
    "Kenya": "kenya",
    "Uganda": "ouganda",
    "Tanzania": "tanzanie",
    "Rwanda": "rwanda",
    "Burundi": "burundi",
    "Somalia": "somalie",
    "Djibouti": "djibouti",
    # Afrique du Nord
    "Egypt, Arab Republic of": "egypte",
    "Libya": "libye",
    "Tunisia": "tunisie",
    "Algeria": "algerie",
}

_URL_BASE = "https://www.j360.info/appels-d-offres/afrique"
_FILTRE_SECTEUR = "equipements-electriques-et-eclairage"
_DELAI_ENTRE_PAYS_MS = 3000
NB_PAGES_MAX_PAR_PAYS = 9


def _construire_url(slug_pays, num_page):
    return f"{_URL_BASE}/{slug_pays}/?act={_FILTRE_SECTEUR}&page={num_page}"

def _seuil_deadline_pour_pays(nom_pays):
    """Tunisie : deadline mini = aujourd'hui + DELAI_MIN_JOURS_J360_TUNISIE.
    Reste de l'Afrique : aujourd'hui + DELAI_MIN_JOURS_J360."""
    jours = DELAI_MIN_JOURS_J360_TUNISIE if nom_pays == "Tunisia" else DELAI_MIN_JOURS_J360
    return date.today() + timedelta(days=jours)


def _filtrer_hors_champ(resultats):
    conserves, exclus = [], []
    for ao in resultats:
        titre = ao.get("titre", "")
        if valider_ao_structure(titre):
            conserves.append(ao)
        else:
            exclus.append(ao)

    if exclus:
        print(f">>> J360 - {len(exclus)} AO exclu(s) (hors champ electrique) :")
        for ao in exclus:
            print(f"    ❌ {ao.get('titre', '')[:90]}")
        log.info(f"J360 - {len(exclus)} AO exclu(s) par filtre hors-champ")

    return conserves


def scraper_j360_multipays():
    resultats = []

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING J360 MULTI-PAYS (Playwright)")
    print(f"#  Pays cibles      : {len(SLUGS_PAYS_J360)}")
    print(f"#  Deadline minimum : {DELAI_MIN_JOURS_J360_TUNISIE}j (Tunisie) / {DELAI_MIN_JOURS_J360}j (reste Afrique)")
    print(f"#  Mode headless    : {CONFIG.get('j360_headless', True)}")
    print("#" * 70)
    log.info("J360 multi-pays - ===== DEBUT SCRAPING =====")

    compteurs = {
        "total_liens": 0,
        "rejet_deja_vu": 0,
        "rejet_pas_marche_en_cours": 0,
        "rejet_national": 0,
        "rejet_deadline_absente": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus": 0,
    }
    liens_vus = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CONFIG.get("j360_headless", True))
            context = browser.new_context(user_agent=_UA_DESKTOP, locale="fr-FR")
            page = context.new_page()
            page.set_default_timeout(30000)

            connecte = se_connecter(
                page, CONFIG.get("j360_email", ""), CONFIG.get("j360_password", ""),
                _attendre_challenge_anubis,
            )
            if not connecte:
                print(">>> Connexion echouee ou identifiants absents -> arret du scraping multi-pays")
                log.warning("J360 multi-pays - connexion non confirmee, arret")
                browser.close()
                return []

            for nom_pays, slug_pays in SLUGS_PAYS_J360.items():
                print(f"\n{'=' * 70}")
                print(f"  J360 MULTI-PAYS - {nom_pays} ({slug_pays})")
                print(f"{'=' * 70}")
                log.info(f"J360 multi-pays - ===== pays : {nom_pays} =====")

                seuil_deadline_pays = _seuil_deadline_pour_pays(nom_pays)
                print(f">>> Seuil deadline pour {nom_pays} : {seuil_deadline_pays}")

                num_page = 1
                while num_page <= NB_PAGES_MAX_PAR_PAYS:
                    url = _construire_url(slug_pays, num_page)
                    print(f">>> Navigation vers {url}")
                    log.info(f"J360 multi-pays - {nom_pays} page {num_page} : {url}")

                    page.goto(url, wait_until="domcontentloaded")

                    if not _attendre_challenge_anubis(page):
                        print(">>> BLOQUE par Anubis -> arret pour ce pays")
                        log.warning(f"J360 multi-pays - {nom_pays} bloque par Anubis")
                        break

                    try:
                        page.wait_for_selector("#spinner", state="hidden", timeout=20000)
                    except PlaywrightTimeoutError:
                        print(">>> #spinner toujours visible ou absent apres 20s (continue quand meme)")

                    try:
                        page.wait_for_selector("div.card.results-item", timeout=15000)
                    except PlaywrightTimeoutError:
                        print(">>> AUCUNE carte d'AO detectee -> fin pour ce pays")
                        log.info(f"J360 multi-pays - {nom_pays} aucune carte page {num_page}, arret pagination")
                        break

                    # Chaque AO est une carte "div.card.results-item"
                    # (microdata schema.org/Demand). Le titre et le lien
                    # public stable sont dans des balises <meta> (fiables,
                    # independantes de l'affichage connecte/anonyme -- le
                    # lien <a> cliquable, lui, pointe vers app.j360.info/
                    # my-monitoring une fois connecte, format qu'on ne veut
                    # pas stocker dans l'Excel). La date limite est dans
                    # [itemprop='validThrough'], attribut datetime ISO.
                    cartes = page.locator("div.card.results-item")
                    nb_cartes = cartes.count()
                    print(f">>> {nb_cartes} carte(s) d'AO trouvee(s)")

                    if nb_cartes == 0:
                        print(">>> Plus aucun resultat exploitable -> pays suivant")
                        break

                    compteurs["total_liens"] += nb_cartes

                    for i in range(nb_cartes):
                        carte = cartes.nth(i)

                        titre = ""
                        el_titre = carte.locator("meta[itemprop='name']")
                        if el_titre.count() > 0:
                            titre = (el_titre.first.get_attribute("content") or "").strip()

                        # Ne garder que les AO reellement ouverts (badge vert
                        # "Marche en cours"), pas les resultats de marches
                        # deja attribues, appels a projets, ou archives --
                        # tous types confondus sur la page de recherche J360.
                        badge = ""
                        el_badge = carte.locator("span.badge")
                        if el_badge.count() > 0:
                            badge = el_badge.first.inner_text().strip()
                        if "en cours" not in badge.lower():
                            compteurs["rejet_pas_marche_en_cours"] += 1
                            continue

                        # Exclusion des AO "National" (comme pour GlobalTenders)
                        # ex: "AVIS D'APPEL D'OFFRES OUVERT NATIONAL Nᵒ ABER/..."
                        if re.search(r'\bnational\b', titre, re.IGNORECASE):
                            compteurs["rejet_national"] += 1
                            continue

                        url_avis = ""
                        el_url = carte.locator("meta[itemprop='url']")
                        if el_url.count() > 0:
                            url_avis = (el_url.first.get_attribute("content") or "").strip()

                        if not titre or not url_avis:
                            continue

                        if url_avis in liens_vus:
                            compteurs["rejet_deja_vu"] += 1
                            continue
                        liens_vus.add(url_avis)

                        date_limite = ""
                        el_deadline = carte.locator("[itemprop='validThrough']")
                        if el_deadline.count() > 0:
                            iso = el_deadline.first.get_attribute("datetime") or ""
                            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
                            if m:
                                date_limite = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
                            else:
                                date_limite = el_deadline.first.inner_text().strip()

                        if not date_limite:
                            compteurs["rejet_deadline_absente"] += 1
                            continue

                        date_limite_obj = parse_date(date_limite)
                        if date_limite_obj and date_limite_obj < seuil_deadline_pays:
                            compteurs["rejet_deadline_trop_proche"] += 1
                            continue

                        compteurs["retenus"] += 1
                        resultats.append({
                            "titre": titre,
                            "pays": nom_pays,
                            "date_pub": "",
                            "date_limite": date_limite,
                            "url_avis": url_avis,
                            "url_dossier": url_avis,
                        })

                    num_page += 1

                page.wait_for_timeout(_DELAI_ENTRE_PAYS_MS)

            browser.close()

    except Exception as e:
        print(f"\n❌ ERREUR J360 multi-pays : {e}")
        log.error(f"J360 multi-pays - erreur : {e}")
        log.error(traceback.format_exc())

    print(f"\n{'=' * 70}")
    print("  J360 MULTI-PAYS - RECAPITULATIF")
    print(f"{'=' * 70}")
    for cle, valeur in compteurs.items():
        print(f"  {cle:30s} : {valeur}")
    log.info(f"J360 multi-pays - RESULTAT FINAL AVANT FILTRE HORS-CHAMP : {len(resultats)} AO")

    resultats = _filtrer_hors_champ(resultats)
    log.info(f"J360 multi-pays - RESULTAT FINAL APRES FILTRE HORS-CHAMP : {len(resultats)} AO retenus")
    return resultats