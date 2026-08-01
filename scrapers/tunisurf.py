"""Scraper TuniSurf (login + extraction via Playwright, site JS/Next.js).
Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import traceback
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import CONFIG, CATEGORIES_CIBLE_TUNISURF, DELAI_MIN_JOURS_TUNISURF, _RE_SIGNAL_ELECTRIQUE, log
from utils import normaliser_texte
from historique import deduplicer

_MOIS_FR_ABBR_TUNISURF = {
    "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date_tunisurf(texte):
    """
    Parse le format de date specifique a TuniSurf, ex :
    '15 juil.\n2026' ou '3 août\n2026' (jour + mois abrege francais,
    parfois suivi d'un point, separe de l'annee par un retour a la ligne).
    """
    if not texte:
        return None
    texte_norm = normaliser_texte(texte).lower().replace("\n", " ")
    m = re.search(r'(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})', texte_norm)
    if not m:
        log.debug(f"[TUNISURF DATE] Echec parsing pour valeur brute : {texte!r}")
        return None
    jour, mois_brut, annee = m.groups()
    mois_cle = mois_brut.rstrip(".")[:5]
    mois_num = None
    for cle, num in _MOIS_FR_ABBR_TUNISURF.items():
        if mois_cle.startswith(cle) or cle.startswith(mois_cle):
            mois_num = num
            break
    if not mois_num:
        log.debug(f"[TUNISURF DATE] Mois non reconnu : {mois_brut!r} (texte brut={texte!r})")
        return None
    try:
        return date(int(annee), mois_num, int(jour))
    except ValueError:
        log.debug(f"[TUNISURF DATE] Date invalide construite depuis {texte!r}")
        return None

# ═══════════════════════════════════════════════════════════════
#  TUNISURF -- login + extraction via Playwright (site JS/Next.js)
#  [MODIFIE v2] Filtre sur la date limite RESTAURE (>= aujourd'hui +
#  DELAI_MIN_JOURS_TUNISURF), + gestion de la PAGINATION : le tableau
#  TuniSurf affiche ~100 lignes par page ("201-300 / 504" par ex.),
#  donc on parcourt les pages suivantes jusqu'a la derniere ou un
#  garde-fou de securite, pour couvrir bien plus que les 100
#  premiers AO.
# ═══════════════════════════════════════════════════════════════

NB_PAGES_MAX_TUNISURF = 10  # garde-fou de securite (10 x ~100 lignes = 1000 max)


def _cliquer_page_suivante_tunisurf(page):
    """
    Multi-strategie pour cliquer sur le bouton 'page suivante' de la
    pagination TuniSurf (ex: bloc '201-300 / 504' avec fleches < >
    en bas de tableau).
    Retourne True si un clic a ete effectue avec succes, False si
    aucun bouton 'suivant' n'a ete trouve OU s'il est desactive
    (= derniere page atteinte).
    """
    # [FIX headless] Attente explicite (pas juste un delai fixe) que le
    # bloc de pagination "X-Y / Z" soit bien present dans le DOM avant
    # de chercher le bouton. Plus fiable qu'un wait_for_timeout fixe,
    # car ca s'adapte a la vitesse reelle de chargement.
    try:
        page.wait_for_selector("text=/\\d+\\s*-\\s*\\d+\\s*\\/\\s*\\d+/", timeout=8000)
    except PlaywrightTimeoutError:
        print("    [PAGINATION] Bloc de pagination 'X-Y / Z' non trouve apres 8s")
        log.debug("TuniSurf - pagination : bloc 'X-Y / Z' introuvable apres attente explicite")

    print("    [PAGINATION] Recherche du bouton 'page suivante'...")

    # -- Strategie 1 : aria-label / accessible name explicite --
    for label in ["Suivant", "Next", "next page", "page suivante", ">"]:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() > 0:
                cible = btn.first
                if cible.is_disabled():
                    print(f"    [PAGINATION] Bouton trouve (label={label!r}) mais DESACTIVE -> derniere page")
                    log.info("TuniSurf - pagination : bouton suivant desactive (derniere page)")
                    return False
                print(f"    [PAGINATION] Bouton trouve via label={label!r} -> clic")
                cible.click()
                log.info(f"TuniSurf - pagination : clic 'suivant' via label={label!r}")
                return True
        except Exception as e:
            print(f"    [PAGINATION] Strategie label={label!r} a echoue : {e}")

    # -- Strategie 2 : conteneur du texte 'X-Y / Z' -> dernier bouton du bloc --
    try:
        conteneur = page.locator("text=/\\d+\\s*-\\s*\\d+\\s*/\\s*\\d+/").locator("xpath=..")
        if conteneur.count() > 0:
            boutons = conteneur.first.locator("button")
            nb_boutons = boutons.count()
            print(f"    [PAGINATION] Conteneur 'X-Y / Z' trouve, {nb_boutons} bouton(s) a l'interieur")
            if nb_boutons >= 2:
                bouton_suivant = boutons.nth(nb_boutons - 1)
                if bouton_suivant.is_disabled():
                    print("    [PAGINATION] Bouton (strategie 2) DESACTIVE -> derniere page")
                    log.info("TuniSurf - pagination : bouton suivant (strat.2) desactive (derniere page)")
                    return False
                bouton_suivant.click()
                print("    [PAGINATION] Clic effectue (strategie 2)")
                log.info("TuniSurf - pagination : clic 'suivant' via strategie 2 (conteneur texte)")
                return True
    except Exception as e:
        print(f"    [PAGINATION] Strategie 2 a echoue : {e}")

    print("    [PAGINATION] AUCUN bouton 'suivant' exploitable trouve -> arret pagination")
    log.warning("TuniSurf - pagination : aucun bouton 'suivant' trouve (toutes strategies)")
    return False


def scraper_tunisurf():
    resultats = []
    url_login = "https://tunisurf.com/login"
    url_ao    = "https://tunisurf.com/ao"

    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_TUNISURF)

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING TuniSurf (Playwright)")
    print(f"#  Categories cibles : {CATEGORIES_CIBLE_TUNISURF}")
    print(f"#  Deadline minimum  : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_TUNISURF}j)")
    print(f"#  Pagination        : jusqu'a {NB_PAGES_MAX_TUNISURF} page(s) (garde-fou)")
    print(f"#  Mode headless     : {CONFIG['tunisurf_headless']}")
    print("#" * 70)
    log.info("TuniSurf - ===== DEBUT SCRAPING (avec pagination) =====")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=CONFIG["tunisurf_headless"],
                args=["--headless=new"] if CONFIG["tunisurf_headless"] else [],
            )
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30000)

            # ── LOGIN (selecteurs confirmes via codegen) ──
            print(f"\n>>> Navigation vers {url_login}")
            page.goto(url_login, wait_until="networkidle")
            print(">>> Page login chargee")

            page.get_by_role("textbox", name="Email").click()
            page.get_by_role("textbox", name="Email").fill(CONFIG["tunisurf_email"])
            print(">>> Email rempli")

            page.get_by_role("textbox", name="Mot de passe").click()
            page.get_by_role("textbox", name="Mot de passe").fill(CONFIG["tunisurf_password"])
            print(">>> Mot de passe rempli")

            page.get_by_role("button", name="Se connecter").click()
            print(">>> Bouton 'Se connecter' clique")

            print(">>> Attente de la redirection post-login...")
            try:
                page.wait_for_url("**/ao**", timeout=15000)
                print(f">>> Redirection OK -> URL actuelle : {page.url}")
            except PlaywrightTimeoutError:
                print(f">>> PAS de redirection detectee vers /ao -> URL actuelle : {page.url}")
                page.screenshot(path="debug_tunisurf_apres_login.png")
                print(">>> Capture d'ecran sauvegardee : debug_tunisurf_apres_login.png")

            if "/ao" not in page.url:
                print(f">>> Navigation manuelle vers {url_ao}")
                page.goto(url_ao, wait_until="networkidle")

            # ── ATTENTE DU TABLEAU ──
            print(">>> Attente du chargement du tableau des AO...")
            try:
                page.wait_for_selector("table tbody tr", timeout=20000)
                print(">>> Tableau detecte (structure)")
            except PlaywrightTimeoutError:
                print(">>> AUCUN tableau detecte apres 20s -> capture de debug")
                page.screenshot(path="debug_tunisurf_tableau.png")
                with open("debug_tunisurf_tableau.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(">>> Fichiers de debug sauvegardes : debug_tunisurf_tableau.png / .html")
                raise RuntimeError("Tableau des AO non trouve")

            # [FIX] La structure <tr> peut apparaitre avant que le JS
            # n'injecte les vraies donnees dans les <td> (lignes "squelette"
            # vides, comme observe dans les logs). On attend donc
            # explicitement qu'au moins la 1ere cellule de la 1ere ligne
            # contienne du texte, via polling, avant de lire le tableau.
            print(">>> Attente que les cellules du tableau contiennent des donnees reelles...")
            contenu_charge = False
            for tentative in range(40):  # jusqu'a ~40 x 500ms = 20s max
                premiere_cellule = page.locator("table tbody tr").first.locator("td").first
                try:
                    texte_test = premiere_cellule.inner_text().strip()
                except Exception:
                    texte_test = ""
                if texte_test:
                    contenu_charge = True
                    print(f">>> Contenu detecte apres {tentative * 0.5:.1f}s (ex: {texte_test[:40]!r})")
                    break
                page.wait_for_timeout(500)

            if not contenu_charge:
                print(">>> ATTENTION : le tableau reste vide apres 10s -> capture de debug")
                page.screenshot(path="debug_tunisurf_tableau_vide.png")
                with open("debug_tunisurf_tableau_vide.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(">>> Fichiers de debug sauvegardes : debug_tunisurf_tableau_vide.png / .html")
                log.warning("TuniSurf - tableau reste vide apres attente de contenu (voir captures de debug)")

            # ── BOUCLE DE PAGINATION ──
            # TuniSurf affiche les AO par page (~100 lignes), avec un
            # total pouvant depasser 500 (cf capture d'ecran fournie :
            # "201-300 / 504"). On parcourt donc toutes les pages
            # disponibles, jusqu'a la derniere ou jusqu'au garde-fou
            # NB_PAGES_MAX_TUNISURF.
            num_page_tunisurf = 1
            arret_complet     = False

            while num_page_tunisurf <= NB_PAGES_MAX_TUNISURF and not arret_complet:
                print(f"\n{'=' * 70}")
                print(f"  TUNISURF - PAGE {num_page_tunisurf} (garde-fou max = {NB_PAGES_MAX_TUNISURF})")
                print(f"{'=' * 70}")
                log.info(f"TuniSurf - ===== traitement page {num_page_tunisurf} =====")

                lignes = page.locator("table tbody tr")
                nb_lignes = lignes.count()
                print(f">>> {nb_lignes} ligne(s) trouvee(s) dans le tableau (page {num_page_tunisurf})")
                log.info(f"TuniSurf - page {num_page_tunisurf} : {nb_lignes} lignes brutes trouvees")

                for i in range(nb_lignes):
                    ligne = lignes.nth(i)
                    cellules = ligne.locator("td")
                    nb_cell = cellules.count()
                    textes = [cellules.nth(j).inner_text().strip() for j in range(nb_cell)]

                    print(f"\n  --- Page {num_page_tunisurf} / Ligne [{i+1:03d}/{nb_lignes}] ---")
                    print(f"    CELLULES BRUTES ({nb_cell} colonnes) : {textes}")

                    if nb_cell < 6:
                        print(f"    RESULTAT : ❌ REJETE (moins de 6 colonnes, format inattendu)")
                        continue

                    categorie   = textes[0]
                    emetteur    = textes[1]
                    num_ao      = textes[2]
                    description = textes[3]
                    parution    = textes[4]
                    limite      = textes[5]

                    categorie_norm = normaliser_texte(categorie).lower()
                    categorie_ok = any(c in categorie_norm for c in CATEGORIES_CIBLE_TUNISURF)
                    print(f"    CATEGORIE       : {categorie!r} -> {'✅ MATCH' if categorie_ok else '❌ pas dans la liste cible'}")

                    if not categorie_ok:
                        continue

                    # [FIX] La categorie TuniSurf "equipements electriques et
                    # electroniques" est trop large (elle inclut des systemes
                    # meteorologiques, informatiques, etc. qui ne sont pas
                    # lies a l'electricite au sens metier). On exige donc un
                    # signal electrique explicite dans le titre, comme deja
                    # fait pour TUNEPS.
                    description_norm = normaliser_texte(description)
                    signal_titre_ok = _RE_SIGNAL_ELECTRIQUE.search(description_norm)
                    print(f"    SIGNAL ELEC     : {'✅ trouve' if signal_titre_ok else '❌ aucun'}")

                    if not signal_titre_ok:
                        print(f"    RESULTAT        : ❌ REJETE (categorie large mais aucun signal electrique dans le titre)")
                        continue

                    # Filtre sur la date limite : on ne garde l'AO que
                    # si sa deadline est encore a au moins
                    # DELAI_MIN_JOURS_TUNISURF jours d'aujourd'hui.
                    date_limite_obj = _parse_date_tunisurf(limite)
                    print(f"    DATE LIMITE     : brut={limite!r} -> parsee={date_limite_obj}")

                    if not date_limite_obj:
                        print(f"    RESULTAT        : ❌ REJETE (date limite non parsee)")
                        continue
                    if date_limite_obj < seuil_deadline:
                        print(f"    RESULTAT        : ❌ REJETE (limite={date_limite_obj} < seuil={seuil_deadline})")
                        continue
                    date_limite_str = date_limite_obj.strftime("%d/%m/%Y")

                    # [STABLE - CLIC DESACTIVE] Le clic sur TuniSurf s'est
                    # avere intermittent et instable (parfois recupere un
                    # vrai lien, parfois casse le rendu du tableau apres
                    # go_back, produisant des lignes vides). On utilise donc
                    # le lien generique de la liste, fiable a 100%, avec le
                    # numero de reference affiche pour recherche manuelle
                    # (voir label "lien_generique" dans exporter_excel()).
                    url_avis_ligne = url_ao
                            
                    print(f"    RESULTAT        : ✅ ACCEPTE")
                    log.info(f"TuniSurf - AO RETENU (page {num_page_tunisurf}) : [{categorie}] {description[:70]} | limite={date_limite_str} | lien={url_avis_ligne}")
                    resultats.append({
                        "titre":            description,
                        "reference":        num_ao,
                        "type_marche":      categorie,
                        "date_publication": parution,
                        "date_limite":      date_limite_str,
                        "lien_avis":        url_avis_ligne,
                        "lien_dossier":     "",
                        "pays":             "Tunisie",
                        "organisme":        emetteur,
                        "lien_generique":   (url_avis_ligne == url_ao),
                    })

                if arret_complet:
                    print(f"\n>>> Arret complet demande pendant la page {num_page_tunisurf} -> pas de tentative de page suivante")
                    break

                # ── Fin de la page courante : tentative de passage a la page suivante ──
                print(f"\n>>> Fin du traitement de la page {num_page_tunisurf} ({len(resultats)} AO retenus au total jusqu'ici)")
                premiere_cellule_avant = ""
                try:
                    premiere_cellule_avant = page.locator("table tbody tr").first.locator("td").first.inner_text().strip()
                except Exception:
                    pass

                a_clique = _cliquer_page_suivante_tunisurf(page)
                if not a_clique:
                    print(">>> Pas de page suivante disponible -> fin de la pagination TuniSurf")
                    log.info(f"TuniSurf - fin de pagination apres la page {num_page_tunisurf} (pas de bouton suivant / desactive)")
                    break

                contenu_change = False
                for _ in range(40):  # jusqu'a ~20s
                    try:
                        premiere_cellule_apres = page.locator("table tbody tr").first.locator("td").first.inner_text().strip()
                    except Exception:
                        premiere_cellule_apres = ""
                    if premiere_cellule_apres and premiere_cellule_apres != premiere_cellule_avant:
                        contenu_change = True
                        break
                    page.wait_for_timeout(500)

                if not contenu_change:
                    print(">>> ATTENTION : le contenu du tableau ne semble pas avoir change apres le clic 'suivant' -> arret de la pagination par securite")
                    log.warning(f"TuniSurf - contenu tableau inchange apres clic pagination (page {num_page_tunisurf}) -> arret par securite")
                    break

                num_page_tunisurf += 1

            if num_page_tunisurf > NB_PAGES_MAX_TUNISURF:
                print(f"\n>>> Garde-fou de pagination atteint ({NB_PAGES_MAX_TUNISURF} pages) -> arret force")
                log.warning(f"TuniSurf - garde-fou de pagination atteint ({NB_PAGES_MAX_TUNISURF} pages) -> arret force")

            context.close()
            browser.close()

    except Exception as e:
        print(f"\n!!! ERREUR TuniSurf : {e}")
        log.error(f"TuniSurf - erreur : {e}")
        log.error(traceback.format_exc())

    print(f"\n{'#' * 70}")
    print(f"#  FIN SCRAPING TuniSurf -> {len(resultats)} AO retenus (toutes pages confondues)")
    print(f"{'#' * 70}\n")
    log.info(f"TuniSurf - RESULTAT FINAL : {len(resultats)} AO retenus")
    return deduplicer(resultats)
