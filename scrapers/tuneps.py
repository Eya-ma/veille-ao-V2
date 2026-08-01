"""Scraper TUNEPS (Playwright, filtre Angular Material "Classification detaillee").
Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import traceback
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    CONFIG, DELAI_MIN_JOURS_TUNEPS, NB_PAGES_MAX_TUNEPS,
    _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, _RE_SIGNAL_ELECTRIQUE_AR_TUNEPS, log,
)
from utils import normaliser_texte, parse_date, url_propre
from historique import deduplicer

_RE_MONTANT_TND = re.compile(
    r'(\d+(?:[\s.,]\d{3})*[.,]\d{3})\s*TND',
    re.IGNORECASE,
)


def _extraire_details_tuneps(detail_page, lien_avis):
    """
    Ouvre la page d'avis TUNEPS dans un onglet Playwright dedie (detail_page)
    et extrait :
      - le nom de l'acheteur public (tableau "Informations generales")
      - le(s) cautionnement(s) provisoire(s), via une recherche du motif de
        montant ("X XXX,XXX TND" ou variantes de separateurs) dans le texte
        de la page plutot que via la structure exacte du tableau, car le
        tableau "Informations par lot ou article" semble se charger de
        facon asynchrone (apres le reste de la page) -> une extraction
        basee sur la structure DOM stricte peut arriver trop tot et ne
        rien trouver.
    Retourne (acheteur_public: str, caution: str). Chaine vide si non trouve
    ou en cas d'erreur (ne bloque jamais le scraping principal).
    """
    acheteur_public = ""
    caution = ""
    try:
        detail_page.goto(lien_avis, wait_until="domcontentloaded", timeout=30000)
        detail_page.wait_for_selector("text=Informations générales", timeout=15000)

        # -- Acheteur public --
        try:
            ligne_acheteur = detail_page.locator("tr", has_text="Nom acheteur public")
            if ligne_acheteur.count() > 0:
                cellules = ligne_acheteur.first.locator("td")
                if cellules.count() >= 2:
                    acheteur_public = cellules.nth(1).inner_text().strip()
        except Exception as e:
            log.debug(f"TUNEPS detail - acheteur public non trouve ({lien_avis}) : {e}")

        # -- Cautionnement(s) provisoire(s) + Objet du lot associe --
        lots_trouves = []
        try:
            detail_page.wait_for_function(
                """() => /\\d[\\d\\s.,]*\\d\\s*TND/.test(document.body.innerText)""",
                timeout=10000,
            )
        except PlaywrightTimeoutError:
            log.debug(f"TUNEPS detail - aucun montant TND apparu apres 10s ({lien_avis})")

        try:
            # [FIX] "Informations par lot ou article" est parfois un titre
            # AU-DESSUS du tableau (hors <table>), donc .filter(has_text=...)
            # sur "table" peut ne rien trouver. On cherche donc le conteneur
            # global qui a ce texte, puis on prend le PREMIER tableau qui suit.
            conteneur_section = detail_page.locator(
                "*:has-text('Informations par lot ou article')"
            ).last
            tableau_lots = conteneur_section.locator("xpath=following::table[1]")
            if tableau_lots.count() == 0:
                tableau_lots = detail_page.locator("table").filter(has_text="Informations par lot ou article")

            if tableau_lots.count() > 0:
                lignes_lots = tableau_lots.first.locator("tbody tr")
                nb_lignes_lots = lignes_lots.count()
                log.debug(f"TUNEPS detail - tableau lots trouve, {nb_lignes_lots} ligne(s) ({lien_avis})")
                for i in range(nb_lignes_lots):
                    cellules_lot = lignes_lots.nth(i).locator("td")
                    nb_cell_lot = cellules_lot.count()
                    textes_lot = [cellules_lot.nth(j).inner_text().strip() for j in range(nb_cell_lot)]
                    log.debug(f"TUNEPS detail - lot {i} cellules brutes ({nb_cell_lot}) : {textes_lot}")
                    if nb_cell_lot < 2:
                        continue
                    # Recherche du montant TND dans N'IMPORTE QUELLE cellule
                    # de la ligne (plus robuste qu'un index fixe), et objet
                    # = la cellule la plus longue qui n'est pas le montant.
                    montant = ""
                    idx_montant = -1
                    for j, txt in enumerate(textes_lot):
                        m = _RE_MONTANT_TND.search(txt)
                        if m:
                            montant = m.group(1).strip() + " TND"
                            idx_montant = j
                            break
                    if not montant:
                        continue
                    candidats_objet = [t for j, t in enumerate(textes_lot) if j != idx_montant and len(t) > 5]
                    objet_lot = max(candidats_objet, key=len) if candidats_objet else ""
                    lots_trouves.append((objet_lot, montant))
                log.debug(f"TUNEPS detail - lots trouves ({lien_avis}) : {lots_trouves}")
            else:
                log.debug(f"TUNEPS detail - tableau 'Informations par lot ou article' introuvable ({lien_avis})")
        except Exception as e:
            log.debug(f"TUNEPS detail - erreur extraction lots (objet+caution) ({lien_avis}) : {e}")

        # [FALLBACK] Si l'approche tableau n'a rien donne, on retombe sur
        # l'ancienne methode (recherche de motifs TND dans le texte brut de
        # la section), qui donne au moins le montant sans l'objet du lot.
        if not lots_trouves:
            try:
                texte_page = detail_page.inner_text("body")
                idx_section = texte_page.find("Informations par lot ou article")
                texte_lots = texte_page[idx_section:] if idx_section != -1 else texte_page
                montants_bruts = _RE_MONTANT_TND.findall(texte_lots)
                lots_trouves = [("", m.strip() + " TND") for m in montants_bruts]
                log.debug(f"TUNEPS detail - fallback texte, montants trouves ({lien_avis}) : {lots_trouves}")
            except Exception as e:
                log.debug(f"TUNEPS detail - erreur fallback texte cautionnement ({lien_avis}) : {e}")

        if len(lots_trouves) == 1:
            objet, montant = lots_trouves[0]
            caution = f"{montant} ({objet})" if objet else montant
        elif len(lots_trouves) > 1:
            caution = ", ".join(
                f"Lot {i + 1} : {montant}" + (f" ({objet})" if objet else "")
                for i, (objet, montant) in enumerate(lots_trouves)
            )

    except Exception as e:
        log.debug(f"TUNEPS detail - erreur ouverture page avis ({lien_avis}) : {e}")

    return acheteur_public, caution

def scraper_tuneps():
    """
    Seul filtre applique cote site : Classification detaillee = Electricite
    (Type commande volontairement laisse vide -> remonte Travaux ET
    Fournitures/Services lies a l'electricite).
    """
    resultats = []
    url = "https://www.tuneps.tn/portail/offres"
    seuil_deadline = date.today() + timedelta(days=DELAI_MIN_JOURS_TUNEPS)

    print("\n" + "#" * 70)
    print("#  DEBUT SCRAPING TUNEPS (Playwright)")
    print(f"#  Filtre source    : Classification detaillee = Electricite")
    print(f"#  Deadline minimum : {seuil_deadline} (aujourd'hui + {DELAI_MIN_JOURS_TUNEPS}j)")
    print(f"#  Mode headless    : {CONFIG.get('tuneps_headless', True)}")
    print("#" * 70)
    log.info("TUNEPS - ===== DEBUT SCRAPING =====")

    compteurs = {
        "total_lignes": 0,
        "rejet_deadline_absente": 0,
        "rejet_deadline_trop_proche": 0,
        "rejet_domaine_bloque": 0,
        "retenus": 0,
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CONFIG.get("tuneps_headless", True))
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30000)
            detail_page = context.new_page()
            detail_page.set_default_timeout(20000)

            print(f"\n>>> Navigation vers {url}")
            page.goto(url, wait_until="domcontentloaded")
            print(">>> Attente du chargement du bouton de filtres avances...")
            page.wait_for_selector("a:has-text('add_circle_outline')", timeout=30000)
            print(">>> Clic sur l'icone '+' (deploiement des criteres avances)")
            page.locator("a").filter(has_text="add_circle_outline").click()

            # [OBLIGATOIRE] "Classification detaillee" reste desactive tant
            # qu'aucun "Type commande" n'est choisi (champ dependant cote
            # site). On selectionne donc "Travaux" en premier.
            print(">>> Ouverture du champ 'Type commande'")
            champ_type_commande = page.locator("mat-form-field").filter(
                has_text="Type commande"
            ).locator("mat-select")
            champ_type_commande.click()
            print(">>> Selection 'Travaux'")
            page.get_by_role("option", name="Travaux", exact=True).click()
            print(">>> Ouverture du champ 'Classification detaillee'")
            champ_classification = page.locator("mat-form-field").filter(
                has_text="Classification"
            ).locator("mat-select")
            champ_classification.click()
            print(">>> Selection 'Electricite'")
            page.get_by_role("option", name="Electricité", exact=True).click()

            print(">>> Clic sur 'Rechercher'")
            page.get_by_role("button", name="Rechercher").click()

            print(">>> Attente du tableau de resultats...")
            try:
                page.wait_for_selector("table tbody tr", timeout=20000)
            except PlaywrightTimeoutError:
                print(">>> AUCUN tableau detecte apres 20s -> capture de debug")
                page.screenshot(path="debug_tuneps_tableau.png")
                with open("debug_tuneps_tableau.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                raise RuntimeError("Tableau des AO TUNEPS non trouve")

            num_page_tuneps = 1
            while num_page_tuneps <= NB_PAGES_MAX_TUNEPS:
                print(f"\n{'=' * 70}")
                print(f"  TUNEPS - PAGE {num_page_tuneps}")
                print(f"{'=' * 70}")
                log.info(f"TUNEPS - ===== page {num_page_tuneps} =====")

                lignes = page.locator("table tbody tr")
                nb_lignes = lignes.count()
                print(f">>> {nb_lignes} ligne(s) trouvee(s)")
                compteurs["total_lignes"] += nb_lignes

                for i in range(nb_lignes):
                    ligne = lignes.nth(i)
                    cellules = ligne.locator("td")
                    nb_cell = cellules.count()
                    textes = [cellules.nth(j).inner_text().strip() for j in range(nb_cell)]
                    print(f"\n  --- P{num_page_tuneps} / Ligne [{i+1:02d}/{nb_lignes}] --- {textes}")

                    if nb_cell < 6:
                        print("    RESULTAT : ❌ REJETE (moins de 6 colonnes)")
                        continue

                    num_ao           = textes[0]
                    acheteur         = textes[1]
                    date_pub         = textes[2]
                    objet            = textes[3]
                    date_limite_brut = textes[4]
                    id_interne       = textes[5] if nb_cell > 5 else ""

                    date_limite_obj = parse_date(date_limite_brut)
                    print(f"    DATE LIMITE : brut={date_limite_brut!r} -> parsee={date_limite_obj}")

                    if not date_limite_obj:
                        compteurs["rejet_deadline_absente"] += 1
                        print("    RESULTAT    : ❌ REJETE (date non parsee)")
                        continue
                    if date_limite_obj < seuil_deadline:
                        compteurs["rejet_deadline_trop_proche"] += 1
                        print(f"    RESULTAT    : ❌ REJETE (limite < seuil {seuil_deadline})")
                        continue
                    if _DOMAINES_BLOQUES.search(objet):
                        compteurs["rejet_domaine_bloque"] += 1
                        print("    RESULTAT    : ❌ REJETE (domaine bloque)")
                        continue

                    # Filtre local supplementaire : le filtre "Classification
                    # detaillee = Electricite" cote site TUNEPS semble parfois
                    # s'appliquer au niveau d'un lot et non du titre affiche
                    # (ex: AO hopital multi-lots dont le titre montre un lot
                    # non-electrique). On exige donc un signal electrique
                    # explicite dans le titre, en francais/anglais OU en arabe.
                    objet_norm = normaliser_texte(objet)
                    signal_fr_en = _RE_SIGNAL_ELECTRIQUE.search(objet_norm)
                    signal_ar    = _RE_SIGNAL_ELECTRIQUE_AR_TUNEPS.search(objet)
                    if not signal_fr_en and not signal_ar:
                        compteurs.setdefault("rejet_pas_signal_electrique", 0)
                        compteurs["rejet_pas_signal_electrique"] += 1
                        print("    RESULTAT    : ❌ REJETE (aucun signal electrique FR/EN/AR dans le titre)")
                        continue

                    # URL construite directement (pas besoin de cliquer) :
                    # format confirme : /portail/offres/details/{id_interne}/{num_ao}
                    if id_interne:
                        lien_avis = f"https://www.tuneps.tn/portail/offres/details/{id_interne}/{num_ao}"
                        lien_avis = url_propre(lien_avis)
                    else:
                        lien_avis = url
                        print("    [ATTENTION] id_interne absent -> fallback URL generique")

                    date_limite_str = date_limite_obj.strftime("%d/%m/%Y")
                    compteurs["retenus"] += 1
                    print("    RESULTAT    : ✅ ACCEPTE")
                    log.info(f"TUNEPS - AO RETENU : [{num_ao}] {objet[:70]} | limite={date_limite_str}")

                    acheteur_public_detail, caution_detail = _extraire_details_tuneps(detail_page, lien_avis)
                    print(f"    [DETAIL] acheteur_public={acheteur_public_detail!r} | caution={caution_detail!r}")
                    log.info(f"TUNEPS - detail extrait : acheteur={acheteur_public_detail!r} | caution={caution_detail!r}")

                    resultats.append({
                        "titre": objet, "reference": num_ao, "type_marche": "",
                        "date_publication": date_pub, "date_limite": date_limite_str,
                        "lien_avis": lien_avis, "lien_dossier": "",
                        "pays": "Tunisie", "organisme": acheteur,
                        "acheteur_public": acheteur_public_detail,
                        "caution": caution_detail,
                    })

                # [DEBUG] Angular Material expose des classes CSS stables sur
                # le bouton "page suivante" du paginator (contrairement aux
                # classes ng-tns-... generees dynamiquement). On les essaie
                # en priorite, avec fallback sur le role/nom accessible.
                bouton_suivant = page.locator(
                    "button.mat-paginator-navigation-next, "
                    "button.mat-mdc-paginator-navigation-next"
                )
                if bouton_suivant.count() == 0:
                    bouton_suivant = page.get_by_role("button", name="Page suivante")

                nb_trouves = bouton_suivant.count()
                est_desactive = bouton_suivant.first.is_disabled() if nb_trouves else None
                print(f">>> [DEBUG pagination] bouton trouve={nb_trouves} | desactive={est_desactive}")
                log.info(f"TUNEPS - [DEBUG] bouton suivant : count={nb_trouves} | disabled={est_desactive}")

                if nb_trouves == 0 or est_desactive:
                    print(">>> Fin de pagination (pas de bouton / desactive)")
                    log.info(f"TUNEPS - fin pagination page {num_page_tuneps}")
                    break

                avant = ""
                try:
                    avant = page.locator("table tbody tr").first.locator("td").first.inner_text().strip()
                except Exception:
                    pass
                bouton_suivant.first.click()

                change = False
                for _ in range(40):
                    try:
                        apres = page.locator("table tbody tr").first.locator("td").first.inner_text().strip()
                    except Exception:
                        apres = ""
                    if apres and apres != avant:
                        change = True
                        break
                    page.wait_for_timeout(500)
                if not change:
                    print(">>> Contenu inchange -> nouvelle tentative de clic")
                    log.warning(f"TUNEPS - contenu inchange page {num_page_tuneps} -> retry clic")
                    bouton_suivant.first.click()
                    for _ in range(40):
                        try:
                            apres = page.locator("table tbody tr").first.locator("td").first.inner_text().strip()
                        except Exception:
                            apres = ""
                        if apres and apres != avant:
                            change = True
                            break
                        page.wait_for_timeout(500)
                    if not change:
                        print(">>> Toujours inchange apres 2e tentative -> arret par securite")
                        log.warning(f"TUNEPS - contenu inchange apres retry page {num_page_tuneps} -> arret")
                        break
                num_page_tuneps += 1
                
            detail_page.close()
            context.close()
            browser.close()

    except Exception as e:
        print(f"\n!!! ERREUR TUNEPS : {e}")
        log.error(f"TUNEPS - erreur : {e}")
        log.error(traceback.format_exc())

    log.info("TUNEPS - ===== BILAN =====")
    log.info(f"TUNEPS - lignes scannees : {compteurs['total_lignes']} | retenus : {compteurs['retenus']}")
    print(f"\n#  FIN SCRAPING TUNEPS -> {len(resultats)} AO retenus\n")
    return deduplicer(resultats)

