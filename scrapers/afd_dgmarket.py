"""Scraper AFD DGMarket (HTML statique, pagination via <link rel="next">).
Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import traceback
import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from config import CONFIG, HEADERS, DELAI_MIN_JOURS_DGMARKET, _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, _MOIS_DGMARKET, log
from utils import session, normaliser_texte, _pays_est_afrique_dgmarket
from historique import deduplicer

def _parse_date_dgmarket(texte):
    """Parse les dates AFD DGMarket, ex: 'Jul 1, 2026', 'Aou 25, 2026',
    'Sept 15, 2026' (abbreviations mixtes anglais/francais sans accent)."""
    if not texte:
        return None
    texte_norm = normaliser_texte(texte).lower().strip()
    m = re.search(r'([a-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})', texte_norm)
    if not m:
        log.debug(f"[DGMARKET DATE] Echec parsing pour valeur brute : {texte!r}")
        return None
    mois_brut, jour, annee = m.groups()
    mois_num = (
        _MOIS_DGMARKET.get(mois_brut)
        or _MOIS_DGMARKET.get(mois_brut[:4])
        or _MOIS_DGMARKET.get(mois_brut[:3])
    )
    if not mois_num:
        log.debug(f"[DGMARKET DATE] Mois non reconnu : {mois_brut!r} (texte brut={texte!r})")
        return None
    try:
        return date(int(annee), mois_num, int(jour))
    except ValueError:
        log.debug(f"[DGMARKET DATE] Date invalide construite depuis {texte!r}")
        return None

def scraper_afd_dgmarket():
    resultats = []
    url_base = "https://afd.dgmarket.com/tenders/brandedNoticeList.do"
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_DGMARKET)
    NB_PAGES_MAX = 10

    log.info("AFD DGMarket - ===== DEBUT SCRAPING =====")
    log.info(f"AFD DGMarket - URL cible : {url_base}")
    log.info(
        f"AFD DGMarket - deadline minimum : {seuil_deadline} "
        f"(aujourd'hui + {DELAI_MIN_JOURS_DGMARKET}j)"
    )

    compteurs = {
        "total_lignes": 0,
        "rejet_pays": 0,
        "rejet_signal_electrique": 0,
        "rejet_domaine_bloque": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus_sans_deadline_fallback": 0,
        "retenus": 0,
    }
    
    pays_rejetes = set()
    url_courante = url_base

    try:
        for num_page in range(1, NB_PAGES_MAX + 1):
            log.info(f"AFD DGMarket - page {num_page} : {url_courante}")
            r = session.get(url_courante, headers=HEADERS, timeout=CONFIG["timeout"])
            r.raise_for_status()
            log.info(f"AFD DGMarket - HTTP {r.status_code} | taille reponse : {len(r.text)} caracteres")
            soup = BeautifulSoup(r.text, "lxml")
            table = soup.find("table", id="notice")
            if not table:
                log.warning(f"AFD DGMarket - page {num_page} : AUCUN tableau 'notice' trouve -> arret")
                break
            tbody = table.find("tbody")
            lignes = tbody.find_all("tr") if tbody else []
            compteurs["total_lignes"] += len(lignes)
            log.info(f"AFD DGMarket - page {num_page} : {len(lignes)} ligne(s) trouvee(s)")

            for tr in lignes:
                cellules = tr.find_all("td")
                if len(cellules) < 4:
                    continue
                pays          = cellules[0].get_text(strip=True)
                lien_tag      = cellules[1].find("a", href=True)
                titre         = lien_tag.get_text(strip=True) if lien_tag else cellules[1].get_text(strip=True)
                href          = lien_tag["href"] if lien_tag else ""
                lien_avis     = href if href.startswith("http") else "https://afd.dgmarket.com" + href
                date_pub_brut = cellules[2].get_text(strip=True)
                date_lim_brut = cellules[3].get_text(strip=True)

                pays_canon = _pays_est_afrique_dgmarket(pays)
                if not pays_canon:
                    compteurs["rejet_pays"] += 1
                    if pays:
                        pays_rejetes.add(pays)
                    continue

                titre_norm = normaliser_texte(titre)
                if not _RE_SIGNAL_ELECTRIQUE.search(titre_norm):
                    compteurs["rejet_signal_electrique"] += 1
                    continue

                if _DOMAINES_BLOQUES.search(titre):
                    compteurs["rejet_domaine_bloque"] += 1
                    continue

                date_limite_obj = _parse_date_dgmarket(date_lim_brut)
                if date_limite_obj:
                    if date_limite_obj < seuil_deadline:
                        compteurs["rejet_deadline_trop_proche"] += 1
                        continue
                else:
                    compteurs["retenus_sans_deadline_fallback"] += 1

                date_pub_obj = _parse_date_dgmarket(date_pub_brut)
                date_pub_str = date_pub_obj.strftime("%d/%m/%Y") if date_pub_obj else date_pub_brut

                compteurs["retenus"] += 1
                log.info(
                    f"AFD DGMarket - AO RETENU : [{pays_canon}] {titre[:70]} | "
                    f"limite={date_limite_obj or 'N/A'}"
                )

                resultats.append({
                    "titre":            titre,
                    "reference":        "",
                    "type_marche":      "",
                    "date_publication": date_pub_str,
                    "date_limite":      date_limite_obj.strftime("%d/%m/%Y") if date_limite_obj else "",
                    "lien_avis":        lien_avis,
                    "lien_dossier":     "",
                    "pays":             pays_canon,
                })

            lien_next = soup.find("link", rel="next")
            if lien_next and lien_next.get("href"):
                url_courante = lien_next["href"]
            else:
                log.info(f"AFD DGMarket - pas de page suivante -> fin de pagination (page {num_page})")
                break
        else:
            log.warning(f"AFD DGMarket - garde-fou atteint ({NB_PAGES_MAX} pages) -> arret force")

    except requests.exceptions.RequestException as e:
        log.error(f"AFD DGMarket - ECHEC REQUETE HTTP : {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
    except Exception as e:
        log.error(f"AFD DGMarket - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("AFD DGMarket - ===== BILAN FILTRAGE =====")
    log.info(f"AFD DGMarket - lignes totales scannees      : {compteurs['total_lignes']}")
    log.info(f"AFD DGMarket - rejetees (pays hors Afrique)  : {compteurs['rejet_pays']}")
    log.info(f"AFD DGMarket - rejetees (signal electrique)  : {compteurs['rejet_signal_electrique']}")
    log.info(f"AFD DGMarket - rejetees (domaine bloque)     : {compteurs['rejet_domaine_bloque']}")
    log.info(f"AFD DGMarket - rejetees (deadline < {DELAI_MIN_JOURS_DGMARKET}j)      : {compteurs['rejet_deadline_trop_proche']}")
    log.info(f"AFD DGMarket - conservees sans deadline (fallback) : {compteurs['retenus_sans_deadline_fallback']}")
    log.info(f"AFD DGMarket - RESULTAT FINAL : {compteurs['retenus']} AO retenus")
    if pays_rejetes:
        log.info(f"AFD DGMarket - pays rencontres rejetes ({len(pays_rejetes)}) : {sorted(pays_rejetes)}")
    return deduplicer(resultats)
