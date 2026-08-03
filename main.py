"""
=============================================================
  VEILLE AUTOMATIQUE - APPELS D'OFFRES ELECTRICITE & TRAVAUX
  VERSION 10.18 (decoupee en modules)

  Point d'entree : orchestre le scraping multi-sources, le filtrage,
  la deduplication, l'export Excel et les notifications email/Teams.
  Comportement identique a veille_ao_1_1.py, seule l'organisation
  du code a change.
=============================================================
"""
import sys
import time
import schedule
from datetime import date, datetime

from config import CONFIG, log
from utils import jours_a_couvrir
from filtrage import _charger_modele_embedding
from historique import charger_historique, sauvegarder_historique, afficher, normaliser_ao, generer_id_ao, dedupliquer_inter_sources
from utils import ao_est_expire
from export_excel import exporter_excel
from notifications import envoyer_email, notifier_teams

from scrapers.sbee import scraper_sbee
from scrapers.afdb import scraper_afdb
from scrapers.dgcmef import scraper_dgcmef
from scrapers.worldbank import scraper_worldbank
from scrapers.tunisurf import scraper_tunisurf
from scrapers.tuneps import scraper_tuneps
from scrapers.opecfund import scraper_opecfund
from scrapers.isdb import scraper_isdb
from scrapers.afd_dgmarket import scraper_afd_dgmarket
from scrapers.developmentaid import scraper_developmentaid
from scrapers.globaltenders import scraper_globaltenders
from scrapers.j360_multipays import scraper_j360_multipays

def main():
    mode_test = "--test" in sys.argv
    print("\n" + "=" * 65)
    print("  VEILLE APPELS D\'OFFRES - v10.18 (SBEE : filtre date limite)")
    print(f"  {datetime.now().strftime('%d/%m/%Y a %H:%M:%S')}")
    jours_noms = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
    print(f"  {jours_noms[date.today().weekday()]} - fenetre : {jours_a_couvrir()} jour(s)")
    if mode_test:
        print("  MODE TEST - historique ignore, tous les AO affiches")
    print("=" * 65 + "\n")
    log.info("=" * 65)
    log.info(f"DEMARRAGE EXECUTION | mode_test={mode_test} | fenetre={jours_a_couvrir()} jour(s)")
    log.info("=" * 65)

    t_debut_global = time.time()
    _charger_modele_embedding()
    historique = charger_historique(CONFIG["historique_file"])
    print(f"Historique : {len(historique)} entrees\n")
    tous_les_ao = []

    log.info("--- Scraping SBEE Benin...")
    t0 = time.time()
    ao_sbee = scraper_sbee()
    log.info(f"SBEE -> {len(ao_sbee)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "SBEE Benin") for ao in ao_sbee)

    log.info("--- Scraping AfDB / BAD...")
    t0 = time.time()
    ao_afdb = scraper_afdb()
    log.info(f"AfDB -> {len(ao_afdb)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "AfDB / BAD") for ao in ao_afdb)

    log.info("--- Scraping DGCMEF Burkina Faso...")
    t0 = time.time()
    ao_dgcmef = scraper_dgcmef()
    log.info(f"DGCMEF -> {len(ao_dgcmef)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "DGCMEF Burkina Faso") for ao in ao_dgcmef)

    log.info("--- Scraping World Bank...")
    t0 = time.time()
    ao_wb = scraper_worldbank()
    log.info(f"World Bank -> {len(ao_wb)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "World Bank") for ao in ao_wb)

    log.info("--- Scraping TuniSurf...")
    ao_tunisurf = scraper_tunisurf()
    log.info(f"TuniSurf -> {len(ao_tunisurf)} AO")
    tous_les_ao.extend(normaliser_ao(ao, "TuniSurf") for ao in ao_tunisurf)

    log.info("--- Scraping TUNEPS...")
    t0 = time.time()
    ao_tuneps = scraper_tuneps()
    log.info(f"TUNEPS -> {len(ao_tuneps)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "TUNEPS") for ao in ao_tuneps)

    log.info("--- Scraping OPEC Fund...")
    t0 = time.time()
    ao_opec = scraper_opecfund()
    log.info(f"OPEC Fund -> {len(ao_opec)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "OPEC Fund") for ao in ao_opec)

    log.info("--- Scraping IsDB...")
    t0 = time.time()
    ao_isdb = scraper_isdb()
    log.info(f"IsDB -> {len(ao_isdb)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "IsDB") for ao in ao_isdb)

    log.info("--- Scraping AFD DGMarket...")
    t0 = time.time()
    ao_dgmarket = scraper_afd_dgmarket()
    log.info(f"AFD DGMarket -> {len(ao_dgmarket)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "AFD DGMarket") for ao in ao_dgmarket)

    log.info("--- Scraping DevelopmentAid...")
    t0 = time.time()
    ao_devaid = scraper_developmentaid()
    log.info(f"DevelopmentAid -> {len(ao_devaid)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "DevelopmentAid") for ao in ao_devaid)
    
    log.info("--- Scraping GlobalTenders...")
    t0 = time.time()
    ao_globaltenders = scraper_globaltenders()
    log.info(f"GlobalTenders -> {len(ao_globaltenders)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "GlobalTenders") for ao in ao_globaltenders)
    
    log.info("--- Scraping J360 (multi-pays)...")
    t0 = time.time()
    ao_j360 = scraper_j360_multipays()
    log.info(f"J360 -> {len(ao_j360)} AO (duree totale : {time.time() - t0:.2f}s)")
    tous_les_ao.extend(normaliser_ao(ao, "J360") for ao in ao_j360)

    log.info(
        "RECAPITULATIF PAR SOURCE -> "
        f"SBEE={len(ao_sbee)} | AfDB={len(ao_afdb)} | DGCMEF={len(ao_dgcmef)} | World Bank={len(ao_wb)} "
        f"| TuniSurf={len(ao_tunisurf)} | TUNEPS={len(ao_tuneps)} | OPEC Fund={len(ao_opec)} | IsDB={len(ao_isdb)} "
        f"| AFD DGMarket={len(ao_dgmarket)} | DevelopmentAid={len(ao_devaid)} "
        f"| GlobalTenders={len(ao_globaltenders)} "
        f"| J360={len(ao_j360)} "
        f"| TOTAL avant filtre expiration={len(tous_les_ao)}"
    )
    
    avant_dedup_inter = len(tous_les_ao)
    tous_les_ao = dedupliquer_inter_sources(tous_les_ao)
    doublons_inter = avant_dedup_inter - len(tous_les_ao)
    if doublons_inter:
        log.info(f"{doublons_inter} doublon(s) inter-sources retire(s)")

    # [DEBUG TEMPORAIRE] Repere les AO quasi-vides (titre vide/absent)
    # pour identifier quelle(s) source(s) generent ces lignes fantomes.
    ao_vides = [ao for ao in tous_les_ao if not ao.get("titre", "").strip() or ao.get("titre") == "Sans titre"]
    if ao_vides:
        print(f"\n⚠️  {len(ao_vides)} AO quasi-vide(s) detecte(s) :")
        for ao in ao_vides:
            print(f"    source={ao.get('source')!r} | titre={ao.get('titre')!r} | pays={ao.get('pays')!r} | url_avis={ao.get('url_avis')!r}")
        log.warning(f"[DEBUG] {len(ao_vides)} AO quasi-vide(s), sources : {[ao.get('source') for ao in ao_vides]}")

    avant       = len(tous_les_ao)
    tous_les_ao = [ao for ao in tous_les_ao if not ao_est_expire(ao)]
    expires     = avant - len(tous_les_ao)
    if expires:
        log.info(f"{expires} AO expires filtres")
    if mode_test:
        nouveaux = tous_les_ao
        log.info("MODE TEST actif -> tous les AO actifs sont consideres comme 'nouveaux'")
    else:
        nouveaux = []
        for ao in tous_les_ao:
            cle = generer_id_ao(ao)
            if cle not in historique:
                nouveaux.append(ao)
                historique.add(cle)
        sauvegarder_historique(CONFIG["historique_file"], historique)
    print(f"\nTOTAL AO ACTIFS : {len(tous_les_ao)}")
    print(f"AO A ENVOYER (email - nouveaux uniquement) : {len(nouveaux)}")
    log.info(f"TOTAL AO ACTIFS (apres filtre expiration) : {len(tous_les_ao)}")
    log.info(f"AO NOUVEAUX (a notifier par email) : {len(nouveaux)}")
    if nouveaux:
        for ao in nouveaux:
            afficher(ao)
    else:
        print("\nAucun appel d\'offres a envoyer par email")

    exporter_excel(tous_les_ao, CONFIG["excel_file"])


    envoyer_email(nouveaux, mode_test=mode_test)
    #notifier_teams(nouveaux, mode_test=mode_test)

    print(f"\nHistorique : {len(historique)} entrees")
    print(f"Excel      : {CONFIG['excel_file']} (cumulatif, jamais reinitialise)")
    print(f"Log        : veille_ao.log\n")
    log.info(f"EXECUTION TERMINEE en {time.time() - t_debut_global:.2f}s au total")
    log.info("=" * 65)
    return nouveaux


def lancer_planificateur():
    heure = CONFIG["heure_execution"]
    print(f"\nMode planifie - execution en semaine a {heure}")
    log.info(f"[PLANIFICATEUR] Demarrage, execution prevue chaque jour de semaine a {heure}")
    for jour in [schedule.every().monday, schedule.every().tuesday,
                 schedule.every().wednesday, schedule.every().thursday,
                 schedule.every().friday]:
        jour.at(heure).do(main)
    main()
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    if "--planifier" in sys.argv:
        lancer_planificateur()
    else:
        main()
