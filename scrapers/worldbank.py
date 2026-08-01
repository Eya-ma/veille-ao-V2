"""Scraper World Bank (API JSON procnotices). Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import time
import json
import traceback
from datetime import date, timedelta

import requests

from config import HEADERS, PAYS_AFRIQUE_CIBLE, NOTICE_TYPES_CIBLE, log
from utils import session, parse_date
from filtrage import valider_ao_structure
from historique import deduplicer

def _notice_type_ok(notice_type):
    return (notice_type or "").strip().lower() in NOTICE_TYPES_CIBLE


def _date_str_wb(d):
    return d.strftime("%d/%m/%Y") if d else ""


def scraper_worldbank():
    """
    Scrape l'API JSON World Bank (procnotices).

    Fonctionnalités :
    - Récupération des appels d'offres via l'API World Bank.
    - Filtrage par type d'avis, pays africains ciblés et domaine électricité.
    - Filtrage basé sur la date limite de dépôt :
      seuls les AO avec une échéance d'au moins 7 jours
      sont conservés.
    - Pagination complète avec protection anti-boucle.

   Pipeline de filtrage :
   1. Type d'avis cible.
   2. Pays africain éligible.
   3. Date limite de dépôt valide (>= aujourd'hui + 7 jours).
   4. Validation du domaine électricité.
"""
    resultats = []
    url = "https://search.worldbank.org/api/v2/procnotices"
    rows = 500
    offset = 0

    DELAI_MIN_JOURS = 14
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS)

    log.info("World Bank - ===== DEBUT SCRAPING =====")
    log.info(f"World Bank - URL API : {url}")
    log.info(f"World Bank - [MODIFIÉ] filtre sur submission_deadline_date >= {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS}j)")
    log.info(f"World Bank - notice_types cibles : {sorted(NOTICE_TYPES_CIBLE)}")
    log.info(f"World Bank - nombre de pays dans la whitelist : {len(PAYS_AFRIQUE_CIBLE)}")

    pays_rejetes = set()
    compteurs = {
        "total_notices_recues": 0,
        "rejet_notice_type": 0,
        "rejet_pays": 0,
        "rejet_deadline_absente_ou_passee": 0,
        "rejet_deadline_trop_proche": 0,
        "rejet_signal_electrique": 0,
        "retenus": 0,
    }
    exemples_notice_type_vus = set()
    pages_traitees = 0

    try:
        while True:
            params = {"format": "json", "rows": rows, "os": offset}
            log.info(f"World Bank - requete API : offset={offset}, rows={rows}")
            t0 = time.time()
            try:
                r = session.get(url, headers=HEADERS, params=params, timeout=60)
            except requests.exceptions.RequestException as e:
                log.error(f"World Bank - ECHEC REQUETE HTTP (offset={offset}) : {type(e).__name__}: {e}")
                log.error(traceback.format_exc())
                break
            log.info(f"World Bank - requete terminee en {time.time() - t0:.2f}s")
            log.info(f"World Bank - HTTP {r.status_code} | taille reponse : {len(r.content)} octets | content-type : {r.headers.get('Content-Type')}")

            if r.status_code != 200:
                log.error(f"World Bank - STATUT HTTP ANORMAL : {r.status_code}")
                log.error(f"World Bank - corps de reponse (1000 premiers caracteres) : {r.text[:1000]}")
                break

            try:
                data = r.json()
            except json.JSONDecodeError as e:
                log.error(f"World Bank - ECHEC PARSING JSON : {e}")
                log.error(f"World Bank - corps brut recu (1000 premiers caracteres) : {r.text[:1000]}")
                break

            log.info(f"World Bank - cles racine du JSON recu : {list(data.keys())}")
            if "total" in data:
                log.info(f"World Bank - 'total' annonce par l'API : {data.get('total')}")

            notices = data.get("procnotices", {})
            if isinstance(notices, dict):
                log.info(f"World Bank - 'procnotices' recu comme dict ({len(notices)} entrees) -> conversion en liste")
                notices = list(notices.values())
            elif isinstance(notices, list):
                log.info(f"World Bank - 'procnotices' recu comme liste ({len(notices)} entrees)")
            else:
                log.warning(f"World Bank - type INATTENDU pour 'procnotices' : {type(notices)} -> traite comme vide")
                notices = []

            if not notices:
                log.info(f"World Bank - aucune notice recue a offset={offset} -> fin de pagination")
                break

            pages_traitees += 1
            compteurs["total_notices_recues"] += len(notices)
            log.info(f"World Bank - offset {offset} : {len(notices)} notices a traiter (page n°{pages_traitees})")

            if offset == 0 and notices:
                try:
                    echantillon = json.dumps(notices[0], indent=2, ensure_ascii=False)
                    log.info(f"World Bank - EXEMPLE DE NOTICE BRUTE (1ere de la page 0) :\n{echantillon[:2500]}")
                except Exception as e:
                    log.warning(f"World Bank - impossible de dumper l'exemple de notice : {e}")

            for n_idx, n in enumerate(notices):
                notice_type = n.get("notice_type", "")
                exemples_notice_type_vus.add(notice_type)

                if not _notice_type_ok(notice_type):
                    compteurs["rejet_notice_type"] += 1
                    log.debug(f"World Bank - [offset={offset}, idx={n_idx}] rejet notice_type={notice_type!r}")
                    continue

                pays = n.get("project_ctry_name", "") or n.get("countryname", "")
                if pays not in PAYS_AFRIQUE_CIBLE:
                    compteurs["rejet_pays"] += 1
                    if pays:
                        pays_rejetes.add(pays)
                    log.debug(f"World Bank - [offset={offset}, idx={n_idx}] rejet pays={pays!r} (hors whitelist)")
                    continue

                # [MODIFIÉ] Filtre sur submission_deadline_date au lieu de noticedate
                deadline_brut = (n.get("submission_deadline_date", "") or "")
                date_limite_obj = parse_date(deadline_brut[:10]) if deadline_brut else None

                if not date_limite_obj:
                    compteurs["rejet_deadline_absente_ou_passee"] += 1
                    log.debug(
                        f"World Bank - [offset={offset}, idx={n_idx}] rejet : "
                        f"submission_deadline_date absente/non parsee (brut={deadline_brut!r})"
                    )
                    continue

                if date_limite_obj < seuil_deadline:
                    compteurs["rejet_deadline_trop_proche"] += 1
                    log.debug(
                        f"World Bank - [offset={offset}, idx={n_idx}] rejet : "
                        f"date_limite={date_limite_obj} < seuil={seuil_deadline} "
                        f"(deja expire ou moins de {DELAI_MIN_JOURS}j restants)"
                    )
                    continue

                titre = n.get("bid_description", "") or n.get("project_name", "") or "Sans titre"
                contexte = n.get("project_name", "")

                if not valider_ao_structure(titre, contexte):
                    compteurs["rejet_signal_electrique"] += 1
                    log.debug(f"World Bank - [offset={offset}, idx={n_idx}] rejet signal electrique : titre={titre[:80]!r} | pays={pays}")
                    continue

                wb_id = n.get("id", "")
                jours_restants = (date_limite_obj - date.today()).days
                compteurs["retenus"] += 1
                log.info(
                    f"World Bank - AO RETENU [{pays}] : {titre[:90]} | notice_type={notice_type} | "
                    f"date_limite={date_limite_obj} ({jours_restants}j restants)"
                )
                resultats.append({
                    "titre":            titre,
                    "reference":        n.get("bid_reference_no", ""),
                    "type_marche":      notice_type,
                    "date_publication": (n.get("noticedate", "") or ""),
                    "date_limite":      _date_str_wb(date_limite_obj),
                    "lien_avis":        f"https://projects.worldbank.org/procurement/noticeoverview?id={wb_id}&lang=en",
                    "lien_dossier":     n.get("contact_web_url", ""),
                    "pays":             pays,
                })


            offset += rows
            if offset > 5000:
                log.warning("World Bank - garde-fou anti-boucle atteint (offset > 5000) -> arret force")
                break

    except Exception as e:
        log.error(f"World Bank - ERREUR INATTENDUE : {e}")
        log.error(traceback.format_exc())

    # ── Bilan final ──
    log.info("World Bank - ===== BILAN FILTRAGE =====")
    log.info(f"World Bank - pages API traitees                        : {pages_traitees}")
    log.info(f"World Bank - notices recues au total                    : {compteurs['total_notices_recues']}")
    log.info(f"World Bank - rejetees (notice_type)                     : {compteurs['rejet_notice_type']}")
    log.info(f"World Bank - rejetees (pays hors whitelist)             : {compteurs['rejet_pays']}")
    log.info(f"World Bank - rejetees (deadline absente/non parsee)     : {compteurs['rejet_deadline_absente_ou_passee']}")
    log.info(f"World Bank - rejetees (deadline < {DELAI_MIN_JOURS}j ou passee)      : {compteurs['rejet_deadline_trop_proche']}")
    log.info(f"World Bank - rejetees (pas de signal elec.)             : {compteurs['rejet_signal_electrique']}")
    log.info(f"World Bank - RETENUS                                     : {compteurs['retenus']}")

    if exemples_notice_type_vus:
        log.info(f"World Bank - valeurs distinctes de notice_type rencontrees ({len(exemples_notice_type_vus)}) : {sorted(exemples_notice_type_vus)}")
    if pays_rejetes:
        log.info(f"World Bank - pays rencontres rejetes (hors whitelist, {len(pays_rejetes)} valeur(s) distincte(s)) : {sorted(pays_rejetes)}")
    else:
        log.info("World Bank - aucun pays rejete (soit aucune notice recue, soit tous les pays etaient deja dans la whitelist)")

    log.info(f"World Bank - RESULTAT FINAL : {len(resultats)} AO retenus")
    return deduplicer(resultats)
