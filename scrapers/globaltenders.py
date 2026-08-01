"""Scraper GlobalTenders (Playwright, login requis).

URL ciblee :
  https://www.globaltenders.com/gt-search
  ?sector[]=21 (Energy, Power and Electrical)
  &region_name[]=REG0101/REG0102/REG0104 (Afrique)
  &tender_type=live

Structure HTML des cartes (observee en DevTools) :
  div.tender-wrap#tender_XXXXXXX
    div.p-0 > div.container
      div.title-wrap.col-10...
        span[itemprop="name"]   <- titre
      div.row.text-dark...      <- pays + dates
        img.flag + texte pays
        icone calendrier + date publication
        icone timer + date limite
      a[href*="view-detail"]    <- lien detail

Credentials : GLOBALTENDERS_EMAIL / GLOBALTENDERS_PASSWORD dans .env
"""
import re
import traceback
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    CONFIG,
    DELAI_MIN_JOURS_GLOBALTENDERS,
    NB_PAGES_MAX_GLOBALTENDERS,
    PAYS_AFRIQUE_CIBLE,
    _DOMAINES_BLOQUES,
    _RE_SIGNAL_ELECTRIQUE,
    _RE_NOTIFICATION,
    log,
)
from utils import normaliser_texte, _pays_est_afrique_cible
from historique import deduplicer

_URL_SEARCH = (
    "https://www.globaltenders.com/gt-search"
    "?status=menu&limit=0"
    "&sector%5B%5D=21"
    "&region_name%5B%5D=REG0101"
    "&region_name%5B%5D=REG0102"
    "&region_name%5B%5D=REG0104"
    "&notice_type=gpn%2Cpp%2Cspn%2Crei%2Cppn%2Cacn%2Crfc"
    "&cpv=&bidding_type=&tender_type=live"
    "&postrange=&deadline=&posting_id=&est_cost_currency=USD&est_cost="
)
_URL_LOGIN = "https://www.globaltenders.com/tender-login/sign-up"
_BASE_URL  = "https://www.globaltenders.com"

# ─────────────────────────────────────────────────────────────────────────────
#  Detection pays - specifique GlobalTenders
# ─────────────────────────────────────────────────────────────────────────────
_PAYS_ALIAS_GLOBALTENDERS = {
    "dr congo":                         "Congo, Democratic Republic of",
    "drc":                               "Congo, Democratic Republic of",
    "democratic republic of congo":      "Congo, Democratic Republic of",
    "democratic republic of the congo":  "Congo, Democratic Republic of",
    "congo":                             "Congo, Republic of",
    "republic of congo":                 "Congo, Republic of",
    "republic of the congo":             "Congo, Republic of",
    "congo-brazzaville":                 "Congo, Republic of",
    "egypt":                             "Egypt, Arab Republic of",
    "arab republic of egypt":            "Egypt, Arab Republic of",
    "gambia":                            "Gambia, The",
    "the gambia":                        "Gambia, The",
    "cote d'ivoire":                     "Cote d'Ivoire",
    "côte d'ivoire":                     "Cote d'Ivoire",
    "ivory coast":                       "Cote d'Ivoire",
    "united republic of tanzania":       "Tanzania",
    "cape verde":                        "Cabo Verde",
    "swaziland":                         "Eswatini",
    "sao tome and principe":             "Sao Tome and Principe",
    "sao tome & principe":               "Sao Tome and Principe",
    "são tomé and príncipe":             "Sao Tome and Principe",
    "guinea bissau":                     "Guinea-Bissau",
}


def _texte_recherche(s: str) -> str:
    """Normalise une chaine pour recherche robuste : accents supprimes,
    minuscule, toute ponctuation (virgules, apostrophes, tirets...)
    remplacee par des espaces, espaces multiples ecrases."""
    if not s:
        return ""
    s = normaliser_texte(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _construire_index_pays():
    """Construit un index (regex, libelle_canonique) trie par longueur de
    motif decroissante, a partir de PAYS_AFRIQUE_CIBLE + des alias
    GlobalTenders. Trier par longueur evite qu'un motif court comme
    "congo" ne soit teste avant "congo democratic republic of"."""
    entrees = [(p, p) for p in PAYS_AFRIQUE_CIBLE]
    entrees += list(_PAYS_ALIAS_GLOBALTENDERS.items())

    index = []
    for libelle_brut, canon in entrees:
        motif = _texte_recherche(libelle_brut)
        if not motif:
            continue
        pattern = re.compile(r'\b' + re.escape(motif).replace(r'\ ', r'\s+') + r'\b')
        index.append((len(motif), pattern, canon))
    index.sort(key=lambda x: -x[0])
    return index


_INDEX_PAYS_GT = _construire_index_pays()


def _detecter_pays_texte(texte: str):
    """Recherche un pays cible n'importe ou dans un texte libre (regex sur
    texte complet normalise), bien plus robuste que le decoupage mot par
    mot : insensible a la casse, aux accents, a la ponctuation, aux
    retours a la ligne et aux mots colles."""
    if not texte:
        return None
    texte_norm = _texte_recherche(texte)
    for _, pattern, canon in _INDEX_PAYS_GT:
        if pattern.search(texte_norm):
            return canon
    return None


# ─── Detection des notifications (pas de vrais AO) ────────────────────────────
_RE_NOTIFICATION = re.compile(
    r'\b('
    r'general\s+procurement\s+notice|gpn|'
    r'procurement\s+plan|'
    r'prior\s+information\s+notice|pin|'
    r'preliminary\s+procurement\s+notice|ppn|'
    r'expression\s+of\s+interest|eoi|rei|'
    r'award\s+notice|contract\s+award|'
    r'notification\s+of\s+award|notice\s+of\s+award|award\s+of\s+contract|'
    r'request\s+for\s+clarification|rfc|'
    r'prequalification|pre-qualification|'
    r'hiring\s+of|recruitment\s+of|vacancy|vacancies|job\s+opening|'
    r'appointment\s+of|request\s+for\s+cv|individual\s+consultant'
    r')\b',
    re.IGNORECASE
)


# ─── Parsing dates ────────────────────────────────────────────────────────────
_MOIS_ABBR_GT = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def _parse_date_gt(texte: str):
    """Parse '27 Jul 2026' ou '2026-07-27' ou '27/07/2026' -> date Python."""
    if not texte:
        return None
    texte = texte.strip()

    # ISO : 2026-07-27
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', texte)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Slashes : 27/07/2026
    m = re.match(r'(\d{1,2})[/.](\d{1,2})[/.](\d{4})', texte)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # "27 Jul 2026"
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})', texte)
    if m:
        jour, mois_brut, annee = m.groups()
        mois_num = _MOIS_ABBR_GT.get(mois_brut.lower()[:3])
        if mois_num:
            try:
                return date(int(annee), mois_num, int(jour))
            except ValueError:
                pass

    log.debug(f"[GT DATE] Echec parsing : {texte!r}")
    return None


# ─── Login ────────────────────────────────────────────────────────────────────
def _tenter_login(page) -> bool:
    email    = CONFIG.get("globaltenders_email", "")
    password = CONFIG.get("globaltenders_password", "")
    if not email or not password:
        log.error("GlobalTenders - GLOBALTENDERS_EMAIL / GLOBALTENDERS_PASSWORD absents dans .env")
        return False

    log.info(f"GlobalTenders - login avec {email!r}")
    try:
        page.goto(_URL_LOGIN, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("input[name='email']", timeout=10000)
        page.fill("input[name='email']", email)
        page.fill("input[name='password']", password)
        page.click("input[type='submit']")

        try:
            page.wait_for_url(
                lambda url: "sign-up" not in url and "/tender-login" not in url,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            log.debug("GlobalTenders - wait_for_url timeout, verification directe de l'URL")

        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        # Verifier si login reussi : on doit etre redirige hors de la page login
        if "sign-up" in page.url or "login" in page.url.lower():
            log.error(f"GlobalTenders - login echoue (toujours sur la page login) -> {page.url}")
            return False

        log.info(f"GlobalTenders - login reussi -> {page.url}")
        return True

    except Exception as e:
        log.error(f"GlobalTenders - erreur login : {e}")
        return False


# ─── Extraction d'une page de résultats ──────────────────────────────────────
def _extraire_cartes_page(page, seuil_deadline: date, compteurs: dict, pays_rejetes: set) -> list:
    resultats_page = []

    # Attendre que les cartes soient chargees
    try:
        page.wait_for_selector("div.tender-wrap", timeout=15000)
    except PlaywrightTimeoutError:
        log.warning("GlobalTenders - timeout attente div.tender-wrap")
        return resultats_page

    cartes = page.locator("div.tender-wrap")
    nb = cartes.count()
    log.info(f"GlobalTenders - {nb} carte(s) trouvee(s)")

    for i in range(nb):
        carte = cartes.nth(i)
        compteurs["total_cartes"] += 1

        try:
            # ── Titre ──
            titre = ""
            el_titre = carte.locator("span[itemprop='name']")
            if el_titre.count() > 0:
                titre = el_titre.first.inner_text().strip()
            if len(titre) < 10:
                log.debug(f"GlobalTenders - carte {i} ignoree (titre court : {titre!r})")
                continue

            # ── Lien detail ──
            # On cible precisement le bouton bleu "View Detail" (texte visible),
            # et non l'icone de telechargement/bookmark a cote qui pointe vers
            # une URL differente (saveAsPDF, protegee par login).
            lien_avis = ""
            el_lien = carte.locator("a:has-text('View Detail')")
            if el_lien.count() == 0:
                el_lien = carte.locator("a[href*='view-detail']")
            if el_lien.count() > 0:
                href = el_lien.first.get_attribute("href") or ""
                lien_avis = href if href.startswith("http") else _BASE_URL + href

            # ── Texte complet de la carte pour extraire pays + dates ──
            texte_carte = carte.inner_text()

            # ── Pays ──
            pays_canon = None
            el_flag = carte.locator("img[src*='flag'], img[class*='flag']")
            for j in range(el_flag.count()):
                for attr in ("alt", "title"):
                    val = (el_flag.nth(j).get_attribute(attr) or "").strip()
                    if val:
                        c = _pays_est_afrique_cible(val) or _detecter_pays_texte(val)
                        if c:
                            pays_canon = c
                            break
                if pays_canon:
                    break
            if not pays_canon:
                pays_canon = _detecter_pays_texte(texte_carte)
            if not pays_canon:
                compteurs["rejet_pays"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (pays non trouve) : {titre[:60]}")
                if texte_carte:
                    pays_rejetes.add(texte_carte[:200].replace("\n", " | "))
                continue

            # ── Signal electrique ──
            titre_norm = normaliser_texte(titre)
            if not _RE_SIGNAL_ELECTRIQUE.search(titre_norm):
                compteurs["rejet_signal_electrique"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (pas signal elec.) : {titre[:60]}")
                continue

            # ── Exclusion des notifications (pas de vrais AO) ──
            if _RE_NOTIFICATION.search(titre):
                compteurs["rejet_notification"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (notification) : {titre[:60]}")
                continue

            # ── Exclusion des AO "National" / "NCB" ──
            # National Competitive Bidding (par opposition a International/ICB)
            if re.search(r'\bnational\b', titre, re.IGNORECASE) or re.search(r'\bncb\b', titre, re.IGNORECASE):
                compteurs["rejet_national"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (National/NCB) : {titre[:60]}")
                continue

            if _DOMAINES_BLOQUES.search(titre):
                compteurs["rejet_domaine_bloque"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (domaine bloque) : {titre[:60]}")
                continue

            # ── Dates : chercher toutes les dates dans la carte ──
            # Format attendu : "27 Jul 2026" x2 (publication + limite)
            dates_trouvees = re.findall(r'\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}', texte_carte)
            # Aussi format ISO ou slashes
            dates_trouvees += re.findall(r'\d{4}-\d{2}-\d{2}', texte_carte)
            dates_trouvees += re.findall(r'\d{1,2}/\d{1,2}/\d{4}', texte_carte)

            dates_obj = []
            for d_str in dates_trouvees:
                d_obj = _parse_date_gt(d_str)
                if d_obj:
                    dates_obj.append((d_str, d_obj))

            if len(dates_obj) < 1:
                compteurs["rejet_deadline_absente"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (aucune date trouvee) : {titre[:60]}")
                continue

            # La date limite est la plus tardive des deux dates
            dates_obj.sort(key=lambda x: x[1])
            date_pub_str    = dates_obj[0][0]  if len(dates_obj) >= 2 else ""
            date_limite_str = dates_obj[-1][0]
            date_limite_obj = dates_obj[-1][1]

            if date_limite_obj < seuil_deadline:
                compteurs["rejet_deadline_trop_proche"] += 1
                log.debug(f"GlobalTenders - carte {i} rejetee (deadline {date_limite_obj} < {seuil_deadline}) : {titre[:60]}")
                continue

            # ── Retenu ──
            jours_restants = (date_limite_obj - date.today()).days
            compteurs["retenus"] += 1
            log.info(
                f"GlobalTenders - AO RETENU [{pays_canon}] : {titre[:90]} | "
                f"limite={date_limite_obj} ({jours_restants}j)"
            )

            resultats_page.append({
                "titre":            titre,
                "reference":        "",
                "type_marche":      "",
                "date_publication": date_pub_str,
                "date_limite":      date_limite_obj.strftime("%d/%m/%Y"),
                "lien_avis":        lien_avis,
                "lien_dossier":     "",
                "pays":             pays_canon,
            })

        except Exception as e:
            log.warning(f"GlobalTenders - erreur carte {i} : {e}")
            continue

    return resultats_page


# ─── Pagination ───────────────────────────────────────────────────────────────
def _aller_page_suivante(page, num_page: int) -> bool:
    """Clique sur le bouton page suivante. Retourne False si plus de page.

    Strategie robuste :
      1) trouve le lien de pagination (numero exact, sinon 'Next')
      2) capture une empreinte du contenu AVANT le clic
      3) clique, puis attend que le contenu de la 1ere carte change
         (au lieu de se fier a networkidle, peu fiable sur ce site)
    """
    page_suivante = num_page + 1

    try:
        empreinte_avant = page.locator("div.tender-wrap").first.inner_text()[:120]
    except Exception:
        empreinte_avant = None

    lien = page.get_by_role("link", name=str(page_suivante), exact=True)
    if lien.count() == 0:
        lien = page.locator(f"a:text-is('{page_suivante}')")
    if lien.count() == 0:
        lien = page.get_by_role("link", name="Next", exact=True)
    if lien.count() == 0:
        lien = page.locator("a:has-text('Next')")
    if lien.count() == 0:
        lien = page.locator("a[rel='next']")

    if lien.count() == 0 or not lien.first.is_visible():
        log.info(f"GlobalTenders - aucun lien de pagination trouve apres page {num_page}")
        return False

    try:
        lien.first.scroll_into_view_if_needed()
        lien.first.click()
    except Exception as e:
        log.warning(f"GlobalTenders - clic page suivante echoue : {e}")
        return False

    if empreinte_avant is not None:
        try:
            page.wait_for_function(
                """(avant) => {
                    const c = document.querySelector('div.tender-wrap');
                    return c && c.innerText.slice(0, 120) !== avant;
                }""",
                arg=empreinte_avant,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            log.warning(
                f"GlobalTenders - contenu inchange apres clic vers page {page_suivante} "
                f"(possible fin de pagination ou chargement lent)"
            )
            return False

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    return True


# ─── Scraper principal ────────────────────────────────────────────────────────
def scraper_globaltenders():
    """
    Scrape GlobalTenders pour les AO electrique en Afrique.
    Necessite GLOBALTENDERS_EMAIL et GLOBALTENDERS_PASSWORD dans .env.
    """
    resultats = []
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_GLOBALTENDERS)

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING GlobalTenders (Playwright)")
    print(f"#  Deadline minimum : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_GLOBALTENDERS}j)")
    print("#" * 70)
    log.info("GlobalTenders - ===== DEBUT SCRAPING =====")
    log.info(f"GlobalTenders - seuil deadline : {seuil_deadline}")

    compteurs = {
        "pages_traitees":             0,
        "total_cartes":               0,
        "rejet_pays":                 0,
        "rejet_signal_electrique":    0,
        "rejet_notification":         0,
        "rejet_national":             0,
        "rejet_domaine_bloque":       0,
        "rejet_deadline_absente":     0,
        "rejet_deadline_trop_proche": 0,
        "retenus":                    0,
    }
    pays_rejetes = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CONFIG.get("tuneps_headless", True))
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = ctx.new_page()
            page.set_default_timeout(30000)

            # ── Login ──
            succes_login = _tenter_login(page)
            if not succes_login:
                log.error("GlobalTenders - login echoue, scraping interrompu")
                browser.close()
                return []

            # ── Navigation vers les resultats ──
            log.info(f"GlobalTenders - navigation vers les resultats")
            try:
                page.goto(_URL_SEARCH, wait_until="networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                log.warning("GlobalTenders - networkidle timeout, on continue")

            # ── Pagination ──
            for num_page in range(1, NB_PAGES_MAX_GLOBALTENDERS + 1):
                log.info(f"GlobalTenders - === PAGE {num_page} ===")
                print(f"\n>>> GlobalTenders page {num_page}")

                ao_page = _extraire_cartes_page(page, seuil_deadline, compteurs, pays_rejetes)
                resultats.extend(ao_page)
                compteurs["pages_traitees"] += 1

                if not _aller_page_suivante(page, num_page):
                    log.info(f"GlobalTenders - fin de pagination (page {num_page})")
                    break

            browser.close()

    except Exception as e:
        log.error(f"GlobalTenders - ERREUR INATTENDUE : {e}")
        log.error(traceback.format_exc())

    # ── Bilan ──
    log.info("GlobalTenders - ===== BILAN =====")
    log.info(f"GlobalTenders - pages traitees                      : {compteurs['pages_traitees']}")
    log.info(f"GlobalTenders - cartes lues                         : {compteurs['total_cartes']}")
    log.info(f"GlobalTenders - rejetees (pays hors Afrique)        : {compteurs['rejet_pays']}")
    log.info(f"GlobalTenders - rejetees (pas signal elec.)         : {compteurs['rejet_signal_electrique']}")
    log.info(f"GlobalTenders - rejetees (notification)             : {compteurs['rejet_notification']}")
    log.info(f"GlobalTenders - rejetees (National/NCB)             : {compteurs['rejet_national']}")
    log.info(f"GlobalTenders - rejetees (domaine bloque)           : {compteurs['rejet_domaine_bloque']}")
    log.info(f"GlobalTenders - rejetees (deadline absente)         : {compteurs['rejet_deadline_absente']}")
    log.info(f"GlobalTenders - rejetees (deadline trop proche)     : {compteurs['rejet_deadline_trop_proche']}")
    log.info(f"GlobalTenders - RETENUS                              : {compteurs['retenus']}")
    if pays_rejetes:
        log.info(f"GlobalTenders - exemples pays rejetes : {list(pays_rejetes)[:5]}")

    print(f"\n#  FIN SCRAPING GlobalTenders -> {len(resultats)} AO retenus\n")
    log.info(f"GlobalTenders - RESULTAT FINAL : {len(resultats)} AO retenus")
    return deduplicer(resultats)