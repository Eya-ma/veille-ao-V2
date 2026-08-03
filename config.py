"""
Configuration, constantes et expressions regulieres partagees par
tous les modules du projet (aucune logique metier ici).
Issu du decoupage de veille_ao_1_1.py (v10.18).
"""
import os
import re
import logging
import urllib3
from dotenv import load_dotenv

load_dotenv()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("veille_ao.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger()

CONFIG = {
    "email_from":       os.environ.get("EMAIL_FROM", ""),
    "email_password":   os.environ.get("EMAIL_PASSWORD", ""),
    "email_to":         os.environ.get("EMAIL_TO", ""),

    #"email_from_2":     os.environ.get("EMAIL_FROM_2", ""),
    #"email_password_2": os.environ.get("EMAIL_PASSWORD_2", ""),
    #"email_to_2":       os.environ.get("EMAIL_TO_2", ""),

    "smtp_server":    "smtp.gmail.com",
    "smtp_port":      587,
    "smtp_port_ssl":  465,
    "historique_file": "resultats_veille.json",
    "excel_file":      "veille_ao_resultats.xlsx",
    "timeout": 45,
    "heure_execution": "18:00",
    "score_structure_seuil": 3,
    "score_rapide_seuil":    3,
    "embedding_seuil":       0.35,
    "sbee_jours_min_avant_limite": 14,
    "tunisurf_email":    os.environ.get("TUNISURF_EMAIL", ""),
    "tunisurf_password": os.environ.get("TUNISURF_PASSWORD", ""),
    "globaltenders_email":    os.environ.get("GLOBALTENDERS_EMAIL", ""),
    "globaltenders_password": os.environ.get("GLOBALTENDERS_PASSWORD", ""),
    "j360_email":    os.environ.get("J360_EMAIL", ""),
    "j360_password": os.environ.get("J360_PASSWORD", ""),
    "tunisurf_headless":  True,
    "tuneps_headless":    True,
    "j360_headless": True,
}

ENTETES_ATTENDUS = [
    "Date ajout", "Source", "Pays", "Titre",
    "Date publication", "Date limite", "Lien page directe", "Lien PDF complet"
]

MOTS_CLES_AFRIQUE = [
    "electricite", "electrique", "photovoltaique", "solaire",
    "transformateur", "compteur", "eclairage", "cablage",
    "HTA", "HTB", "basse tension", "electrification",
    "groupe electrogene", "centrale electrique",
    "ligne electrique", "reseau electrique", "energie electrique",
    "onduleur", "panneau solaire", "batterie solaire",
    "branchement electrique", "poste de transformation",
    "generateur", "energie renouvelable", "mini-reseau",
    "fournitures", "services courants", "travaux", "prestations",
    "acquisition", "logiciels", "prestataire",
]

CATEGORIES_CIBLE_TUNISURF = [
    "télécommunications",
    "telecommunications",
    "equipements electriques et electroniques",
    "équipements électriques et électroniques",
    "electricite",
    "telecom",
]
DELAI_MIN_JOURS_TUNISURF = 7
DELAI_MIN_JOURS_DGMARKET = 14
DELAI_MIN_JOURS_OPECFUND = 14
DELAI_MIN_JOURS_ISDB = 14
NB_PAGES_MAX_ISDB = 5
DELAI_MIN_JOURS_TUNEPS = 7
DELAI_MIN_JOURS_DEVAID = 14
NB_RESULTATS_PAR_PAGE_DEVAID = 300  # pour eviter la pagination (97 < 300)
NB_PAGES_MAX_TUNEPS    = 15
DELAI_MIN_JOURS_GLOBALTENDERS = 14
NB_PAGES_MAX_GLOBALTENDERS    = 50
DELAI_MIN_JOURS_J360 = 14
NB_PAGES_MAX_J360     = 10
DELAI_MIN_JOURS_J360_TUNISIE = 7

# ─────────────────────────────────────────────────────────────
#  Liste des pays Afrique (libelles francais) pour AFD DGMarket.
#  Volontairement exclu : Maroc (coherent avec PAYS_AFRIQUE_CIBLE
#  utilise pour World Bank). "International" est inclus car ce
#  site l'utilise aussi pour des programmes regionaux couvrant
#  l'Afrique (ex: Sahel, Afrique de l'Ouest).
# ─────────────────────────────────────────────────────────────
PAYS_AFRIQUE_FR_DGMARKET = {
    "Algérie", "Bénin",
    "Burkina Faso", "Burundi", "Cameroun", "Cap-Vert", "Comores",
    "Congo", "Côte d'Ivoire", "Djibouti", "Égypte", "Érythrée",
    "Gabon", "Gambie", "Ghana", "Guinée",
    "Guinée équatoriale", "Guinée-Bissao", "Kenya",
    "Liberia", "Libye", "Madagascar", "Mali",
    "Maurice", "Mauritanie", "Niger", "Nigeria",
    "Ouganda", "République centrafricaine",
    "République démocratique du Congo", "Rwanda",
    "Sao Tomé-et-Principe", "Sénégal", "Seychelles", "Sierra Leone",
    "Somalie", "Tanzanie", "Tchad", "Togo",
    "Tunisie", "International",
}

_MOIS_DGMARKET = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "avr": 4, "apr": 4,
    "mai": 5, "may": 5, "jun": 6, "juin": 6, "jul": 7, "juil": 7,
    "aou": 8, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11,
    "dec": 12,
}

_MOIS_EN_OPECFUND = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

PAYS_AFRIQUE_CIBLE = {
    # Afrique de l'Ouest
    "Benin", "Burkina Faso", "Niger", "Mali", "Senegal", "Guinea",
    "Guinea-Bissau", "Sierra Leone", "Liberia", "Cote d'Ivoire",
    "Ghana", "Togo", "Gambia, The", "Cabo Verde", "Mauritania",
    "Nigeria",
    # Afrique Centrale
    "Cameroon", "Chad", "Central African Republic",
    "Congo, Republic of", "Congo, Democratic Republic of", "Gabon",
    "Equatorial Guinea", "Sao Tome and Principe",
    # Afrique de l'Est
    "Kenya", "Uganda", "Tanzania", "Rwanda", "Burundi",
    "Somalia", "Djibouti", "Eritrea",
    # Afrique du Nord (Maroc exclu)
    "Egypt, Arab Republic of", "Libya", "Tunisia", "Algeria",
}


NOTICE_TYPES_CIBLE = {
    "invitation for bids",
    "invitation for prequalification",
}

SIGNAUX_RAPIDES = [
    (r"electr|electr",                        2),
    (r"photovolta",                            2),
    (r"solaire|\bsolar\b",                     1),
    (r"transformateur|transform|\btransformer\b", 1),
    (r"ligne\s+(?:electrique|HTA|HTB|BT|MT)|\btransmission\s+line\b|\bdistribution\s+line\b", 2),
    (r"\bHTA\b|\bHTB\b|\b[BM]T\b",            1),
    (r"energie|energie|energy",                1),
    (r"reseau\s+electr|reseau\s+electr|\bpower\s+grid\b", 2),
    (r"groupe\s+electrog|groupe\s+electrog|\bgenerator\s+set\b|\bgenset\b", 2),
    (r"onduleur|panneau\s+solaire|batterie\s+solaire|\binverter\b|\bsolar\s+panel\b", 2),
    (r"branchement|raccordement|\bconnection\s+works\b", 1),
    (r"poste\s+de\s+transform|\bsubstation\b", 2),
    (r"centrale\s+electr|centrale\s+electr|\bpower\s+(?:plant|station)\b", 2),
    (r"mini.reseau|mini.reseau|\bmini.?grid\b", 2),
    (r"compteur|\bmeter(?:ing)?\b",            1),
    (r"eclairage|eclairage|\b(?:street\s+|public\s+)?lighting\b", 1),
    (r"cablage|cablage|\bcabling\b",           1),
    (r"generateur|generateur|\bgenerator\b",   1),
    (r"electrification|electrification",       2),
    (r"renouvelable|\brenewable\s+energy\b",   1),
    (r"\bappel\s+d.offres?\b|\binvitation\s+for\s+bids\b", 3),
    (r"\bavis\s+d.appel\b",                    3),
    (r"\b(?:dao|aon|aoi)\s*n[o]?\s*\d",        3),
    (r"\b(?:dao|aon|aoi|ifb|rfb)\b",           2),
    (r"fournitures?\s+et\s+services?|\bgoods\s+and\s+services\b", 2),
    (r"\btravaux\b|\bworks\b",                 1),
    (r"\bprestations?\b",                      1),
    (r"\bacquisition\b|\bprocurement\b",       1),
    (r"\brenouvellement\b",                    1),
    (r"\brecrutement\b",                       1),
    (r"n[o]\s*\d{4}[\-/]\d{2,}",              2),
    (r"/dao/|/aon/|/aoi/",                     2),
    (r"\bhydropower\b|\bhydroelectric\b",      2),
    (r"\bwind\s+(?:farm|turbine|power)\b",     2),
    (r"\b\d+\s*kV\b|\b\d+\s*MW\b|\b\d+\s*kW\b", 2),
    (r"disjoncteur\w*|\bcircuit\s+breaker\b",           2),
    (r"tableau\s+(?:electr\w*|de\s+distribution)|\bdistribution\s+board\b|\bswitchboard\b", 2),
    (r"armoire\s+electr\w*|coffret\s+electr\w*",         2),
    (r"mise\s+a\s+la\s+terre|\bearthing\b|\bgrounding\b", 2),
    (r"parafoudre\w*|\blightning\s+arrest\w*\b",         2),
    (r"pylone\w*\s+electr\w*|\belectric(?:al)?\s+pylon\b", 2),
    (r"cable\s+(?:HTA|HTB|BT|MT|electr\w*)|\bunderground\s+power\s+cable\b", 2),
    (r"poste\s+(?:HTA|HTB|MT|BT)\b",                     2),
    (r"kVA\b|\bkWh\b|\bMWh\b",                           1),
    (r"variateur\s+(?:de\s+vitesse|electr\w*)|\bVFD\b",  1),
    (r"batterie\s+de\s+stockage\s+(?:electr\w*|d.energie)|\bBESS\b", 2),
    (r"borne\s+de\s+recharge|\belectric\s+charging\s+station\b", 2),
    (r"\bSTEG\b",                                        2),
    (r"\bSENELEC\b|\bAMADER\b|\bEDM\b|\bENEO\b",         2),
    (r"\bANME\b",                                        2),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_RE_MARQUEUR_AO = re.compile(
    r"APPEL\s+D.OFFRES?|DEMANDE\s+DE\s+PRIX|AVIS\s+D.APPEL"
    r"|CONSULTATION\s+RESTREINTE|DEMANDE\s+DE\s+PROPOSITION"
    r"|DAO\s*N[o]|AON\s*N[o]|AOI\s*N[o]|AO\s*N[o]",
    re.IGNORECASE,
)

_RE_CATEGORIE = re.compile(
    r"^(Fournitures?(\s+et\s+Services?\s+courants?)?|Travaux|"
    r"Services?\s+(de\s+)?[Cc]onsultants?|Prestations?\s+intellectuelles?)$",
    re.IGNORECASE,
)

_RE_TYPES_REJETES = re.compile(
    r"(?:"
    r"r[ee]sultat\s+(?:de\s+)?(?:d[ee]pouillement|attribution|appel|s[ee]lection)"
    r"|avis\s+de\s+(?:r[ee]sultat|publication|attribution|non.?attribution)"
    r"|d[ee]cision\s+d.attribution"
    r"|proc[e]s.verbal"
    r"|march[e]\s+attribu[e]"
    r"|attributaire"
    r"|manifestation\s+d.int[e]r[e]t"
    r"|expression\s+d.int[e]r[e]t"
    r"|avis\s+[a]\s+manifestation"
    r"|compl[e]mentaire\s+de\s+la\s+base\s+de\s+donn[e]es"
    r"|base\s+de\s+donn[e]es\s+des\s+prestataires"
    r"|communiqu[e]\s*n[o]"
    r"|rectificatif"
    r")",
    re.IGNORECASE,
)

_RE_PARASITES = re.compile(
    r"^(?:Non\s+class|Non\s+retenu|Class[e]|Retenu|Attributaire|Conforme\s*:)"
    r"|^Lot\s+n[o]\s*\d+\s*:\s*Montant"
    r"|^(?:Dix|Vingt|Trente|Quarante|Cinquante|Soixante|Cent|Deux\s+cent"
    r"|Trois\s+cent|Quatre\s+cent|Cinq\s+cent|Six\s+cent|Sept\s+cent"
    r"|Huit\s+cent|Neuf\s+cent|Mille|Million)\s+"
    r"|SARL\s*\)?\s*Conforme"
    r"|er\s+Conforme\s+SARL"
    r"|garantie\s+de\s+soumission"
    r"|[Oo]ffre\s+anormalement\s+basse",
    re.IGNORECASE,
)

_DOMAINES_BLOQUES = re.compile(
    r"fibre\s+optique|reseau\s+informat|reseau\s+tele"
    r"|gardiennage|surveillance\s+(?:des\s+)?b[a]timents"
    r"|s[e]curit[e]\s+(?:physique|incendie|intervention)"
    r"|sant[e]\s+des\s+travailleurs"
    r"|assurance\s+sant[e]"
    r"|pharmacie|m[e]dicament|laboratoire\s+(?!electr)"
    r"|audit\s+financier"
    r"|nettoyage|restauration|pause.caf[e]|d[e]jeuner"
    r"|communication\s+et\s+visibilit[e]"
    r"|inventaire\s+des\s+immobilis"
    r"|logiciel\s+de\s+gestion(?!\s+d.[e]nergie)"
    r"|affichage\s+dynamique"
    r"|gestion\s+digitale"
    r"|bonbonnes?\s+d.eau"
    r"|fourniture\s+de\s+(?:repas|plateau|pause|d[e]jeuner)"
    r"|\bclimatiseur\b|\bclimatisation\b"
    r"|\bmobilier\b|\bameublement\b"
    r"|\bv[e]hicule\b|\bv[e]hicules\b|\bvoiture\b|\bauto\b"
    r"|\bcarburant\b|\bgazole\b"
    r"|\bpalettes?\s+de\s+stockage\b"
    r"|\bimprimes?\b|\bfournitures\s+de\s+bureau\b"
    r"|\bconstruction\s+d.[e]cole\b"
    r"|\br[e]habilitation\s+d.infrastructures\s+administratives\b"
    r"|\binfrastructures?\s+sanitaires?\b"
    r"|\bscanner\b|\bimprimante\b|\bswitch\b"
    r"|licences?\s+de\s+logiciels?\s+de\s+(?:bo[i]tiers?|s[e]curit[e]|antivirus|firewall)"
    r"|renouvellement\s+de\s+licences?\s+de\s+logiciels?"
    r"|bo[i]tiers?\s+de\s+s[e]curit[e]"
    r"|antivirus|firewall|pare.feu"
    r"|t[e]l[e]communications?|t[e]l[e]phonie"
    r"|fr[e]quences?\s+radio|spectre\s+radio"
    r"|services?\s+postaux?|courrier\s+postal"
    r"|[e]quipements?\s+[e]lectroniques?"
    r"|maintenance\s+des\s+[e]quipements?\s+[e]lectroniques?"
    r"|licences?\s+de\s+logiciels?"
    r"|renouvellement\s+de\s+licences?"
    r"|logiciels?"
    r"|cybers[e]curit[e]"
    r"|informatique"
    r"|\bfournitures\s+informatiques?\b"
    r"|\bconducteur\s+electr\w*\b|\belectrical?\s+conductor\b"
    r"|\bpoteau\s+(?:electr\w*|bois|beton|beton\s+arme)\b|\belectric(?:al)?\s+pole\b"
    r"|\bdistribution\s+publique\s+(?:BT|MT)\b|\bpublic\s+(?:low|medium).?voltage\s+distribution\b"
    r"|\bderivation\s+(?:electr\w*|BT|MT)\b"
    r"|\bboucle\s+(?:electr\w*|HTA|HTB)\b"
    r"|\binterconnexion\s+electr\w*\b|\belectrical?\s+interconnection\b"
    r"|\bpost.eclairage\b|\bmat\s+d.eclairage\b|\blighting\s+pole\b|\blighting\s+column\b"
    r"|\blampadaire\w*\b"
    r"|\bLED\s+(?:lighting|eclairage)\b"
    r"|\bregulateur\s+de\s+tension\b|\bvoltage\s+regulator\b"
    r"|\bdelestage\b|\bload\s+shedding\b"
    r"|\bfacteur\s+de\s+puissance\b|\bpower\s+factor\b"
    r"|\bmise\s+en\s+service\s+electr\w*\b|\belectrical?\s+commissioning\b"
    r"|\bexploitation\s+(?:du\s+)?reseau\s+electr\w*\b|\bgrid\s+operation\b"
    r"|\bwater\s+dispensers?\b|\biron\s+box(?:es)?\b|\bmicrowaves?\b"
    r"|\bfridges?\b|\brefrigerators?\b|\bwater\s+kettles?\b"
    r"|\bICT\b|\bmanagement\s+information\s+system\b"
    r"|\bnetwork\s+and\s+data\s+cabling\b|\bdata\s+cabling\b"
    r"|\belectrical\s+appliances?\b"
    r"|\brecrutement\s+d.un\s+consultant\b|\brecrutement\s+de\s+personnel\b"
    r"|\bconsultant\s+individuel\b|\bappel\s+a\s+candidature\b"
    r"|\bhiring\s+of\s+(?:an?\s+)?individual\b|\bindividual\s+consultant\b"
    r"|\brequest\s+for\s+cv\b|\bvacan(?:cy|cies)\b|\bjob\s+opening\b"
    r"|\brecruitment\s+of\s+(?:a\s+)?(?:staff|officer|manager|coordinator|specialist)\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────
#  Detection des "notifications" (avis qui ne sont pas de vrais
#  appels d'offres ouverts : procurement plan, avis d'attribution,
#  expressions d'interet...). Utilise par le scraper GlobalTenders.
# ─────────────────────────────────────────────────────────────
_RE_NOTIFICATION = re.compile(
    r'\b('
    r'general\s+procurement\s+notice|gpn|'
    r'procurement\s+plan|'
    r'prior\s+information\s+notice|pin|'
    r'preliminary\s+procurement\s+notice|ppn|'
    r'expression\s+of\s+interest|eoi|rei|'
    r'award\s+notice|contract\s+award|'
    r'request\s+for\s+clarification|rfc|'
    r'prequalification|pre-qualification'
    r')\b',
    re.IGNORECASE
)

_RE_AO_OUVERT = re.compile(
    r"(?:APPEL\s+D.OFFRES?\s+(?:OUVERT|RESTREINT|ACCELERE|NATIONAL|INTERNATIONAL)"
    r"|(?:AVIS\s+(?:DE\s+)?)?DEMANDE\s+DE\s+PRIX"
    r"|AVIS\s+D.APPEL\s+D.OFFRES?"
    r"|DAO\s*N[o]\s*\d"
    r"|AON\s*N[o]\s*\d"
    r"|AOI\s*N[o]\s*\d"
    r"|DEMANDE\s+DE\s+PROPOSITIONS?\s+(?:ALLEGEE\s+)?N[o]\s*\d"
    r"|AVIS\s+D.APPEL\s+A\s+CANDIDATURE)",
    re.IGNORECASE,
)

_RE_ENCORE_RESULTATS = re.compile(
    r"ATTRIBUTAIRE|SYNTHESE\s+DES\s+RESULTATS"
    r"|PROCES.VERBAL|Date\s+de\s+d[e]pouillement"
    r"|Montant\s+lu\s+en\s+FCFA|Soumissionnaires"
    r"|Date\s+de\s+d[e]lib[e]ration|Nombre\s+d.offres\s+re[c]ues",
    re.IGNORECASE,
)

_RE_INDICATEURS_AO = re.compile(
    r"\bAPPEL\s+D[.''\s]?OFFRES?\b"
    r"|\bAVIS\s+D[.''\s]?APPEL\b"
    r"|\b(?:DAO|AON|AOI|AO)\s*[Nn][o]?\s*\d"
    r"|\bDAO\b|\bAON\b|\bAOI\b",
    re.IGNORECASE,
)

_RE_TYPE_MARCHE = re.compile(
    r"\bFournitures?\b"
    r"|\bServices?\s+(?:courants?|de\s+consultants?)?\b"
    r"|\bTravaux\b"
    r"|\bPrestations?\b"
    r"|\brecrutement\b"
    r"|\bacquisition\b"
    r"|\brenouvellement\b"
    r"|\bprestataire\b"
    r"|\bLogiciels?\b",
    re.IGNORECASE,
)

_RE_NUMERO_AO = re.compile(
    r"N[o]\.?\s*\d{4}[\-/]\d{2,}"
    r"|/DAO/|/AON/|/AOI/"
    r"|N[o]\.?\s*\d{4}-\d{3,}",
    re.IGNORECASE,
)

_RE_ORGANISME_PUBLIC = re.compile(
    r"\bAUTORITE\b|\bMINISTERE?\b|\bDIRECTION\b"
    r"|\bAGENCE\b|\bARCEP\b|\bOFFICE\b|\bSOCIETE\s+D[E]TAT\b"
    r"|\bFONDS\b|\bINSTITUT\b|\bBUREAU\b",
    re.IGNORECASE,
)

_RE_FINANCEMENT = re.compile(
    r"\bfinancement\b|\bfonds\s+propres\b|\bbudget\b"
    r"|\bbanque\s+mondiale\b|\b[E]tat\b|\bIDA\b|\bBM\b|\bFAD\b",
    re.IGNORECASE,
)

_RE_RESULTATS_REJETES = re.compile(
    r"\br[e]sultats?\b|\battribution\b|\badjudication\b"
    r"|\btitulaire\b|\bmarche\s+attribu[e]\b|\bnotification\b"
    r"|\bConforme\s*:\s*\d"
    r"|\bNon\s+conforme\s*:"
    r"|\boffre\s+anormalement\b"
    r"|\bCFA\s+HTVA\s+et\s+\w"
    r"|\bfrancsCFA\s+HTVA\b"
    r"|\bnombre\s+de\s+plis\s+re[c]us\b"
    r"|\bplis?\s+re[c]us\b"
    r"|\bseuil\s+de\s+tol[e]rance\b"
    r"|\bintervalle\s*:\s*de\b"
    r"|\bmoyenne\s+\d"
    r"|\bmontant\s+lu\b"
    r"|\bd[e]pouillement\b"
    r"|\bsoumissionnaires?\b"
    r"|\bbudget\s*:\s*\d[\d\s]*"
    r"|\blot\s+0?\d\s*:\s*\d{2,}\s+plis\b",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────
#  _RE_SIGNAL_ELECTRIQUE enrichi avec termes anglais
#  (les avis World Bank sont majoritairement rediges en anglais).
# ─────────────────────────────────────────────────────────────
_RE_SIGNAL_ELECTRIQUE = re.compile(
    r"electr"
    r"|photovolta"
    r"|\bsolaire\b|\bsolar\b"
    r"|\btransformateur\b|\btransformer\b"
    r"|\bHTA\b|\bHTB\b|\b[BM]T\b|\bTHT\b|\bHTA/BT\b"
    r"|\benergie\b|\benergy\b"
    r"|reseau\s+electr|\bpower\s+grid\b|\belectrical?\s+grid\b"
    r"|\bgrid\s+(?:extension|connection|network)\b"
    r"|groupe\s+electrog|\bgenerator\s+set\b|\bgenset\b"
    r"|\bonduleur\b|\binverter\b"
    r"|panneau\s+solaire|\bsolar\s+panel\b"
    r"|batterie\s+solaire|\bsolar\s+batter"
    r"|\braccordement\b|\bbranchement\b|\bconnection\s+(?:works|fee)\b"
    r"|poste\s+de\s+transform|\bsubstation\b"
    r"|centrale\s+electr|\bpower\s+(?:plant|station)\b"
    r"|mini.reseau|\bmini.?grid\b"
    r"|\bcompteur\b|\b(?:smart\s+)?meter(?:ing)?\b"
    r"|\beclairage\b|\b(?:street\s+|public\s+)?lighting\b"
    r"|\bcablage\b|\bcabling\b|\belectrical?\s+wiring\b"
    r"|\bgenerateur\b|\bgenerator\b"
    r"|electrification"
    r"|\brenouvelable\b|\brenewable\s+energy\b"
    r"|ligne\s+(?:electrique|HTA|HTB|BT|MT)|\b(?:transmission|distribution)\s+line\b"
    r"|travaux\s+(?:d.electrification|de\s+reseau\s+electr|de\s+ligne\s+(?:electr|HTA|HTB|BT|MT))"
    r"|travaux\s+de\s+pose\s+de\s+(?:cable|ligne)s?\s+(?:electr|HTA|HTB|BT|MT)"
    r"|infrastructure\s+electr|\belectrical?\s+infrastructure\b"
    r"|equipement\s+electr|\belectrical?\s+equipment\b"
    r"|\bSonabel\b|\bSONABEL\b"
    r"|\bSIER\b|\bANER\b|\bAREC\b"
    r"|\bcourant\s+(?:monobloc|alternatif|continu)\b|\b(?:AC|DC)\s+power\b"
    r"|\bposte\s+(?:HTA|HTB|MT|BT|de\s+transform)\b"
    r"|\b\d+\s*kV\b|\b\d+\s*MW\b|\b\d+\s*kW\b|\b\d+\s*kWh\b|\b\d+\s*MWh\b"
    r"|\boff.?grid\b|\bon.?grid\b"
    r"|\brural\s+electrification\b"
    r"|\bhydropower\b|\bhydroelectric\b"
    r"|\bwind\s+(?:farm|turbine|power)\b|\beolien\w*\b"
    r"|\bbiomass\s+(?:power|energy)\b"
    r"|\butility\s+pole\b|\belectric(?:al)?\s+pole\b"
    r"|\bdisjoncteur\w*\b|\bcircuit\s+breaker\b"
    r"|\barmoire\s+electr\w*\b|\belectrical?\s+cabinet\b"
    r"|\bcoffret\s+electr\w*\b"
    r"|\btableau\s+(?:electr\w*|de\s+distribution|de\s+comptage)\b|\bdistribution\s+board\b|\bswitchboard\b"
    r"|\bmise\s+a\s+la\s+terre\b|\bearthing\b|\bgrounding\b"
    r"|\bparafoudre\w*\b|\blightning\s+arrest\w*\b"
    r"|\bisolateur\w*\b|\belectrical?\s+insulator\b"
    r"|\bpylone\w*\s+electr\w*\b|\belectric(?:al)?\s+pylon\b"
    r"|\bcable\s+(?:HTA|HTB|BT|MT|electr\w*|souterrain|aerien)\b|\bunderground\s+(?:power\s+)?cable\b|\boverhead\s+(?:power\s+)?line\b"
    r"|\bvariateur\s+(?:de\s+vitesse|electr\w*)\b|\bvariable\s+frequency\s+drive\b|\bVFD\b"
    r"|\bstation\s+de\s+recharge\s+electr\w*\b|\belectric\s+charging\s+station\b|\bborne\s+de\s+recharge\b"
    r"|\bbatterie\s+de\s+stockage\s+(?:electr\w*|d.energie)\b|\bbattery\s+storage\b|\bBESS\b"
    r"|\bSTEG\b"
    r"|\bAMADER\b|\bEDM\b|\bSENELEC\b|\bENEO\b",
    re.IGNORECASE,
)

# [TUNEPS] Signal electrique specifique arabe
_RE_SIGNAL_ELECTRIQUE_AR_TUNEPS = re.compile(
    r"كهرباء|كهربائي|كهربائية|كهروضوئية|كهروبائية"
    r"|إنارة|الإنارة|تنوير|التنوير"
    r"|محول|محولات"
    r"|الجهد\s+المنخفض|الجهد\s+المتوسط"
    r"|الطاقة\s+الشمسية"
    r"|شبكة\s+كهرباء|الشبكة\s+الكهربائية"
    r"|عمود\s+كهربائي|أعمدة\s+كهربائية"
    r"|مولد|مولدات"
    r"|تركيب\s+كهربائي"
    r"|عداد\s+كهرباء|عدادات\s+كهرباء"
    r"|خط\s+كهربائي|خطوط\s+كهربائية"
    r"|كابل|كابلات" 
    r"|قاطع|قواطع"
)
