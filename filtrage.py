"""
Scoring, validation et filtrage des AO (structure, mots-cles,
similarite semantique par embedding, analyse de pages PDF).
Issu du decoupage de veille_ao_1_1.py (v10.18).
"""
import re
import time
import traceback

from config import (
    CONFIG, MOTS_CLES_AFRIQUE, SIGNAUX_RAPIDES,
    _RE_INDICATEURS_AO, _RE_TYPE_MARCHE, _RE_NUMERO_AO,
    _RE_ORGANISME_PUBLIC, _RE_FINANCEMENT, _DOMAINES_BLOQUES,
    _RE_RESULTATS_REJETES, _RE_SIGNAL_ELECTRIQUE, log,
)
from utils import normaliser_texte, contient_mot_cle

_PHRASE_REFERENCE = (
    "electricite energie solaire photovoltaique transformateur "
    "reseau electrique HTA BT ligne electrique groupe electrogene "
    "electrification centrale electrique onduleur panneau solaire"
)

_modele_embedding     = None
_embedding_ref        = None
_embedding_disponible = None

def _charger_modele_embedding():
    global _modele_embedding, _embedding_ref, _embedding_disponible
    if _embedding_disponible is not None:
        log.info(f"[EMBEDDING] Etat deja connu : disponible={_embedding_disponible}")
        return _embedding_disponible
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
        log.info("[EMBEDDING] Chargement SentenceTransformer (all-MiniLM-L6-v2)...")
        t0 = time.time()
        _modele_embedding = SentenceTransformer("all-MiniLM-L6-v2")
        _embedding_ref = _modele_embedding.encode(
            _PHRASE_REFERENCE, convert_to_numpy=True, normalize_embeddings=True,
        )
        _embedding_disponible = True
        log.info(f"[EMBEDDING] Modele charge avec succes en {time.time() - t0:.2f}s -> filtre semantique ACTIF")
    except ImportError:
        log.warning("[EMBEDDING] sentence-transformers non installe -> filtre semantique DESACTIVE")
        _embedding_disponible = False
    except Exception as e:
        log.warning(f"[EMBEDDING] Impossible de charger le modele : {e}")
        log.warning(traceback.format_exc())
        _embedding_disponible = False
    return _embedding_disponible

def score_rapide(texte):
    texte_lower = normaliser_texte(texte).lower()
    return sum(p for pat, p in SIGNAUX_RAPIDES if re.search(pat, texte_lower))

def similarite_embedding(texte):
    import numpy as np
    if not _charger_modele_embedding():
        return -1.0
    try:
        vec = _modele_embedding.encode(
            texte[:512], convert_to_numpy=True, normalize_embeddings=True,
        )
        sim = float(np.dot(vec, _embedding_ref))
        log.debug(f"[EMBEDDING] similarite={sim:.3f} pour texte={texte[:60]!r}")
        return sim
    except Exception as e:
        log.debug(f"[EMBEDDING] Erreur embedding : {e}")
        return -1.0

def score_structure_ao(texte, contexte_organisme=""):
    texte_complet = (texte + " " + contexte_organisme).strip()
    detail = {"indicateur": 0, "marche": 0, "numero": 0, "organisme": 0, "financement": 0}
    if _RE_INDICATEURS_AO.search(texte_complet):  detail["indicateur"]  = 3
    if _RE_TYPE_MARCHE.search(texte_complet):      detail["marche"]      = 2
    if _RE_NUMERO_AO.search(texte_complet):        detail["numero"]      = 2
    if _RE_ORGANISME_PUBLIC.search(texte_complet): detail["organisme"]   = 1
    if _RE_FINANCEMENT.search(texte_complet):      detail["financement"] = 1
    return sum(detail.values()), detail

def valider_ao_structure(titre, contexte_organisme=""):
    texte_complet = (titre + " " + contexte_organisme).strip()
    if _DOMAINES_BLOQUES.search(texte_complet):
        log.debug(f"[VALIDATION] Domaine bloque : {texte_complet[:80]!r}")
        return False
    if _RE_RESULTATS_REJETES.search(texte_complet):
        log.debug(f"[VALIDATION] Resultats detectes (rejet) : {texte_complet[:80]!r}")
        return False
    titre_norm    = normaliser_texte(titre)
    contexte_norm = normaliser_texte(contexte_organisme)
    if not _RE_SIGNAL_ELECTRIQUE.search(titre_norm) and not _RE_SIGNAL_ELECTRIQUE.search(contexte_norm):
        log.debug(f"[VALIDATION] Aucun signal electricite : {texte_complet[:80]!r}")
        return False
    score_el = score_rapide(texte_complet)
    _RE_OPERATEUR = re.compile(r"\bSONABEL\b|\bSIER\b|\bANER\b|\bAREC\b", re.IGNORECASE)
    seuil = 1 if _RE_OPERATEUR.search(texte_complet) else 2
    if score_el >= seuil:
        log.debug(f"[VALIDATION] OK via score_rapide={score_el} (seuil={seuil}) : {texte_complet[:80]!r}")
        return True
    score, detail = score_structure_ao(titre, contexte_organisme)
    if score >= CONFIG["score_structure_seuil"]:
        log.debug(f"[VALIDATION] OK via score_structure={score} (detail={detail}) : {texte_complet[:80]!r}")
        return True
    if score_el >= CONFIG["score_rapide_seuil"]:
        log.debug(f"[VALIDATION] OK via score_rapide(seuil config)={score_el} : {texte_complet[:80]!r}")
        return True
    sim = similarite_embedding(texte_complet)
    if sim < 0:
        ok = contient_mot_cle(texte_complet, MOTS_CLES_AFRIQUE)
        log.debug(f"[VALIDATION] Embedding indisponible -> fallback mots-cles = {ok} : {texte_complet[:80]!r}")
        return ok
    ok = sim >= CONFIG["embedding_seuil"]
    log.debug(f"[VALIDATION] Embedding sim={sim:.3f} (seuil={CONFIG['embedding_seuil']}) -> {ok} : {texte_complet[:80]!r}")
    return ok

def filtrer_ao_dgcmef(titre, texte_supplementaire=""):
    return valider_ao_structure(titre, texte_supplementaire)

def analyser_page_pdf(texte):
    lignes = [l.strip() for l in texte.split("\n") if l.strip()]
    if not lignes:
        return {"ratio_table": 0, "ratio_texte": 0, "score_ao": 0, "score_resultats": 0}
    total = len(lignes)
    lignes_courtes  = sum(1 for l in lignes if len(l.split()) <= 5)
    lignes_chiffres = sum(1 for l in lignes if re.search(r"\d", l))
    ratio_table     = (lignes_courtes + lignes_chiffres) / (2 * total)
    lignes_longues  = sum(1 for l in lignes if len(l.split()) >= 8)
    ratio_texte     = lignes_longues / total
    texte_lower     = texte.lower()
    score_ao = 0
    if re.search(r"appel\s+d.offres?|avis\s+d.appel", texte_lower): score_ao += 3
    if re.search(r"\bdao\b|\baon\b|\baoi\b", texte_lower):           score_ao += 2
    score_resultats = 0
    if re.search(r"nombre\s+de\s+plis|plis\s+re[c]us", texte_lower):             score_resultats += 3
    if re.search(r"seuil\s+de\s+tol[e]rance|intervalle\s*:\s*de", texte_lower):  score_resultats += 3
    if re.search(r"d[e]pouillement|soumissionnaires?", texte_lower):              score_resultats += 2
    if re.search(r"attributaire|adjudication|march[e]\s+attribu", texte_lower):   score_resultats += 3
    if re.search(r"montant\s+lu|moyenne\s+\d|budget\s*:\s*\d", texte_lower):      score_resultats += 2
    if re.search(r"lot\s+0?\d\s*:\s*\d{2,}\s+plis", texte_lower):                score_resultats += 3
    return {"ratio_table": ratio_table, "ratio_texte": ratio_texte,
            "score_ao": score_ao, "score_resultats": score_resultats}

def page_est_utile(texte):
    info = analyser_page_pdf(texte)
    if info["score_resultats"] >= 3:
        log.debug(f"[PDF] Page rejetee (score_resultats={info['score_resultats']} >= 3)")
        return False
    if info["ratio_texte"] < 0.2 and info["ratio_table"] > 0.8:
        log.debug(f"[PDF] Page rejetee (ratio_texte={info['ratio_texte']:.2f} bas, ratio_table={info['ratio_table']:.2f} haut -> tableau pur)")
        return False
    if info["score_ao"] >= 2 and info["score_resultats"] == 0:
        return True
    if info["ratio_texte"] > 0.3 and info["score_resultats"] < 2:
        return True
    log.debug(f"[PDF] Page rejetee (criteres non remplis) : {info}")
    return False
