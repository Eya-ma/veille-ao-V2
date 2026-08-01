"""
Scraper J360 (Playwright -- la page charge ses resultats en JavaScript,
un spinner est visible au chargement initial, donc `requests` seul ne
recupererait jamais les AO).

[IMPORTANT -- A LIRE AVANT D'UTILISER CE FICHIER]
Je n'ai pas pu inspecter la structure HTML complete des resultats
(la capture recue montrait la page encore en chargement, avec la liste
des AO repliee dans les DevTools). Les selecteurs ci-dessous reposent
donc sur 2 choses fiables :
  1. Le schema d'URL confirme (?act=...&page=N)
  2. Le format des liens vers une fiche AO, confirme par la recherche
     web : /appels-d-offres/<id>-<slug>/ (ex: 24078353-59-connectorplugelec)
Tout le reste (date affichee dans la liste, secteur, etc.) est extrait
par une recherche de texte a proximite du lien plutot que par une classe
CSS precise -- volontairement plus tolerant, mais moins precis qu'un
vrai selecteur. A ajuster ensemble une fois le HTML reel du bloc
"col-lg-8" (zone des resultats) confirme.
"""
import re
import traceback
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import CONFIG, DELAI_MIN_JOURS_J360, NB_PAGES_MAX_J360, PAYS_AFRIQUE_FR_DGMARKET, PAYS_AFRIQUE_CIBLE, log
from utils import parse_date, normaliser_texte

_URL_BASE = "https://www.j360.info/appels-d-offres/"
_FILTRE_SECTEUR = "equipements-electriques-et-eclairage"

# Format confirme par la recherche web : /appels-d-offres/24078353-59-connectorplugelec/
_RE_LIEN_AO = re.compile(r"/appels-d-offres/\d+-[\w-]+/?$")

# Dates au format JJ/MM/AAAA ou AAAA-MM-JJ frequemment utilisees sur ce
# type de site -- recherchees dans le texte proche du lien, pas dans une
# cellule/colonne dediee (structure non confirmee).
_RE_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\b")

# [A CONFIRMER] Detection du pays par recherche de texte (titre + bloc
# autour du lien), faute de savoir ou le pays apparait vraiment dans le
# HTML reel. "International" est exclu ici : sur J360 ce mot generique
# apparaitrait trop souvent hors contexte pays. Trie du nom le plus long
# au plus court pour eviter qu'un nom court (ex: "Niger") ne matche a
# tort a l'interieur d'un nom plus long (ex: "Nigeria").
# J360 est bilingue (FR/EN) -- on combine la liste francaise (DGMarket)
# et la liste anglaise (World Bank) pour couvrir les deux cas, plutot
# que d'utiliser une seule des deux listes.
_TOUS_LES_PAYS_AFRIQUE = (
    {p for p in PAYS_AFRIQUE_FR_DGMARKET if p != "International"}
    | PAYS_AFRIQUE_CIBLE
)
_PAYS_CIBLE_NORMALISES = sorted(
    (
        (normaliser_texte(p).lower(), p)
        for p in _TOUS_LES_PAYS_AFRIQUE
    ),
    key=lambda x: -len(x[0]),
)


def _detecter_pays_cible(texte):
    """Retourne le libelle Afrique cible detecte dans le texte donne
    (titre + bloc autour du lien), ou None si aucun des pays cibles n'y
    apparait."""
    texte_norm = normaliser_texte(texte).lower()
    for norm, original in _PAYS_CIBLE_NORMALISES:
        if re.search(rf"\b{re.escape(norm)}\b", texte_norm):
            return original
    return None


_UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _attendre_challenge_anubis(page, timeout_ms=25000):
    """J360 est protege par Anubis/BotStopper (defi JavaScript de type
    proof-of-work, PAS de la detection comportementale -- cf. la doc
    officielle : un vrai navigateur qui execute le JS est cense passer
    automatiquement apres quelques secondes de calcul). Cette fonction
    detecte la page de defi ('You have been juged a robot' / balise
    <script id="anubis_challenge">) et attend sa resolution + redirection
    avant de continuer. Retourne True si on est passe, False si toujours
    bloque apres le timeout (auquel cas ce n'est probablement plus un
    probleme de configuration mais un blocage explicite du site)."""
    try:
        titre = page.title()
    except Exception:
        titre = ""
    est_challenge = (
        "robot" in titre.lower()
        or page.locator("#anubis_challenge").count() > 0
    )
    if not est_challenge:
        return True

    print(">>> Page de defi Anubis detectee -> attente de la resolution automatique...")
    try:
        page.wait_for_function(
            "() => !document.title.toLowerCase().includes('robot')",
            timeout=timeout_ms,
        )
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
        print(">>> Defi Anubis resolu, page reelle chargee")
        return True
    except PlaywrightTimeoutError:
        print(">>> Toujours bloque par Anubis apres le delai d'attente")
        return False


def scraper_j360():
    """
    Filtre applique cote site : secteur "Equipements electriques et
    eclairage" (via le parametre d'URL 'act'). Filtre applique cote
    script : pays Afrique cible (PAYS_AFRIQUE_FR_DGMARKET), detecte par
    recherche de texte dans le titre + le bloc autour du lien -- J360 ne
    proposant pas de filtre pays/region dans l'URL, contrairement a
    SBEE/DGCMEF/World Bank etc. A affiner une fois confirme ou le pays
    apparait vraiment dans la structure reelle (liste ou fiche detail).
    """
    resultats = []
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_J360)

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING J360 (Playwright)")
    print(f"#  Filtre source    : secteur = {_FILTRE_SECTEUR}")
    print(f"#  Deadline minimum : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_J360}j)")
    print(f"#  Mode headless    : {CONFIG.get('j360_headless', True)}")
    print("#" * 70)
    log.info("J360 - ===== DEBUT SCRAPING =====")

    compteurs = {
        "total_liens": 0,
        "rejet_deja_vu": 0,
        "rejet_pays_hors_cible": 0,
        "rejet_deadline_absente": 0,
        "rejet_deadline_trop_proche": 0,
        "retenus": 0,
    }
    liens_vus = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CONFIG.get("j360_headless", True))
            context = browser.new_context(user_agent=_UA_DESKTOP, locale="fr-FR")
            page = context.new_page()
            page.set_default_timeout(30000)

            num_page = 1
            while num_page <= NB_PAGES_MAX_J360:
                url = f"{_URL_BASE}?act={_FILTRE_SECTEUR}&page={num_page}"
                print(f"\n{'=' * 70}")
                print(f"  J360 - PAGE {num_page}")
                print(f"{'=' * 70}")
                print(f">>> Navigation vers {url}")
                log.info(f"J360 - ===== page {num_page} : {url} =====")

                page.goto(url, wait_until="domcontentloaded")

                if not _attendre_challenge_anubis(page):
                    print(">>> BLOQUE par Anubis -> capture de debug, arret du scraping J360")
                    page.screenshot(path=f"debug_j360_anubis_page{num_page}.png")
                    with open(f"debug_j360_anubis_page{num_page}.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    log.warning(f"J360 - bloque par Anubis page {num_page}, arret de la pagination")
                    break

                # Le spinner (#spinner, dot1/dot2) disparait une fois les
                # resultats charges en JS -- on attend sa disparition plutot
                # qu'un delai fixe.
                try:
                    page.wait_for_selector("#spinner", state="hidden", timeout=20000)
                except PlaywrightTimeoutError:
                    print(">>> #spinner toujours visible ou absent apres 20s (continue quand meme)")

                # Attente supplementaire que les liens de resultats soient
                # bien presents dans le DOM avant de les lire.
                try:
                    page.wait_for_selector(f"a[href*='/appels-d-offres/']", timeout=15000)
                except PlaywrightTimeoutError:
                    print(">>> AUCUN lien d'AO detecte apres 15s -> capture de debug")
                    page.screenshot(path=f"debug_j360_page{num_page}.png")
                    with open(f"debug_j360_page{num_page}.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    log.warning(f"J360 - aucun lien trouve page {num_page}, arret de la pagination")
                    break

                liens = page.locator("div.tenders-search a[href*='/appels-d-offres/']")
                nb_liens = liens.count()
                print(f">>> {nb_liens} lien(s) brut(s) trouve(s) sur la page")

                liens_page = []
                for i in range(nb_liens):
                    lien = liens.nth(i)
                    href = lien.get_attribute("href") or ""
                    if not _RE_LIEN_AO.search(href):
                        continue  # lien de nav/pagination/filtre, pas une fiche AO
                    titre = lien.inner_text().strip()
                    if not titre:
                        continue
                    liens_page.append((href, titre, lien))

                if not liens_page:
                    print(">>> Plus aucun resultat exploitable -> fin de pagination")
                    break

                compteurs["total_liens"] += len(liens_page)

                for i, (href, titre, lien) in enumerate(liens_page, 1):
                    url_avis = href if href.startswith("http") else f"https://www.j360.info{href}"
                    print(f"\n  --- P{num_page} / AO [{i:02d}/{len(liens_page)}] --- {titre[:80]}")

                    if url_avis in liens_vus:
                        print("    RESULTAT : ❌ REJETE (deja vu sur une page precedente)")
                        compteurs["rejet_deja_vu"] += 1
                        continue
                    liens_vus.add(url_avis)

                    # Texte du bloc autour du lien -- reutilise pour la date
                    # ET la detection du pays (une seule lecture DOM).
                    texte_bloc = ""
                    try:
                        bloc = lien.locator(
                            "xpath=ancestor::*[self::div or self::li][2]"
                        )
                        texte_bloc = bloc.inner_text()
                    except Exception as e:
                        print(f"    [DEBUG ERREUR xpath] >>> {e}")
                        log.debug(f"J360 - bloc parent non trouve pour '{titre[:50]}' : {e}")
                        
                    if i == 1 and num_page == 1:
                        try:
                            print(f"\n    [DEBUG HTML COMPLET] >>>\n{bloc.inner_html()}")
                        except Exception as e:
                            print(f"    [DEBUG HTML ERREUR] >>> {e}")

                    # [A CONFIRMER] Recherche d'une date a proximite du lien,
                    # via le texte du bloc parent -- pas de selecteur CSS
                    # dedie confirme pour l'instant.
                    # La seule date affichee sur la carte J360 est celle
                    # sous "TEMPS RESTANT", qui EST la date limite (pas une
                    # date de publication) -- confirme par capture d'ecran.
                    date_pub = ""
                    m = _RE_DATE.search(texte_bloc)
                    if m:
                        date_pub = m.group(1)
                        print(f"    [DEBUG DATE] >>> date trouvee dans texte_bloc : {date_pub}")

                    # [A CONFIRMER] Filtre Afrique cible : le pays n'est pas
                    # forcement visible dans la liste, on cherche donc le nom
                    # d'un pays cible dans le titre + le texte du bloc. Si
                    # aucun pays cible n'est detecte, l'AO est rejete --
                    # attention, ca peut aussi rejeter a tort un AO africain
                    # dont le pays n'apparait que sur la fiche detail (a
                    # verifier une fois le HTML reel confirme).
                    pays_detecte = _detecter_pays_cible(titre + " " + texte_bloc)
                    if not pays_detecte:
                        print("    RESULTAT : ❌ REJETE (aucun pays Afrique cible detecte)")
                        compteurs["rejet_pays_hors_cible"] += 1
                        continue

                    # Confirme par capture d'ecran : la date sous "TEMPS
                    # RESTANT" sur la carte EST la date limite -- on
                    # reutilise donc la date deja trouvee par regex dans
                    # texte_bloc (variable date_pub) au lieu de la laisser
                    # vide.
                    date_limite = date_pub

                    if not date_limite:
                        print("    RESULTAT : ❌ REJETE (date limite non trouvee -- a implementer)")
                        compteurs["rejet_deadline_absente"] += 1
                        continue

                    date_limite_obj = parse_date(date_limite)
                    if date_limite_obj and date_limite_obj < seuil_deadline:
                        print(f"    RESULTAT : ❌ REJETE (deadline trop proche : {date_limite})")
                        compteurs["rejet_deadline_trop_proche"] += 1
                        continue

                    print(f"    RESULTAT : ✅ RETENU (pays : {pays_detecte})")
                    compteurs["retenus"] += 1
                    resultats.append({
                        "titre": titre,
                        "pays": pays_detecte,
                        "date_pub": "", 
                        "date_limite": date_limite,
                        "url_avis": url_avis,
                        "url_dossier": url_avis,
                    })

                num_page += 1

            browser.close()

    except Exception as e:
        print(f"\n❌ ERREUR J360 : {e}")
        log.error(f"J360 - erreur : {e}")
        log.error(traceback.format_exc())

    print(f"\n{'=' * 70}")
    print(f"  J360 - RECAPITULATIF")
    print(f"{'=' * 70}")
    for cle, valeur in compteurs.items():
        print(f"  {cle:30s} : {valeur}")
    log.info(f"J360 - RESULTAT FINAL : {len(resultats)} AO retenus")
    return resultats