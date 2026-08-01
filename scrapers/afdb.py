"""Scraper AfDB / BAD. Issu du decoupage de veille_ao_1_1.py (v10.18)."""
import re
import time
import traceback
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

from config import CONFIG, HEADERS, _DOMAINES_BLOQUES, _RE_SIGNAL_ELECTRIQUE, log
from utils import session, normaliser_texte
from historique import deduplicer

def _parse_date_afdb(texte):
    if not texte:
        return ""
    texte = texte.strip()
    m = re.search(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', texte)
    if m:
        try:
            d = datetime.strptime(m.group(0), "%d-%b-%Y")
            return d.strftime("%d/%m/%Y")
        except ValueError:
            pass
    m2 = re.search(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', texte)
    if m2:
        return m2.group(0).replace("-", "/")
    return ""


def _parser_type_pays_titre_afdb(texte_complet):
    """
    Parse le texte du lien AfDB, format standard :
        'AOI - Sénégal - Travaux de réalisation de réseaux...'
        'SPN - Kenya - Consultancy Services for...'
    Retourne (type_marche, pays, titre_sans_prefixe).
    Si le format ne correspond pas (pas assez de ' - '), retourne
    (None, None, texte_complet) pour ne rien perdre silencieusement.
    """
    parties = texte_complet.split(" - ", 2)
    if len(parties) < 3:
        print(f"    >>> [PARSING] format inattendu (pas de 'TYPE - PAYS - TITRE') : {texte_complet[:80]!r}")
        return None, None, texte_complet
    type_marche = parties[0].strip()
    pays        = parties[1].strip()
    titre       = parties[2].strip()
    print(f"    >>> [PARSING] type={type_marche!r} | pays={pays!r} | titre={titre[:60]!r}")
    return type_marche, pays, titre


def _scraper_detail_afdb(lien_detail):
    """
    Recupere uniquement le lien PDF telechargeable depuis la page detail.
    [NOTE] La date limite n'est PAS recuperee ici : elle n'existe que dans
    le corps texte du PDF, donc non fiable en extraction automatique.
    """
    print(f"\n    >>> [DETAIL AfDB] GET {lien_detail}")
    if not lien_detail:
        return None
    try:
        r_det = session.get(lien_detail, headers=HEADERS, timeout=CONFIG["timeout"])
        r_det.raise_for_status()
        print(f"    >>> [DETAIL AfDB] HTTP {r_det.status_code} | {len(r_det.text)} chars")
    except Exception as e:
        print(f"    >>> [DETAIL AfDB] ERREUR GET : {e}")
        log.debug(f"AfDB detail - erreur GET {lien_detail[:60]} : {e}")
        return None

    soup_det = BeautifulSoup(r_det.text, "lxml")
    detail   = {}

    for a in soup_det.find_all("a", href=True):
        href_d = a["href"]
        ta_d   = a.get_text(strip=True).lower()
        if any(kw in ta_d for kw in ["download", "dao", "dossier", "tender document", "bid document"]):
            full_d = href_d if href_d.startswith("http") else "https://www.afdb.org" + href_d
            detail["lien_dossier"] = full_d
            print(f"    >>> [DETAIL AfDB] lien PDF trouve (mot-cle '{ta_d[:30]}') : {full_d[-80:]}")
            break
        if href_d.lower().endswith(".pdf"):
            full_d = href_d if href_d.startswith("http") else "https://www.afdb.org" + href_d
            detail.setdefault("lien_dossier", full_d)
            print(f"    >>> [DETAIL AfDB] lien PDF trouve (extension .pdf) : {full_d[-80:]}")

    if not detail.get("lien_dossier"):
        print(f"    >>> [DETAIL AfDB] AUCUN lien PDF trouve sur cette page")

    return detail


def scraper_afdb():
    resultats = []

    URL_BASE = (
        "https://www.afdb.org/en/documents/project-related-procurement"
        "/procurement-notices/invitation-for-bids"
    )
    NB_PAGES_MAX  = 5      
    FENETRE_JOURS = 45     
    MOIS_FR = {
        "janvier": "January", "février": "February", "mars": "March",
        "avril": "April",     "mai": "May",           "juin": "June",
        "juillet": "July",    "août": "August",       "septembre": "September",
        "octobre": "October", "novembre": "November", "décembre": "December",
    }

    _RE_SIGNAL_ELEC_AFDB = re.compile(
        _RE_SIGNAL_ELECTRIQUE.pattern + r"|\b\d+\s*kV\b|\bsubstation\b|\bpower\s+plant\b"
        r"|\bsolar\b|\bphotovoltaic\b|\belectricit\b|\benerg",
        re.IGNORECASE,
    )

    def _parse_date_afdb_fr(texte):
        if not texte:
            return None
        texte = texte.strip()
        texte_en = texte.lower()
        for fr, en in MOIS_FR.items():
            texte_en = re.sub(rf'\b{fr}\b', en.lower(), texte_en)
        m = re.search(r'(\d{1,2})-([a-z]+)-(\d{4})', texte_en)
        if m:
            for fmt in ["%d-%B-%Y", "%d-%b-%Y"]:
                try:
                    return datetime.strptime(m.group(0), fmt).date()
                except ValueError:
                    continue
        m2 = re.search(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', texte)
        if m2:
            try:
                return datetime.strptime(m2.group(0).replace("-", "/"), "%d/%m/%Y").date()
            except ValueError:
                pass
        return None

    def _date_str(d):
        return d.strftime("%d/%m/%Y") if d else ""

    vus_liens = set()
    seuil_date = date.today() - timedelta(days=FENETRE_JOURS)

    print("\n" + "#" * 70)
    print(f"#  DEBUT SCRAPING AfDB - Filtre : AOI uniquement (SPN/autres exclus)")
    print(f"#  URL de base    : {URL_BASE}")
    print(f"#  Pages a couvrir: {NB_PAGES_MAX} (page 0 a {NB_PAGES_MAX - 1})")
    print(f"#  Fenetre de securite (publication) : {FENETRE_JOURS} jours -> seuil = {seuil_date}")
    print("#" * 70)

    total_tags        = 0
    total_type_aoi     = 0
    total_valides      = 0

    for num_pagination in range(NB_PAGES_MAX):
        url_page = f"{URL_BASE}?page={num_pagination}"
        print(f"\n{'=' * 60}")
        print(f"  PAGE {num_pagination + 1}/{NB_PAGES_MAX}  ->  {url_page}")
        print(f"{'=' * 60}")
        log.info(f"AfDB - scraping page {num_pagination} : {url_page}")

        try:
            r = session.get(url_page, headers=HEADERS, timeout=CONFIG["timeout"])
            r.raise_for_status()
            print(f"  HTTP {r.status_code} | taille reponse : {len(r.text)} caracteres")
            log.info(f"AfDB p.{num_pagination} - HTTP {r.status_code} | {len(r.text)} chars")

            soup = BeautifulSoup(r.text, "lxml")
            pub_tags = soup.find_all(string=re.compile(r'Publication\s+Date', re.I))
            total_tags += len(pub_tags)

            print(f"  -> {len(pub_tags)} bloc(s) 'Publication Date' trouve(s) sur cette page")
            log.info(f"AfDB p.{num_pagination} - {len(pub_tags)} tags 'Publication Date'")

            if not pub_tags:
                print(f"  -> PAGE VIDE au 1er essai -> nouvelle tentative dans 3s")
                log.info(f"AfDB p.{num_pagination} - page vide au 1er essai -> retry")
                time.sleep(3)
                r_retry = session.get(url_page, headers=HEADERS, timeout=CONFIG["timeout"])
                soup_retry = BeautifulSoup(r_retry.text, "lxml")
                pub_tags_retry = soup_retry.find_all(string=re.compile(r'Publication\s+Date', re.I))
                if not pub_tags_retry:
                    print(f"  -> PAGE VIDE confirmee apres retry -> arret pagination")
                    log.info(f"AfDB p.{num_pagination} - page vide confirmee -> arret pagination")
                    break
                else:
                    print(f"  -> Retry reussi : {len(pub_tags_retry)} bloc(s) trouve(s)")
                    log.info(f"AfDB p.{num_pagination} - retry reussi : {len(pub_tags_retry)} tags")
                    soup = soup_retry
                    pub_tags = pub_tags_retry
                    total_tags += len(pub_tags)

            valides_page = 0
            aoi_page     = 0

            for idx, pub_tag in enumerate(pub_tags, 1):
                print(f"\n  --- AfDB p.{num_pagination} [{idx:02d}/{len(pub_tags)}] ---")

                # -- Date de publication --
                date_brut = ""
                parent_tag = pub_tag.parent
                if parent_tag:
                    parent_txt = parent_tag.get_text(separator=" ", strip=True)
                    parent_txt_clean = re.sub(
                        r'Publication\s+Date\s*[:\-]?\s*', '', parent_txt, flags=re.IGNORECASE
                    ).strip()
                    m_txt = re.search(r'\d{1,2}-[A-Za-zéû]+-\d{4}', parent_txt_clean)
                    if m_txt:
                        date_brut = m_txt.group(0)
                    else:
                        m_num = re.search(r'\d{2}[/\-]\d{2}[/\-]\d{4}', parent_txt_clean)
                        if m_num:
                            date_brut = m_num.group(0)

                if not date_brut and parent_tag and parent_tag.parent:
                    gp_txt = parent_tag.parent.get_text(separator=" ", strip=True)
                    m_gp = re.search(
                        r'Publication\s+Date\s*[:\-]?\s*'
                        r'(\d{1,2}-[A-Za-zéû]+-\d{4}|\d{2}[/\-]\d{2}[/\-]\d{4})',
                        gp_txt, re.IGNORECASE,
                    )
                    if m_gp:
                        date_brut = m_gp.group(1)

                print(f"    DATE BRUTE     : {date_brut!r}")
                date_pub_obj = _parse_date_afdb_fr(date_brut)
                date_pub_str = _date_str(date_pub_obj)
                print(f"    DATE PARSEE    : {date_pub_str!r}")

                if date_pub_obj and date_pub_obj < seuil_date:
                    print(f"    RESULTAT       : ❌ REJETE (trop ancien, seuil={seuil_date})")
                    continue
                if not date_pub_obj:
                    print(f"    ATTENTION      : date non parsee, on continue quand meme")

                # -- Lien + texte complet ("TYPE - PAYS - TITRE") --
                conteneur = pub_tag.parent
                lien_tag = None
                for _ in range(6):
                    if conteneur is None:
                        break
                    lien_tag = conteneur.find("a", href=True)
                    if lien_tag:
                        break
                    conteneur = conteneur.parent

                if not lien_tag:
                    print(f"    RESULTAT       : ❌ REJETE (aucun lien <a> trouve)")
                    continue

                texte_complet = lien_tag.get_text(strip=True)
                href = lien_tag["href"]
                lien = href if href.startswith("http") else "https://www.afdb.org" + href

                print(f"    TEXTE COMPLET  : {texte_complet[:100]!r}")
                print(f"    LIEN           : ...{lien[-70:]}")

                if lien in vus_liens:
                    print(f"    RESULTAT       : ❌ REJETE (doublon deja vu)")
                    continue
                vus_liens.add(lien)

                # -- Parsing TYPE - PAYS - TITRE --
                type_marche, pays, titre = _parser_type_pays_titre_afdb(texte_complet)

                # -- Filtre : AOI uniquement --
                if not type_marche or type_marche.upper() != "AOI":
                    print(f"    RESULTAT       : ❌ REJETE (type={type_marche!r}, on ne garde que AOI)")
                    continue
                aoi_page += 1

                # -- Filtre : signal electricite sur le TITRE uniquement --
                titre_norm   = normaliser_texte(titre)
                signal_titre = _RE_SIGNAL_ELEC_AFDB.search(titre_norm)
                print(f"    SIGNAL TITRE   : {signal_titre.group() if signal_titre else 'AUCUN'!r}")

                if not signal_titre:
                    print(f"    RESULTAT       : ❌ REJETE (pas de signal electricite dans le titre)")
                    continue

                if _DOMAINES_BLOQUES.search(titre):
                    print(f"    RESULTAT       : ❌ REJETE (domaine bloque)")
                    continue

                # -- Lien PDF via page detail (uniquement pour les AO retenus) --
                detail       = _scraper_detail_afdb(lien)
                lien_dossier = (detail or {}).get("lien_dossier", "")

                print(f"    PAYS           : {pays!r}")
                print(f"    LIEN PDF       : {lien_dossier[-70:] if lien_dossier else 'NON TROUVE'}")
                print(f"    RESULTAT       : ✅ ACCEPTE")
                log.info(
                    f"AfDB p.{num_pagination}[{idx:02d}] VALIDE | AOI | pays={pays!r} | "
                    f"pub={date_pub_str} | pdf={'oui' if lien_dossier else 'non'} | {titre[:60]!r}"
                )

                resultats.append({
                    "titre":            titre,        # titre SANS le prefixe "AOI - Pays -"
                    "pays_detail":      pays,          # colonne Pays separee (normaliser_ao l'utilise deja)
                    "reference":        "",
                    "type_marche":      "AOI",
                    "date_publication": date_pub_str,
                    "date_limite":      "",            
                    "lien_avis":        lien,
                    "lien_dossier":     lien_dossier,
                })
                valides_page += 1

            total_type_aoi += aoi_page
            total_valides  += valides_page
            print(f"\n  >> BILAN PAGE {num_pagination + 1} : {aoi_page} de type AOI | {valides_page} valides (electricite) sur {len(pub_tags)} total")
            log.info(f"AfDB p.{num_pagination} - BILAN : {aoi_page} AOI | {valides_page} valides / {len(pub_tags)}")

        except Exception as e:
            print(f"  !!! ERREUR sur page {num_pagination} : {e}")
            log.error(f"AfDB p.{num_pagination} - erreur : {e}")
            log.error(traceback.format_exc())

    print(f"\n{'#' * 70}")
    print(f"#  FIN SCRAPING AfDB")
    print(f"#  Total blocs 'Publication Date' rencontres (toutes pages) : {total_tags}")
    print(f"#  Total de type AOI (avant filtre electricite)             : {total_type_aoi}")
    print(f"#  Total AO valides retenus (avant dedup)                   : {total_valides}")
    print(f"#  Total AO apres deduplication                             : {len(deduplicer(resultats))}")
    print(f"{'#' * 70}\n")
    log.info(f"AfDB - RESULTAT FINAL : {len(resultats)} AO retenus")

    return deduplicer(resultats)
