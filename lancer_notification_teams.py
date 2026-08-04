from dotenv import load_dotenv
load_dotenv()

import json
from notifications import notifier_teams

try:
    with open("nouveaux_ao_dernier_run.json", "r", encoding="utf-8") as f:
        nouveaux = json.load(f)
except FileNotFoundError:
    nouveaux = []

notifier_teams(nouveaux)