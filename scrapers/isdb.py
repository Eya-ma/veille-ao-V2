"""Scraper IsDB (Islamic Development Bank), HTML statique paginee.
Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import traceback
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from config import (
    CONFIG, HEADERS, DELAI_MIN_JOURS_ISDB, NB_PAGES_MAX_ISDB,
    _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, _MOIS_EN_OPECFUND, log,
)
from utils import session, normaliser_texte, _pays_est_afrique_cible
from historique import deduplicer

def _parse_date_isdb(texte):
    """Parse les dates IsDB, format 'D Month YYYY' ex: '2 July 2026',
    '20 November 2025'. Reutilise le dict de mois anglais _MOIS_EN_OPECFUND."""
    if not texte:
        return None
    texte = texte.strip()
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', texte)
    if not m:
        log.debug(f"[ISDB DATE] Echec parsing pour valeur brute : {texte!r}")
        return None
    jour, mois_brut, annee = m.groups()
    mois_num = _MOIS_EN_OPECFUND.get(mois_brut.lower())
    if not mois_num:
        log.debug(f"[ISDB DATE] Mois non reconnu : {mois_brut!r} (texte brut={texte!r})")
        return None
    try:
        return date(int(annee), mois_num, int(jour))
    except ValueError:
        log.debug(f"[ISDB DATE] Date invalide construite depuis {texte!r}")
        return None    

_RE_STATUT_ISDB_ACTIF  = re.compile(r'^\s*(Actif|Active)\s*$', re.IGNORECASE)
_RE_STATUT_ISDB_FERME  = re.compile(r'^\s*(Ferm[eé]|Closed)\s*$', re.IGNORECASE)
_RE_LIEN_TENDER_ISDB   = re.compile(r'/project-procurement/(?:tenders|fr/appels-doffres)/\d{4}/')
_RE_DATE_ISDB          = re.compile(r'\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b')

_RE_TYPE_ISDB_CIBLE = re.compile(
    r"pre.?qualification"
    r"|pr[eé].?qualification"
    r"|specific\s+procurement\s+notice"
    r"|avis\s+(?:de\s+)?(?:passation\s+de\s+march[eé]\s+)?sp[eé]cifique"
    r"|general\s+procurement\s+notice"
    r"|avis\s+g[eé]n[eé]ral\s+de\s+passation\s+de\s+march[eé]"
    r"|\bSPN\b|\bGPN\b",
    re.IGNORECASE,
)

def _scraper_detail_isdb(lien_detail):
    """
    Recupere la date de publication ('Issue Date') depuis la page
    detail d'un avis IsDB.
    """
    if not lien_detail:
        return ""
    try:
        r_det = session.get(lien_detail, headers=HEADERS, timeout=CONFIG["timeout"])
        r_det.raise_for_status()
    except Exception as e:
        log.debug(f"IsDB detail - erreur GET {lien_detail[:60]} : {e}")
        return ""

    soup_det = BeautifulSoup(r_det.text, "lxml")
    texte_page = soup_det.get_text(separator="\n", strip=True)

    m = re.search(
        r'Issue\s+Date\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})',
        texte_page, re.IGNORECASE
    )
    if not m:
        log.debug(f"IsDB detail - 'Issue Date' non trouvee sur {lien_detail[:60]}")
        return ""

    d_pub = _parse_date_isdb(m.group(1))
    return d_pub.strftime("%d/%m/%Y") if d_pub else ""

def scraper_isdb():
    resultats = []
    url_base = "https://www.isdb.org/project-procurement/tenders"
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_ISDB)

    log.info("IsDB - ===== DEBUT SCRAPING =====")
    log.info(f"IsDB - URL de base : {url_base}")
    log.info(
        f"IsDB - pages a couvrir : 0 a {NB_PAGES_MAX_ISDB - 1} ({NB_PAGES_MAX_ISDB} max) | "
        f"deadline minimum : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_ISDB}j)"
    )

    compteurs = {
        "total_lignes": 0,
        "rejet_statut_ferme": 0,
        "rejet_statut_non_reconnu": 0,
        "rejet_type_non_cible": 0,
        "rejet_pays": 0,
        "rejet_signal_electrique": 0,
        "rejet_domaine_bloque": 0,
        "rejet_deadline_absente": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus": 0,
    }
    pays_rejetes = set()

    try:
        for num_page in range(NB_PAGES_MAX_ISDB):
            url_page = f"{url_base}?page={num_page}"
            log.info(f"IsDB - scraping page {num_page} : {url_page}")
            r = session.get(url_page, headers=HEADERS, timeout=CONFIG["timeout"])
            r.raise_for_status()
            log.info(f"IsDB - page {num_page} : HTTP {r.status_code} | {len(r.text)} caracteres")
            soup = BeautifulSoup(r.text, "lxml")

            h2_tenders = [
                h for h in soup.find_all("h2")
                if h.find("a", href=_RE_LIEN_TENDER_ISDB)
            ]
            log.info(f"IsDB - page {num_page} : {len(h2_tenders)} entree(s) de tender trouvee(s)")

            if not h2_tenders:
                log.info(f"IsDB - page {num_page} vide -> arret de la pagination")
                break

            compteurs["total_lignes"] += len(h2_tenders)

            for idx_h, h in enumerate(h2_tenders):
                lien_tag = h.find("a", href=_RE_LIEN_TENDER_ISDB)
                titre    = lien_tag.get_text(strip=True)
                href     = lien_tag["href"]
                lien     = href if href.startswith("http") else "https://www.isdb.org" + href

                conteneur = h.parent
                niveau = 0
                while conteneur is not None and niveau < 5:
                    txt_test = conteneur.get_text(separator="\n", strip=True)
                    if _RE_DATE_ISDB.search(txt_test) and any(
                        _RE_STATUT_ISDB_ACTIF.match(l) or _RE_STATUT_ISDB_FERME.match(l)
                        for l in txt_test.split("\n")
                    ):
                        break
                    conteneur = conteneur.parent
                    niveau += 1

                if conteneur is None:
                    log.debug(f"IsDB - page {num_page}[{idx_h}] conteneur introuvable : {titre[:60]!r}")
                    continue

                texte_complet = conteneur.get_text(separator="\n", strip=True)
                lignes = [l.strip() for l in texte_complet.split("\n") if l.strip()]
                lignes_meta = [l for l in lignes if l != titre]

                statut_ligne = next(
                    (l for l in lignes_meta
                     if _RE_STATUT_ISDB_ACTIF.match(l) or _RE_STATUT_ISDB_FERME.match(l)),
                    None
                )
                date_ligne = next((l for l in lignes_meta if _RE_DATE_ISDB.search(l)), "")

                if not statut_ligne:
                    compteurs["rejet_statut_non_reconnu"] += 1
                    log.debug(f"IsDB - page {num_page}[{idx_h}] statut non trouve : {titre[:60]!r} | lignes={lignes_meta}")
                    continue

                if _RE_STATUT_ISDB_FERME.match(statut_ligne):
                    compteurs["rejet_statut_ferme"] += 1
                    continue

                # -- Type de marche : ligne juste apres le statut --
                type_ligne = ""
                if statut_ligne in lignes_meta:
                    idx_statut = lignes_meta.index(statut_ligne)
                    if idx_statut + 1 < len(lignes_meta):
                        type_ligne = lignes_meta[idx_statut + 1]

                if not _RE_TYPE_ISDB_CIBLE.search(type_ligne):
                    compteurs["rejet_type_non_cible"] += 1
                    log.debug(f"IsDB - page {num_page}[{idx_h}] rejet type={type_ligne!r} (pas Pre-Qual/SPN/GPN) : {titre[:60]!r}")
                    continue

                pays_brut = ""
                if date_ligne in lignes_meta:
                    idx_date = lignes_meta.index(date_ligne)
                    if idx_date > 0:
                        pays_brut = lignes_meta[idx_date - 1]

                pays_canon = _pays_est_afrique_cible(pays_brut)
                if not pays_canon:
                    compteurs["rejet_pays"] += 1
                    if pays_brut:
                        pays_rejetes.add(pays_brut)
                    log.debug(f"IsDB - page {num_page}[{idx_h}] rejet pays={pays_brut!r} : {titre[:60]!r}")
                    continue

                titre_norm = normaliser_texte(titre)
                if not _RE_SIGNAL_ELECTRIQUE.search(titre_norm):
                    compteurs["rejet_signal_electrique"] += 1
                    continue

                if _DOMAINES_BLOQUES.search(titre):
                    compteurs["rejet_domaine_bloque"] += 1
                    continue

                date_limite_obj = _parse_date_isdb(date_ligne)
                if not date_limite_obj:
                    compteurs["rejet_deadline_absente"] += 1
                    log.debug(f"IsDB - page {num_page}[{idx_h}] deadline non parsee (brut={date_ligne!r}) : {titre[:60]!r}")
                    continue
                if date_limite_obj < seuil_deadline:
                    compteurs["rejet_deadline_trop_proche"] += 1
                    continue

                date_pub_str = _scraper_detail_isdb(lien)

                compteurs["retenus"] += 1
                log.info(
                    f"IsDB - AO RETENU [{pays_canon}] : {titre[:80]} | "
                    f"limite={date_limite_obj} | pub={date_pub_str or 'N/A'} | lien={lien}"
                )

                resultats.append({
                    "titre":            titre,
                    "reference":        "",
                    "type_marche":      "",
                    "date_publication": date_pub_str,
                    "date_limite":      date_limite_obj.strftime("%d/%m/%Y"),
                    "lien_avis":        lien,
                    "lien_dossier":     "",
                    "pays":             pays_canon,
                })

    except requests.exceptions.RequestException as e:
        log.error(f"IsDB - ECHEC REQUETE HTTP : {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
    except Exception as e:
        log.error(f"IsDB - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("IsDB - ===== BILAN FILTRAGE =====")
    log.info(f"IsDB - entrees totales scannees              : {compteurs['total_lignes']}")
    log.info(f"IsDB - rejetees (statut Ferme/Closed)         : {compteurs['rejet_statut_ferme']}")
    log.info(f"IsDB - rejetees (statut non reconnu)          : {compteurs['rejet_statut_non_reconnu']}")
    log.info(f"IsDB - rejetees (type non cible)              : {compteurs['rejet_type_non_cible']}")
    log.info(f"IsDB - rejetees (pays hors Afrique)           : {compteurs['rejet_pays']}")
    log.info(f"IsDB - rejetees (signal electrique)           : {compteurs['rejet_signal_electrique']}")
    log.info(f"IsDB - rejetees (domaine bloque)              : {compteurs['rejet_domaine_bloque']}")
    log.info(f"IsDB - rejetees (deadline absente)            : {compteurs['rejet_deadline_absente']}")
    log.info(f"IsDB - rejetees (deadline < {DELAI_MIN_JOURS_ISDB}j)          : {compteurs['rejet_deadline_trop_proche']}")
    log.info(f"IsDB - RESULTAT FINAL : {compteurs['retenus']} AO retenus")
    if pays_rejetes:
        log.info(f"IsDB - pays rencontres rejetes ({len(pays_rejetes)}) : {sorted(pays_rejetes)}")
    return deduplicer(resultats)
