"""Scraper OPEC Fund (HTML statique, page unique). Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import traceback
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from config import (
    CONFIG, HEADERS, PAYS_AFRIQUE_CIBLE, DELAI_MIN_JOURS_OPECFUND,
    _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, _MOIS_EN_OPECFUND, log,
)
from utils import session, normaliser_texte, verifier_lien
from historique import deduplicer

def _parse_date_opecfund(texte):
    """Parse les dates OPEC Fund, ex: 'June 29, 2026', 'August 11, 2026'.
    Retourne None pour les valeurs non-dates ('N/A', 'Not Applicable', vide)."""
    if not texte:
        return None
    texte = texte.strip()
    if not texte or texte.lower() in ("n/a", "not applicable", "-"):
        return None
    m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', texte)
    if not m:
        log.debug(f"[OPECFUND DATE] Echec parsing pour valeur brute : {texte!r}")
        return None
    mois_brut, jour, annee = m.groups()
    mois_num = _MOIS_EN_OPECFUND.get(mois_brut.lower())
    if not mois_num:
        log.debug(f"[OPECFUND DATE] Mois non reconnu : {mois_brut!r} (texte brut={texte!r})")
        return None
    try:
        return date(int(annee), mois_num, int(jour))
    except ValueError:
        log.debug(f"[OPECFUND DATE] Date invalide construite depuis {texte!r}")
        return None

# ═══════════════════════════════════════════════════════════════

_RE_SECTEUR_ENERGY = re.compile(r"\benergy\b", re.IGNORECASE)


def scraper_opecfund():
    resultats = []
    url = "https://opecfund.org/work-with-us/project-procurement/current-opportunities"
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_OPECFUND)

    log.info("OPEC Fund - ===== DEBUT SCRAPING =====")
    log.info(f"OPEC Fund - URL cible : {url}")
    log.info(
        f"OPEC Fund - deadline minimum : {seuil_deadline} "
        f"(aujourd'hui + {DELAI_MIN_JOURS_OPECFUND}j) | filtre Sector=Energy | "
        f"filtre pays : {len(PAYS_AFRIQUE_CIBLE)} pays whitelistes (memes que World Bank)"
    )

    compteurs = {
        "total_lignes": 0,
        "rejet_secteur": 0,
        "rejet_pays": 0,
        "rejet_signal_electrique": 0,
        "rejet_domaine_bloque": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus_sans_deadline_fallback": 0,
        "retenus": 0,
        "liens_verifies_ok": 0,
        "liens_verifies_casses": 0,
    }
    pays_rejetes = set()

    try:
        r = session.get(url, headers=HEADERS, timeout=CONFIG["timeout"])
        r.raise_for_status()
        log.info(f"OPEC Fund - HTTP {r.status_code} | taille reponse : {len(r.text)} caracteres")
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", class_="table")
        if not table:
            log.warning("OPEC Fund - AUCUN tableau trouve -> la structure du site a peut-etre change")
            return []
        tbody = table.find("tbody")
        lignes = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
        compteurs["total_lignes"] = len(lignes)
        log.info(f"OPEC Fund - {len(lignes)} ligne(s) trouvee(s) dans le tableau")

        for tr in lignes:
            cellules = tr.find_all("td")
            if len(cellules) < 6:
                continue
            date_pub_brut = cellules[0].get_text(strip=True)
            pays          = cellules[1].get_text(strip=True)

            premier_p     = cellules[2].find("p")
            lien_tag      = cellules[2].find("a", href=True)
            if premier_p:
                titre = premier_p.get_text(strip=True)
            else:
                texte_cellule = cellules[2].get_text(separator=" ", strip=True)
                texte_lien    = lien_tag.get_text(strip=True) if lien_tag else ""
                titre = texte_cellule.replace(texte_lien, "").strip() if texte_lien else texte_cellule
            lien_avis = lien_tag["href"] if lien_tag else url
            if lien_avis and not lien_avis.startswith("http"):
                lien_avis = "https://opecfund.org" + lien_avis

            secteur       = cellules[3].get_text(strip=True)
            date_lim_brut = cellules[4].get_text(strip=True)
            type_marche   = cellules[5].get_text(strip=True)

            # -- Filtre 1 : Secteur = Energy --
            if not _RE_SECTEUR_ENERGY.search(secteur):
                compteurs["rejet_secteur"] += 1
                log.debug(f"OPEC Fund - rejet secteur={secteur!r} (pas Energy) : {titre[:60]!r}")
                continue

            # -- Filtre 2 : Pays Afrique --
            if pays not in PAYS_AFRIQUE_CIBLE:
                compteurs["rejet_pays"] += 1
                if pays:
                    pays_rejetes.add(pays)
                log.debug(f"OPEC Fund - rejet pays={pays!r} (hors whitelist) : {titre[:60]!r}")
                continue

            # -- Filtre 3 : signal electricite (titre + secteur) --
            texte_signal = normaliser_texte(titre + " " + secteur)
            if not _RE_SIGNAL_ELECTRIQUE.search(texte_signal):
                compteurs["rejet_signal_electrique"] += 1
                log.debug(f"OPEC Fund - rejet signal electrique : {titre[:60]!r}")
                continue

            if _DOMAINES_BLOQUES.search(titre):
                compteurs["rejet_domaine_bloque"] += 1
                continue

            # -- Filtre 4 : Closing Date >= aujourd'hui + 7j --
            date_limite_obj = _parse_date_opecfund(date_lim_brut)
            if date_limite_obj:
                if date_limite_obj < seuil_deadline:
                    compteurs["rejet_deadline_trop_proche"] += 1
                    continue
            else:
                compteurs["retenus_sans_deadline_fallback"] += 1

            date_pub_obj = _parse_date_opecfund(date_pub_brut)
            date_pub_str = date_pub_obj.strftime("%d/%m/%Y") if date_pub_obj else date_pub_brut

            compteurs["retenus"] += 1
            log.info(
                f"OPEC Fund - AO RETENU : [{pays}] {titre[:70]} | secteur={secteur} | "
                f"limite={date_limite_obj or 'N/A'}"
            )

            lien_ok, lien_statut = verifier_lien(lien_avis)
            if lien_ok:
                compteurs["liens_verifies_ok"] += 1
                log.info(f"OPEC Fund - lien OK ({lien_statut}) : {titre[:60]!r} -> {lien_avis}")
            else:
                compteurs["liens_verifies_casses"] += 1
                log.warning(f"OPEC Fund - LIEN CASSE ({lien_statut}) : {titre[:60]!r} -> {lien_avis}")

            resultats.append({
                "titre":            titre,
                "reference":        "",
                "type_marche":      type_marche,
                "date_publication": date_pub_str,
                "date_limite":      date_limite_obj.strftime("%d/%m/%Y") if date_limite_obj else "",
                "lien_avis":        lien_avis,
                "lien_dossier":     "",
                "pays":             pays,
            })

    except requests.exceptions.RequestException as e:
        log.error(f"OPEC Fund - ECHEC REQUETE HTTP : {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
    except Exception as e:
        log.error(f"OPEC Fund - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("OPEC Fund - ===== BILAN FILTRAGE =====")
    log.info(f"OPEC Fund - lignes totales                  : {compteurs['total_lignes']}")
    log.info(f"OPEC Fund - rejetees (secteur != Energy)     : {compteurs['rejet_secteur']}")
    log.info(f"OPEC Fund - rejetees (pays hors Afrique)     : {compteurs['rejet_pays']}")
    log.info(f"OPEC Fund - rejetees (signal electrique)     : {compteurs['rejet_signal_electrique']}")
    log.info(f"OPEC Fund - rejetees (domaine bloque)        : {compteurs['rejet_domaine_bloque']}")
    log.info(f"OPEC Fund - rejetees (deadline < {DELAI_MIN_JOURS_OPECFUND}j)      : {compteurs['rejet_deadline_trop_proche']}")
    log.info(f"OPEC Fund - conservees sans deadline (fallback) : {compteurs['retenus_sans_deadline_fallback']}")
    log.info(f"OPEC Fund - liens verifies OK                : {compteurs['liens_verifies_ok']}")
    log.info(f"OPEC Fund - liens verifies CASSES            : {compteurs['liens_verifies_casses']}")
    log.info(f"OPEC Fund - RESULTAT FINAL : {compteurs['retenus']} AO retenus")
    if pays_rejetes:
        log.info(f"OPEC Fund - pays rencontres rejetes ({len(pays_rejetes)}) : {sorted(pays_rejetes)}")
    return deduplicer(resultats)
