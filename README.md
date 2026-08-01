# 🔍 Veille Automatique — Appels d'Offres Électricité & Travaux

> Système de veille intelligente multi-sources pour la collecte, le filtrage et la notification automatique des appels d'offres dans le domaine de l'électricité et des travaux publics en Afrique et en Tunisie.

---

## 📌 Présentation

Ce projet automatise entièrement la veille des appels d'offres (AO) pour une entreprise spécialisée dans les travaux électriques active en Tunisie et en Afrique francophone.

Il collecte quotidiennement les AO publiés sur **12 sources internationales**, applique un **filtrage intelligent par NLP**, élimine les doublons inter-sources, exporte les résultats dans un **fichier Excel structuré** et envoie des **notifications automatiques** par email et Microsoft Teams.

---

## ✨ Fonctionnalités

- ✅ Scraping automatisé de 12 sources (sites publics, portails internationaux, plateformes authentifiées)
- ✅ Filtrage sémantique par embeddings NLP (sentence-transformers)
- ✅ Déduplication intra et inter-sources
- ✅ Export Excel cumulatif avec 2 onglets (Afrique / Tunisie), statuts colorés, liens cliquables
- ✅ Archivage automatique des AO masqués
- ✅ Notifications email HTML + pièce jointe Excel
- ✅ Notifications Microsoft Teams (adaptive card)
- ✅ Planificateur intégré (exécution automatique chaque jour de semaine)
- ✅ Mode test pour valider sans impacter l'historique

---

## 🌍 Sources couvertes

| Source | Zone | Méthode |
|---|---|---|
| SBEE | Bénin | Requests + BeautifulSoup |
| AfDB / BAD | Afrique | Requests + BeautifulSoup |
| DGCMEF | Burkina Faso | Requests + BeautifulSoup |
| World Bank | International | Requests + API |
| OPEC Fund | International | Requests + BeautifulSoup |
| IsDB | International | Requests + BeautifulSoup |
| AFD DGMarket | Afrique francophone | Requests + BeautifulSoup |
| DevelopmentAid | International | Requests + BeautifulSoup |
| GlobalTenders | International | Playwright (session authentifiée + PDF) |
| TuniSurf | Tunisie | Playwright (login requis) |
| TUNEPS | Tunisie | Playwright (login requis) |
| J360 | Multi-pays | Playwright (login requis) |

---

## 🏗️ Architecture du projet

```
veille_ao/
├── main.py                  # Point d'entrée — orchestre tout le pipeline
├── config.py                # Configuration, constantes, expressions régulières
├── utils.py                 # Fonctions utilitaires (dates, normalisation)
├── filtrage.py              # Filtrage NLP par embeddings (sentence-transformers)
├── historique.py            # Gestion de l'historique et déduplication
├── export_excel.py          # Export Excel cumulatif (openpyxl)
├── notifications.py         # Email HTML + notification Teams
├── requirements.txt         # Dépendances Python
├── .env                     # Identifiants et mots de passe
├── resultats_veille.json    # Historique des AO déjà vus
├── veille_ao.log            # Logs d'exécution
└── scrapers/
    ├── sbee.py
    ├── afdb.py
    ├── dgcmef.py
    ├── worldbank.py
    ├── tunisurf.py
    ├── tuneps.py
    ├── opecfund.py
    ├── isdb.py
    ├── afd_dgmarket.py
    ├── developmentaid.py
    ├── globaltenders.py
    └── j360_multipays.py
```

---

## ⚙️ Installation

### Prérequis
- Python 3.10+
- Connexion internet

### 1. Cloner le projet
```bash
git clone https://github.com/ton-username/veille-ao.git
cd veille-ao
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Installer le navigateur Playwright
```bash
playwright install chromium
```

### 4. Configurer le fichier `.env`
Créer un fichier `.env` à la racine du projet :
```env
EMAIL_FROM=votre_email@gmail.com
EMAIL_PASSWORD=votre_mot_de_passe_app
EMAIL_TO=destinataire@gmail.com

TUNISURF_EMAIL=email@entreprise.tn
TUNISURF_PASSWORD=mot_de_passe

GLOBALTENDERS_EMAIL=email@gmail.com
GLOBALTENDERS_PASSWORD=mot_de_passe

J360_EMAIL=email@gmail.com
J360_PASSWORD=mot_de_passe
```

> **Note** : Pour Gmail, utiliser un [mot de passe d'application](https://myaccount.google.com/apppasswords) et non le mot de passe principal.

---

## 🚀 Utilisation

### Exécution immédiate (une fois)
```bash
python main.py
```

### Mode test (ignore l'historique, affiche tous les AO)
```bash
python main.py --test
```

### Mode planifié (exécution automatique chaque jour de semaine à 18h)
```bash
python main.py --planifier
```

### Planificateur Windows (recommandé)
Configurer dans le **Planificateur de tâches Windows** :

| Champ | Valeur |
|---|---|
| Programme | `python` |
| Arguments | `main.py` |
| Dossier de démarrage | `C:\chemin\vers\veille_ao` |

---

## 📊 Résultat — Fichier Excel

Le fichier `veille_ao_resultats.xlsx` est mis à jour à chaque exécution avec :

- **Onglet Afrique** — AO organisés par pays avec bandeau et drapeau
- **Onglet Tunisie** — AO tunisiens avec colonnes Caution et Maître d'Ouvrage
- **Onglet Archives** — AO masqués, jamais réinsérés
- **Onglet Légende** — Explication des couleurs et statuts

Chaque ligne contient :
- Statut calculé automatiquement (🟢 Ouvert / 🟠 Urgent / 🔴 Expiré / ⚪ Inconnu)
- Jours restants avant clôture
- Lien cliquable vers l'avis original
- Colonne **Avis Direction Générale** : `Confirmé` / `En attente` / `Masquer`

---

## 🧠 Filtrage intelligent

Le filtrage des AO non pertinents utilise une approche multi-niveaux :

1. **Mots-clés métier** — liste de signaux électriques pondérés
2. **Expressions régulières** — détection de types d'AO, domaines bloqués
3. **Embeddings sémantiques** — modèle `sentence-transformers` pour similarité cosinus
4. **Déduplication MD5** — hash sur titre + lien + source pour éviter les doublons

---

## 🛠️ Stack technique

| Technologie | Usage |
|---|---|
| Python 3.10+ | Langage principal |
| Playwright | Scraping sites authentifiés (JS dynamique) |
| BeautifulSoup + lxml | Parsing HTML |
| sentence-transformers | Embeddings NLP pour filtrage sémantique |
| openpyxl | Génération et mise à jour du fichier Excel |
| schedule | Planificateur intégré |
| python-dotenv | Gestion des variables d'environnement |
| PyMuPDF | Extraction PDF (GlobalTenders) |
| smtplib | Notifications email HTML |
| requests | Requêtes HTTP |

---

## 📁 Fichiers à ne pas versionner

Ajouter dans `.gitignore` :
```
.env
resultats_veille.json
veille_ao.log
veille_ao_resultats.xlsx
pdfs_globaltenders/
__pycache__/
*.pyc
debug_*.html
debug_*.png
gt_*.html
gt_cookies.json
```

---

## 📄 Licence

Projet interne — usage professionnel chez Enertechgroup.