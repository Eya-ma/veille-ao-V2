"""Scraper DevelopmentAid.org (Playwright, contenu public limite).
Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import traceback
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import CONFIG, DELAI_MIN_JOURS_DEVAID, _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, log
from utils import normaliser_texte, _pays_est_afrique_cible
from historique import deduplicer

_MOIS_ABBR_EN_DEVAID = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date_devaid(texte):
    """Parse les dates DevelopmentAid, ex: 'Jul 30, 2026', 'Aug 13, 2026'
    (mois abrege anglais SANS point, contrairement a OPEC Fund)."""
    if not texte:
        return None
    texte = texte.strip()
    m = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})', texte)
    if not m:
        log.debug(f"[DEVAID DATE] Echec parsing pour valeur brute : {texte!r}")
        return None
    mois_brut, jour, annee = m.groups()
    mois_num = _MOIS_ABBR_EN_DEVAID.get(mois_brut.lower()[:3])
    if not mois_num:
        log.debug(f"[DEVAID DATE] Mois non reconnu : {mois_brut!r}")
        return None
    try:
        return date(int(annee), mois_num, int(jour))
    except ValueError:
        return None


def _pays_devaid_matches(lieu_brut):
    """
    Verifie si lieu_brut (ex: 'Kenya, Uganda' ou 'Eswatini (Swaziland)')
    correspond a au moins un pays d'Afrique (liste complete, pas de
    whitelist restreinte). Gere :
      - les listes multi-pays separees par virgule
      - les suffixes entre parentheses ('Eswatini (Swaziland)' -> 'Eswatini')
    Retourne le libelle du 1er match trouve, ou None.
    """
    if not lieu_brut:
        return None
    for morceau in lieu_brut.split(","):
        morceau_propre = re.sub(r'\([^)]*\)', '', morceau).strip()
        canon = _pays_est_afrique_cible(morceau_propre)
        if canon:
            return canon
    return None



def scraper_developmentaid():
    resultats = []
    url = (
        "https://www.developmentaid.org/tenders/search"
        "?hiddenAdvancedFilters=0&tenderTypes=2,1&sectors=6,85,20"
        "&locations=3&statuses=3"
    )
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_DEVAID)

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING DevelopmentAid.org (Playwright)")
    print(f"#  Deadline minimum : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_DEVAID}j)")
    print("#" * 70)
    log.info("DevelopmentAid - ===== DEBUT SCRAPING =====")

    compteurs = {
        "total_liens_bruts": 0,
        "rejet_href_pas_tender": 0,
        "total_cartes_valides": 0,
        "rejet_pays": 0,
        "rejet_signal_electrique": 0,
        "rejet_domaine_bloque": 0,
        "rejet_deadline_absente": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus": 0,
    }
    pays_rejetes = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CONFIG.get("tuneps_headless", True))
            page = browser.new_page()
            page.set_default_timeout(30000)

            print(f"\n>>> Navigation vers {url}")
            page.goto(url, wait_until="networkidle")

            try:
                print(">>> Clic sur '300' resultats par page")
                page.get_by_text("300", exact=True).click()
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f">>> Impossible de cliquer '300' ({e}) -> on continue")
                log.warning(f"DevelopmentAid - clic '300' resultats/page echoue : {e}")

            try:
                page.wait_for_selector("text=/results/i", timeout=15000)
            except PlaywrightTimeoutError:
                print(">>> Compteur de resultats non trouve apres 15s")

            tous_les_a = page.locator("a")
            nb_a = tous_les_a.count()
            compteurs["total_liens_bruts"] = nb_a
            print(f">>> {nb_a} lien(s) <a> trouve(s) sur la page")
            liens_deja_vus = set()

            for i in range(nb_a):
                a_tag = tous_les_a.nth(i)

                href = a_tag.get_attribute("href") or ""
                if "/tenders/" not in href.lower():
                    compteurs["rejet_href_pas_tender"] += 1
                    continue
                if href.lower().rstrip("/").endswith(("/tenders/search", "/tenders/publish", "/tenders")):
                    compteurs["rejet_href_pas_tender"] += 1
                    continue

                try:
                    titre = a_tag.inner_text().strip()
                except Exception:
                    continue
                if len(titre) < 15:
                    continue

                conteneur = a_tag.locator("xpath=ancestor::*[.//text()[contains(., 'Status:')]][1]")
                if conteneur.count() == 0:
                    continue

                texte_bloc = conteneur.first.inner_text()
                if "Status:" not in texte_bloc or "Deadline:" not in texte_bloc:
                    continue

                if len(texte_bloc) > 1000:
                    continue

                compteurs["total_cartes_valides"] += 1
                print(f"\n  --- Tender [{compteurs['total_cartes_valides']}] ---")
                print(f"    TITRE : {titre!r}")

                lien_avis = href if href.startswith("http") else "https://www.developmentaid.org" + href

                if lien_avis in liens_deja_vus:
                    continue
                liens_deja_vus.add(lien_avis)

                m_categorie= re.search(r'Category:\s*([^\n]+)', texte_bloc)
                m_statut   = re.search(r'Status:\s*([^\n]+)', texte_bloc)
                m_lieu     = re.search(r'Location:\s*([^\n]+)', texte_bloc)
                m_deadline = re.search(r'Deadline:\s*([^\n]+)', texte_bloc)

                categorie = m_categorie.group(1).strip() if m_categorie else ""
                statut    = m_statut.group(1).strip()    if m_statut    else ""
                lieu_brut = m_lieu.group(1).strip()      if m_lieu      else ""
                deadline_brut = m_deadline.group(1).strip() if m_deadline else ""

                print(f"    CATEGORIE={categorie!r} | STATUT={statut!r} | LIEU={lieu_brut!r} | DEADLINE={deadline_brut!r}")

                if statut and statut.lower() != "open":
                    print("    RESULTAT : ❌ REJETE (statut != Open)")
                    continue

                pays_canon = _pays_devaid_matches(lieu_brut)
                if not pays_canon:
                    compteurs["rejet_pays"] += 1
                    if lieu_brut:
                        pays_rejetes.add(lieu_brut)
                    print(f"    RESULTAT : ❌ REJETE (pays {lieu_brut!r} hors Afrique)")
                    continue

                titre_norm = normaliser_texte(titre)
                if not _RE_SIGNAL_ELECTRIQUE.search(titre_norm):
                    compteurs["rejet_signal_electrique"] += 1
                    print("    RESULTAT : ❌ REJETE (pas de signal electrique dans le titre)")
                    continue

                if _DOMAINES_BLOQUES.search(titre):
                    compteurs["rejet_domaine_bloque"] += 1
                    print("    RESULTAT : ❌ REJETE (domaine bloque)")
                    continue

                date_limite_obj = _parse_date_devaid(deadline_brut)
                if not date_limite_obj:
                    compteurs["rejet_deadline_absente"] += 1
                    print(f"    RESULTAT : ❌ REJETE (deadline non parsee : {deadline_brut!r})")
                    continue
                if date_limite_obj < seuil_deadline:
                    compteurs["rejet_deadline_trop_proche"] += 1
                    print(f"    RESULTAT : ❌ REJETE (deadline {date_limite_obj} < seuil {seuil_deadline})")
                    continue

                compteurs["retenus"] += 1
                print("    RESULTAT : ✅ ACCEPTE")
                log.info(f"DevelopmentAid - AO RETENU [{pays_canon}] : {titre} | limite={date_limite_obj}")

                resultats.append({
                    "titre":            titre,
                    "reference":        "",
                    "type_marche":      categorie,
                    "date_publication": "",
                    "date_limite":      date_limite_obj.strftime("%d/%m/%Y"),
                    "lien_avis":        lien_avis,
                    "lien_dossier":     "",
                    "pays":             pays_canon,
                })

            browser.close()

    except Exception as e:
        print(f"\n!!! ERREUR DevelopmentAid : {e}")
        log.error(f"DevelopmentAid - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("DevelopmentAid - ===== BILAN =====")
    log.info(f"DevelopmentAid - retenus : {compteurs['retenus']}")
    if pays_rejetes:
        log.info(f"DevelopmentAid - pays rejetes (non whitelistes) : {sorted(pays_rejetes)}")
    print(f"\n#  FIN SCRAPING DevelopmentAid -> {len(resultats)} AO retenus\n")
    return deduplicer(resultats)
