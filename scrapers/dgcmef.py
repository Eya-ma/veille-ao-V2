"""Scraper DGCMEF Burkina Faso (HTML + PDF via PyMuPDF). Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import time
import traceback
from datetime import date, datetime

import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup

from config import (
    CONFIG, HEADERS, _RE_MARQUEUR_AO, _RE_CATEGORIE, _RE_TYPES_REJETES,
    _RE_PARASITES, _RE_AO_OUVERT, _RE_ENCORE_RESULTATS, _RE_INDICATEURS_AO,
    _RE_RESULTATS_REJETES, log,
)
from utils import session
from filtrage import analyser_page_pdf, page_est_utile, valider_ao_structure
from historique import deduplicer

def _est_ligne_organisme(texte):
    if _RE_MARQUEUR_AO.search(texte):
        return False
    mots = texte.split()
    if len(mots) < 3 or any(c.isdigit() for c in texte):
        return False
    mots_signif = [m for m in mots if len(m) > 2]
    if not mots_signif:
        return False
    return sum(1 for m in mots_signif if m.isupper()) / len(mots_signif) >= 0.6


def _extraire_lignes_page(page):
    lignes = []
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type", 1) == 1:
            continue
        for line in bloc.get("lines", []):
            parties, est_gras, taille = [], False, 0.0
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if not t:
                    continue
                parties.append(t)
                if span.get("flags", 0) & (1 << 4):
                    est_gras = True
                taille = max(taille, span.get("size", 0))
            texte_ligne = " ".join(parties).strip()
            if texte_ligne:
                lignes.append({"y": line["bbox"][1], "texte": texte_ligne,
                                "bold": est_gras, "size": taille})
    lignes.sort(key=lambda x: x["y"])
    return lignes


def trouver_page_debut_ao(doc):
    total = len(doc)
    log.info(f"DGCMEF - recherche de la 1ere page AO pure parmi {total} pages")
    for num_page in range(total):
        texte = doc[num_page].get_text()
        info  = analyser_page_pdf(texte)
        if (info["score_resultats"] == 0
                and info["ratio_texte"] > 0.4
                and (info["score_ao"] > 0 or info["ratio_texte"] > 0.5)):
            log.info(f"DGCMEF - premiere page AO pure detectee : page {num_page + 1} (info={info})")
            return num_page
    log.warning("DGCMEF - aucune page AO pure trouvee dans tout le document, lecture depuis page 0")
    return 0

def scraper_dgcmef():
    resultats = []
    url_base  = "http://www.dgcmef.gov.bf/fr/appels-d-offre"
    log.info("DGCMEF - ===== DEBUT SCRAPING =====")
    log.info(f"DGCMEF - URL cible : {url_base}")

    compteurs = {
        "ao_avec_organisme_mais_pas_de_marqueur": 0,
        "ao_titre_trop_court": 0,
        "ao_type_rejete": 0,
        "ao_rejete_validation": 0,
        "pages_utiles": 0,
        "pages_ignorees": 0,
        "retenus": 0,
    }

    try:
        t0 = time.time()
        r = session.get(url_base, headers=HEADERS, timeout=CONFIG["timeout"])
        log.info(f"DGCMEF - requete page liste terminee en {time.time() - t0:.2f}s")
        r.raise_for_status()
        log.info(f"DGCMEF - HTTP {r.status_code} | taille reponse : {len(r.text)} caracteres")
        soup = BeautifulSoup(r.text, "lxml")
        lien_pdf = None
        liens_pdf_trouves = [a["href"] for a in soup.find_all("a", href=True) if ".pdf" in a["href"].lower()]
        log.info(f"DGCMEF - {len(liens_pdf_trouves)} lien(s) PDF trouve(s) sur la page liste")
        for a in soup.find_all("a", href=True):
            if ".pdf" in a["href"].lower():
                lien_pdf = a["href"] if a["href"].startswith("http") else "http://www.dgcmef.gov.bf" + a["href"]
                break
        if not lien_pdf:
            log.warning("DGCMEF - AUCUN PDF trouve sur la page -> la structure du site a peut-etre change")
            return resultats
        log.info(f"DGCMEF - telechargement : {lien_pdf}")
        t1 = time.time()
        resp_pdf = session.get(lien_pdf, headers=HEADERS, timeout=60)
        log.info(f"DGCMEF - telechargement PDF termine en {time.time() - t1:.2f}s")
        resp_pdf.raise_for_status()
        log.info(f"DGCMEF - HTTP {resp_pdf.status_code} | taille PDF : {len(resp_pdf.content)} octets")
        with fitz.open(stream=resp_pdf.content, filetype="pdf") as doc:
            total_pages = len(doc)
            log.info(f"DGCMEF - PDF ouvert avec succes : {total_pages} pages")
            page_debut = trouver_page_debut_ao(doc)
            log.info(f"DGCMEF - lecture a partir de la page {page_debut + 1}")
            for num_page in range(page_debut, total_pages):
                page       = doc[num_page]
                texte_brut = page.get_text()
                utile      = page_est_utile(texte_brut)
                if not utile:
                    compteurs["pages_ignorees"] += 1
                    log.debug(f"DGCMEF - page {num_page + 1} ignoree (non utile)")
                    continue
                compteurs["pages_utiles"] += 1
                lignes        = _extraire_lignes_page(page)
                lignes_brutes = [l.strip() for l in texte_brut.split("\n") if l.strip()]
                if not lignes:
                    log.debug(f"DGCMEF - page {num_page + 1} : aucune ligne extraite (structure spans vide)")
                    continue
                organisme_courant = ""
                lignes_titre      = []

                def _sauvegarder_ao():
                    if not organisme_courant or not lignes_titre:
                        return
                    ligne_ao = next(
                        (l for l in lignes_titre
                         if _RE_AO_OUVERT.search(l) or _RE_INDICATEURS_AO.search(l)),
                        None
                    )
                    if not ligne_ao:
                        compteurs["ao_avec_organisme_mais_pas_de_marqueur"] += 1
                        log.debug(f"DGCMEF - page {num_page + 1} : organisme={organisme_courant[:50]!r} mais aucune ligne marqueur AO trouvee parmi {lignes_titre}")
                        return
                    idx = lignes_titre.index(ligne_ao)
                    if len(ligne_ao) < 40 and idx + 1 < len(lignes_titre):
                        titre_final = (ligne_ao + " " + lignes_titre[idx + 1]).strip()
                    else:
                        titre_final = ligne_ao.strip()
                    if len(titre_final) < 8:
                        compteurs["ao_titre_trop_court"] += 1
                        log.debug(f"DGCMEF - page {num_page + 1} : titre trop court ignore : {titre_final!r}")
                        return
                    if _RE_TYPES_REJETES.search(titre_final):
                        compteurs["ao_type_rejete"] += 1
                        log.debug(f"DGCMEF - page {num_page + 1} : type rejete (resultat/attribution) : {titre_final[:60]!r}")
                        return

                    contexte_complet = organisme_courant + " " + " ".join(lignes_titre)
                    ok = valider_ao_structure(contexte_complet, organisme_courant)
                    if not ok:
                        compteurs["ao_rejete_validation"] += 1
                        log.debug(f"DGCMEF - page {num_page + 1} : rejet valider_ao_structure : {titre_final[:80]!r}")
                        return
                    date_pub_ao = ""
                    for l in lignes_titre:
                        dm = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', l)
                        if dm:
                            date_pub_ao = dm.group(1).replace("-", "/")
                            break
                    if not date_pub_ao:
                        date_pub_ao = datetime.now().strftime("%d/%m/%Y")
                    ref_m = re.search(r'((?:AON|AOI|AO|DAO|DP)\s*[Nn][o]\s*[\d/\w-]+)',
                                      titre_final, re.IGNORECASE)
                    reference = ref_m.group(1) if ref_m else ""
                    date_lim = ""
                    try:
                        idx_brut = next(k for k, l in enumerate(lignes_brutes) if titre_final[:20] in l)
                        contexte = " ".join(lignes_brutes[idx_brut:idx_brut + 12])
                        lm = re.search(
                            r'(?:limite|depot|cloture|date\s+limite)'
                            r'[^\d]*(\d{2}[/\-]\d{2}[/\-]\d{4})',
                            contexte, re.IGNORECASE
                        ) or re.search(r'(\d{2}[/\-]\d{2}[/\-]\d{4})', contexte)
                        if lm:
                            date_lim = lm.group(1).replace("-", "/")
                    except StopIteration:
                        pass
                    num_page_reel = num_page + 1
                    lien_page     = f"{lien_pdf}#page={num_page_reel}"
                    titre_export = lignes_titre[0] if lignes_titre else titre_final
                    if len(titre_export) < 15:
                        titre_export = titre_final
                    compteurs["retenus"] += 1
                    log.info(f"DGCMEF - AO RETENU (page {num_page_reel}) : organisme={organisme_courant[:40]!r} | titre={titre_export[:80]!r}")
                    resultats.append({
                        "titre":            titre_export[:300],
                        "reference":        reference,
                        "lien":             lien_page,
                        "lien_dossier":     lien_pdf,
                        "page_pdf":         num_page_reel,
                        "date_publication": date_pub_ao,
                        "date_limite":      date_lim,
                    })

                for ligne in lignes:
                    texte = ligne["texte"].strip()
                    if not texte or len(texte) < 4:
                        continue
                    if _RE_CATEGORIE.match(texte):
                        continue
                    if re.fullmatch(r'[\d\s/\-\.]+', texte):
                        continue
                    if re.search(r"QUOTIDIEN\s+DES?\s+MARCHES?|DGCMEF|Direction\s+G[e]n[e]rale"
                                 r"|Burkina\s+Faso|Appels?\s+d.offres?\s+des\s+Minist",
                                 texte, re.IGNORECASE):
                        continue
                    if _RE_PARASITES.match(texte):
                        continue
                    if _est_ligne_organisme(texte):
                        _sauvegarder_ao()
                        organisme_courant = texte
                        lignes_titre      = []
                        continue
                    if organisme_courant:
                        if _RE_ENCORE_RESULTATS.search(texte):
                            lignes_titre      = []
                            organisme_courant = ""
                            continue
                        if _RE_RESULTATS_REJETES.search(texte) or _RE_PARASITES.match(texte):
                            continue
                        if len(lignes_titre) < 5:
                            lignes_titre.append(texte)
                _sauvegarder_ao()
    except ImportError:
        log.error("DGCMEF - PyMuPDF non installe -> pip install PyMuPDF")
    except requests.exceptions.RequestException as e:
        log.error(f"DGCMEF - ECHEC REQUETE HTTP : {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
    except Exception as e:
        log.error(f"DGCMEF - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("DGCMEF - ===== BILAN FILTRAGE =====")
    log.info(f"DGCMEF - pages jugees utiles    : {compteurs['pages_utiles']}")
    log.info(f"DGCMEF - pages ignorees         : {compteurs['pages_ignorees']}")
    log.info(f"DGCMEF - rejetes (pas de marqueur AO trouve) : {compteurs['ao_avec_organisme_mais_pas_de_marqueur']}")
    log.info(f"DGCMEF - rejetes (titre trop court)          : {compteurs['ao_titre_trop_court']}")
    log.info(f"DGCMEF - rejetes (type resultat/attribution) : {compteurs['ao_type_rejete']}")
    log.info(f"DGCMEF - rejetes (validation structure)      : {compteurs['ao_rejete_validation']}")
    log.info(f"DGCMEF - retenus avant deduplication          : {compteurs['retenus']}")
    log.info(f"DGCMEF - RESULTAT FINAL : {len(resultats)} AO retenus")
    return deduplicer(resultats)
