"""
Fonctions utilitaires generiques (session HTTP, dates, normalisation
de texte/pays, URLs...) utilisees par plusieurs modules.
Issu du decoupage de veille_ao_1_1.py (v10.18).
"""
import re
import unicodedata
from datetime import datetime, date, timedelta
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CONFIG, HEADERS, PAYS_AFRIQUE_CIBLE, PAYS_AFRIQUE_FR_DGMARKET, log

def creer_session():
    s = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        connect=3,
        read=3,
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

session = creer_session()

def verifier_lien(url_a_tester, timeout=10):
    """
    Verifie qu'un lien est reellement accessible (HTTP 200-399).
    Utilise HEAD en priorite (plus rapide, pas de telechargement du
    contenu) ; si le serveur ne supporte pas HEAD (405/403 etc.),
    retente en GET.
    Retourne (ok: bool, statut: str) ou statut est soit le code HTTP
    soit un message d'erreur court.
    """
    try:
        r = session.head(url_a_tester, headers=HEADERS, timeout=timeout,
                          allow_redirects=True, verify=False)
        if r.status_code >= 400:
            r = session.get(url_a_tester, headers=HEADERS, timeout=timeout,
                             allow_redirects=True, verify=False, stream=True)
            r.close()
        ok = 200 <= r.status_code < 400
        return ok, str(r.status_code)
    except requests.exceptions.RequestException as e:
        return False, f"{type(e).__name__}"

def normaliser_texte(s):
    """Retire les accents/diacritiques d'une chaine pour le matching regex."""
    if not s:
        return ""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )

def _normaliser_pays_texte(txt):
    """Normalise un nom de pays pour comparaison robuste (accents, casse,
    apostrophes courbes vs droites, espaces)."""
    if not txt:
        return ""
    txt = txt.replace("’", "'").replace("`", "'")
    txt = normaliser_texte(txt)
    return re.sub(r'\s+', ' ', txt).strip().lower()


_PAYS_AFRIQUE_CIBLE_NORMALISES = {
    _normaliser_pays_texte(p): p for p in PAYS_AFRIQUE_CIBLE
}


def _pays_est_afrique_cible(pays_brut):
    """Retourne le libelle canonique PAYS_AFRIQUE_CIBLE si match, sinon None."""
    return _PAYS_AFRIQUE_CIBLE_NORMALISES.get(_normaliser_pays_texte(pays_brut))

_PAYS_AFRIQUE_FR_DGMARKET_NORMALISES = {
    _normaliser_pays_texte(p): p for p in PAYS_AFRIQUE_FR_DGMARKET
}


def _pays_est_afrique_dgmarket(pays_brut):
    """Retourne le libelle canonique PAYS_AFRIQUE_FR_DGMARKET si match, sinon None."""
    return _PAYS_AFRIQUE_FR_DGMARKET_NORMALISES.get(_normaliser_pays_texte(pays_brut))

def contient_mot_cle(texte, mots):
    texte_lower = texte.lower()
    return any(re.search(rf"\b{re.escape(m.lower())}\b", texte_lower) for m in mots)

def jours_a_couvrir():
    return 3 if date.today().weekday() == 0 else 2


def parse_date(date_str):
    """
    [v10.17] Ajout du format "%d-%b-%Y" (ex: "23-Apr-2026") car c'est
    le format renvoye par le champ "noticedate" de l'API World Bank
    (mois en anglais abrege).
    """
    if not date_str:
        return None
    date_str = date_str.strip().split(" ")[0]
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y",
                "%B %d, %Y", "%d/%m/%y", "%d-%b-%Y"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    log.debug(f"[PARSE_DATE] Echec parsing pour valeur brute : {date_str!r}")
    return None


def ao_est_expire(ao):
    d = parse_date(ao.get("date_limite", ""))
    if d is not None:
        expire = d < date.today()
        if expire:
            log.debug(f"[EXPIRATION] AO expire (date_limite={d}) : {ao.get('titre','')[:60]!r}")
        return expire

    d_pub = parse_date(ao.get("date_pub", ""))
    if d_pub is not None and d_pub < (date.today() - timedelta(days=60)):
        log.debug(f"[EXPIRATION] AO expire via fallback date_pub ({d_pub}) : {ao.get('titre','')[:60]!r}")
        return True
    return False


def ao_est_recent(date_pub_str):
    d = parse_date(date_pub_str)
    return d is None or d >= (date.today() - timedelta(days=jours_a_couvrir()))


def url_propre(url_brute):
    """
    Nettoie et encode une URL pour qu'elle soit utilisable partout
    (Excel hyperlink, email, navigateur), quelle que soit l'origine
    des caracteres problematiques (espaces, accents, °, /, #, etc.
    dans les segments dynamiques comme num_ao ou id_interne).
    
    """
    if not url_brute:
        return url_brute
    try:
        parties = urlsplit(url_brute)
        path_propre = quote(parties.path, safe="/")
        path_propre = path_propre.replace("#", "%23")
        query_propre = quote(parties.query, safe="=&")
        fragment_propre = quote(parties.fragment, safe="")
        return urlunsplit((parties.scheme, parties.netloc, path_propre, query_propre, fragment_propre))
    except Exception:
        log.debug(f"[URL_PROPRE] Echec nettoyage URL, fallback brut : {url_brute!r}")
        return url_brute  
