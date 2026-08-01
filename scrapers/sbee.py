"""Scraper SBEE Benin. Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import time
import traceback
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from config import CONFIG, HEADERS, MOTS_CLES_AFRIQUE, _RE_SIGNAL_ELECTRIQUE, log
from utils import session, normaliser_texte, contient_mot_cle, parse_date, ao_est_recent
from historique import deduplicer

def scraper_sbee():
    """
    Le filtre de fraicheur ne se base plus sur la date de
    publication (ao_est_recent) mais sur la DATE LIMITE DE DEPOT :
    un AO SBEE n'est retenu que si sa date limite de depot est
    encore a au moins CONFIG["sbee_jours_min_avant_limite"] jours
    d'aujourd'hui (par defaut 7). Si aucune date limite n'est
    detectee dans le bloc HTML, l'AO est CONSERVE par defaut
    (comportement de secours), comme avant.
    """
    resultats = []
    url = "https://marches-publics.sbee.bj/"
    jours_min_limite = CONFIG.get("sbee_jours_min_avant_limite", 7)
    seuil_date_limite = date.today() + timedelta(days=jours_min_limite)
    log.info(f"SBEE - ===== DEBUT SCRAPING =====")
    log.info(f"SBEE - URL cible : {url}")
    log.info(
        f"SBEE - filtre desormais sur la DATE LIMITE DE DEPOT "
        f"(>= {jours_min_limite} jour(s) a partir d'aujourd'hui) | "
        f"date du jour : {date.today()} | seuil date limite : {seuil_date_limite}"
    )

    compteurs = {
        "blocs_h2_h3_sans_date_pub": 0,
        "rejet_date_limite_trop_proche": 0,
        "rejet_pas_signal_electrique": 0,
        "retenus_sans_date_limite_fallback": 0,
        "retenus": 0,
    }

    try:
        t0 = time.time()
        r = session.get(url, headers=HEADERS, timeout=CONFIG["timeout"], verify=False)
        log.info(f"SBEE - requete HTTP terminee en {time.time() - t0:.2f}s")
        r.raise_for_status()
        log.info(f"SBEE - HTTP {r.status_code} | taille reponse : {len(r.text)} caracteres | content-type : {r.headers.get('Content-Type')}")
        soup = BeautifulSoup(r.text, "lxml")
        titres = soup.find_all(["h2", "h3"])
        log.info(f"SBEE - {len(titres)} balises h2/h3 trouvees sur la page")
        if not titres:
            log.warning("SBEE - AUCUNE balise h2/h3 trouvee -> fallback sur liens <a> (la structure du site a peut-etre change)")
            liens_a = soup.find_all("a", href=True)
            log.info(f"SBEE - {len(liens_a)} liens <a> trouves au total sur la page (fallback)")
            for a in liens_a:
                texte_a = a.get_text(strip=True)
                if len(texte_a) < 10 or not contient_mot_cle(texte_a, MOTS_CLES_AFRIQUE):
                    continue
                href = a["href"]
                full = href if href.startswith("http") else "https://marches-publics.sbee.bj" + href
                resultats.append({"titre": texte_a, "reference": "", "type_marche": "",
                                   "date_publication": "", "date_limite": "",
                                   "lien_avis": full, "lien_dossier": ""})
            log.info(f"SBEE - fallback <a> : {len(resultats)} element(s) retenu(s)")
            log.info(f"SBEE - RESULTAT FINAL : {len(resultats)} AO retenus")
            return deduplicer(resultats)
        for idx_h, h in enumerate(titres):
            titre = h.get_text(strip=True)
            if not titre or len(titre) < 5:
                continue
            parent = h.find_parent()
            if not parent:
                continue
            conteneur  = parent.find_parent() or parent
            texte_bloc = conteneur.get_text(separator=" ", strip=True)

            pub_m = re.search(r'Date\s+de\s+publication\s+(\d{2}[-/]\d{2}[-/]\d{4})', texte_bloc, re.IGNORECASE)
            if not pub_m:
                compteurs["blocs_h2_h3_sans_date_pub"] += 1
                log.debug(f"SBEE - [bloc {idx_h}] pas de 'Date de publication' trouvee -> ignore : {titre[:60]!r}")
                continue
            date_pub = pub_m.group(1).replace("-", "/")

            #Extraction de la date limite de depot AVANT le
            # filtre, car c'est desormais elle qui determine si l'AO
            # est retenu (et non plus date_pub / ao_est_recent).
            date_lim = ""
            lim_m = re.search(r'Date\s+limite\s+de\s+d[eé]p[oô]t\s+(\d{2}[-/]\d{2}[-/]\d{4})', texte_bloc, re.IGNORECASE)
            if lim_m:
                date_lim = lim_m.group(1).replace("-", "/")

            if date_lim:
                d_lim_obj = parse_date(date_lim)
                if d_lim_obj is not None and d_lim_obj < seuil_date_limite:
                    compteurs["rejet_date_limite_trop_proche"] += 1
                    log.debug(
                        f"SBEE - [bloc {idx_h}] date limite trop proche "
                        f"({d_lim_obj} < seuil {seuil_date_limite}) : {titre[:60]!r}"
                    )
                    continue
            else:
                # Aucune date limite detectee -> fallback SECURISE sur la
                # date de publication : on ne garde l'AO que si sa
                # publication reste recente (< 45 jours), sinon on le
                # rejette pour eviter de conserver des AO obsoletes.
                d_pub_obj = parse_date(date_pub)
                if d_pub_obj is not None and d_pub_obj < (date.today() - timedelta(days=45)):
                    compteurs.setdefault("rejet_fallback_date_pub_trop_ancienne", 0)
                    compteurs["rejet_fallback_date_pub_trop_ancienne"] += 1
                    log.debug(
                        f"SBEE - [bloc {idx_h}] rejete via fallback date_pub "
                        f"({d_pub_obj} trop ancienne) : {titre[:60]!r}"
                    )
                    continue
                compteurs["retenus_sans_date_limite_fallback"] += 1
                log.debug(f"SBEE - [bloc {idx_h}] aucune date limite detectee -> AO conserve via fallback date_pub OK : {titre[:60]!r}")

            signal = _RE_SIGNAL_ELECTRIQUE.search(normaliser_texte(titre))
            if not signal:
                compteurs["rejet_pas_signal_electrique"] += 1
                log.debug(f"SBEE - [bloc {idx_h}] aucun signal electrique dans le titre : {titre[:60]!r}")
                continue
            tous_liens = conteneur.find_all("a", href=True)
            lien_avis = ""
            lien_dossier = ""
            for a in tous_liens:
                href = a["href"]
                ta   = a.get_text(strip=True).lower()
                full = href if href.startswith("http") else "https://marches-publics.sbee.bj" + href
                if "/uploads/" in href.lower() and href.lower().endswith((".pdf", ".PDF")):
                    lien_avis = lien_avis or full
                elif "telecharger" in ta or "telecharger" in ta:
                    lien_avis = lien_avis or full
                elif "demander" in ta or "dossier" in ta:
                    lien_dossier = lien_dossier or full
            if not lien_avis:
                lien_avis = "https://marches-publics.sbee.bj/"
            ref_m = re.search(r'([A-Z]+\s*n[o]\s*[\d/\w-]+/SBEE/[^\s\.]+)', texte_bloc, re.IGNORECASE)
            reference = ref_m.group(1) if ref_m else ""
            type_m = re.search(r'Type\s+de\s+march[e]\s+([^\s][^\n]{2,40})', texte_bloc, re.IGNORECASE)
            type_marche = type_m.group(1).strip() if type_m else ""
            compteurs["retenus"] += 1
            log.info(f"SBEE - AO RETENU [{idx_h}] : {titre[:90]} | pub={date_pub} | limite={date_lim or 'N/A'}")
            resultats.append({
                "titre": titre, "reference": reference, "type_marche": type_marche,
                "date_publication": date_pub, "date_limite": date_lim,
                "lien_avis": lien_avis, "lien_dossier": lien_dossier,
            })
    except requests.exceptions.RequestException as e:
        log.error(f"SBEE - ECHEC REQUETE HTTP : {type(e).__name__}: {e}")
        log.error(traceback.format_exc())
    except Exception as e:
        log.error(f"SBEE - erreur : {e}")
        log.error(traceback.format_exc())

    log.info(f"SBEE - ===== BILAN FILTRAGE =====")
    log.info(f"SBEE - blocs sans date de publication trouvee   : {compteurs['blocs_h2_h3_sans_date_pub']}")
    log.info(f"SBEE - rejetes (date limite trop proche < {jours_min_limite}j) : {compteurs['rejet_date_limite_trop_proche']}")
    log.info(f"SBEE - conserves via fallback (pas de date limite) : {compteurs['retenus_sans_date_limite_fallback']}")
    log.info(f"SBEE - rejetes (pas de signal electrique)       : {compteurs['rejet_pas_signal_electrique']}")
    log.info(f"SBEE - retenus avant deduplication               : {compteurs['retenus']}")
    log.info(f"SBEE - RESULTAT FINAL : {len(resultats)} AO retenus")
    return deduplicer(resultats)
