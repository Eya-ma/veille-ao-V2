"""
Notifications : envoi email (SSL/465 puis fallback STARTTLS/587) et
notification Teams via webhook Power Automate (adaptive card + pièce jointe).
Issu du decoupage de veille_ao_1_1.py (v10.18).
"""
import os
import time
import base64
import smtplib
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import requests

from config import CONFIG, log

def _envoyer_un_email(email_from, email_password, email_to, nouveaux, mode_test=False):
    """Envoie l'email pour UNE paire expediteur/destinataire donnee."""
    cfg = CONFIG
    log.info(f"[EMAIL] Preparation envoi depuis {email_from} vers {email_to} : {len(nouveaux)} AO a notifier | mode_test={mode_test}")
    if not all([email_from, email_password, email_to]):
        log.info(f"[EMAIL] Configuration incomplete pour {email_from or '(vide)'} -> {email_to or '(vide)'} - envoi ignore")
        return
    date_str = datetime.now().strftime("%d/%m/%Y")
    heure_str = datetime.now().strftime("%H:%M")
    tag_test = " [TEST]" if mode_test else ""
    if len(nouveaux) == 0:
        libelle_ao = "aucun appel d'offres détecté"
    elif len(nouveaux) == 1:
        libelle_ao = "1 appel d'offres détecté"
    else:
        libelle_ao = f"{len(nouveaux)} appels d'offres détectés"
    sujet = f"[Enertech] Veille AO — {date_str} {heure_str}{tag_test} : {libelle_ao}"
    log.info(f"[EMAIL] Sujet : {sujet}")
    corps = f"""<html><body style="font-family:Arial,sans-serif;max-width:860px;margin:auto;color:#222;">
  <h2 style="background:#1F4E79;color:white;padding:14px 18px;border-radius:6px;">
    Veille Appels d\'Offres{tag_test} - {datetime.now().strftime('%d/%m/%Y a %H:%M')}
  </h2>"""
    if nouveaux:
        corps += (
            f'<p><b>{len(nouveaux)} appel(s) d\'offres detecte(s)</b> '
            f'aujourd\'hui.</p>'
            f'<p>Le detail complet (tous les AO actifs, avec liens) '
            f'se trouve dans le fichier Excel joint a cet email.</p>'
        )
    else:
        corps += '<div style="background:#f5f5f5;padding:20px;text-align:center;"><p>Aucun appel d\'offres detecte aujourd\'hui.</p></div>'
    corps += (
        '<hr style="border:none;border-top:1px solid #ddd;margin:24px 0;">'
        '<p style="font-size:12px;color:#777;">'
        'Cette veille est automatisee : merci de verifier manuellement la validite '
        'des AO ci-joints, ainsi que l\'existence d\'eventuels appels d\'offres non '
        'detectes par le systeme sur les sources suivies.'
        '</p>'
    )
    corps += "</body></html>"
    msg            = MIMEMultipart("mixed")
    msg["Subject"] = sujet
    msg["From"]    = f'VEILLE COMMERCIALE <{email_from}>'
    msg["To"]      = email_to
    msg_alt        = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(corps, "html", "utf-8"))
    msg.attach(msg_alt)
    excel_path = cfg["excel_file"]
    if os.path.exists(excel_path):
        with open(excel_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(excel_path)}")
        msg.attach(part)
        log.info(f"[EMAIL] Piece jointe Excel attachee : {excel_path}")
    else:
        log.warning(f"[EMAIL] Fichier Excel {excel_path} introuvable -> envoi sans piece jointe")

    try:
        t0 = time.time()
        with smtplib.SMTP_SSL(cfg["smtp_server"], cfg.get("smtp_port_ssl", 465), timeout=30) as server:
            server.login(email_from, email_password)
            server.sendmail(email_from, [email_to], msg.as_string())
        log.info(f"[EMAIL] Envoye avec succes (SSL/465) {email_from} -> {email_to} en {time.time() - t0:.2f}s")
        return
    except Exception as e_ssl:
        log.warning(f"[EMAIL] Echec SMTP_SSL (465) pour {email_from} : {e_ssl} -> tentative STARTTLS (587)")

    try:
        t0 = time.time()
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_from, email_password)
            server.sendmail(email_from, [email_to], msg.as_string())
        log.info(f"[EMAIL] Envoye avec succes (STARTTLS/587) {email_from} -> {email_to} en {time.time() - t0:.2f}s")
    except Exception as e:
        print(traceback.format_exc())
        log.error(f"[EMAIL] Erreur envoi email {email_from} -> {email_to} (les deux methodes ont echoue) : {e}")


def envoyer_email(nouveaux, mode_test=False):
    """
    Envoie l'email via 2 paires expediteur/destinataire independantes :
      - Paire 1 : email_from / email_to
      - Paire 2 : email_from_2 / email_to_2
    Chaque paire est envoyee independamment ; si l'une echoue, l'autre
    est quand meme tentee.
    """
    cfg = CONFIG

    _envoyer_un_email(
        cfg.get("email_from", ""),
        cfg.get("email_password", ""),
        cfg.get("email_to", ""),
        nouveaux, mode_test,
    )

    #_envoyer_un_email(
     #   cfg.get("email_from_2", ""),
      #  cfg.get("email_password_2", ""),
      #  cfg.get("email_to_2", ""),
      #  nouveaux, mode_test,
    #)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def notifier_teams(nouveaux, mode_test=False):
    """Envoie un resume + le fichier Excel vers Teams via webhook Power Automate."""
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        log.info("[TEAMS] TEAMS_WEBHOOK_URL non configure -> notification ignoree")
        return

    tag_test = " [TEST]" if mode_test else ""
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not nouveaux:
        resume = "Aucun nouvel appel d'offres detecte aujourd'hui."
    else:
        resume = "Consultez le detail complet dans le fichier Excel."

    excel_path = CONFIG["excel_file"]
    file_content_b64 = ""
    file_name = os.path.basename(excel_path)
    if os.path.exists(excel_path):
        try:
            with open(excel_path, "rb") as f:
                file_content_b64 = base64.b64encode(f.read()).decode("utf-8")
            log.info(f"[TEAMS] Fichier Excel encode en base64 ({len(file_content_b64)} caracteres)")
        except Exception as e:
            log.error(f"[TEAMS] Erreur lecture/encodage Excel : {e}")
    else:
        log.warning(f"[TEAMS] Fichier Excel {excel_path} introuvable -> envoi sans fichier")

    payload = {
        "type": "message",
        "titre": f"Veille AO{tag_test} - {date_str}",
        "nombre": len(nouveaux),
        "resume": resume,
        "fileName": file_name,
        "fileContent": file_content_b64,
        "nouveauxAO": [
        {
            "dateAjout": ao.get("date_ajout", ""),
            "source": ao.get("source", ""),
            "pays": ao.get("pays", ""),
            "titre": ao.get("titre", ""),
            "datePub": ao.get("date_pub", ""),
            "dateLimite": ao.get("date_limite", ""),
            "lien": ao.get("url_avis", ""),
            "lienDossier": ao.get("url_dossier", ""),
            "caution": ao.get("caution", ""),
            "acheteur": ao.get("acheteur_public", ""),
        }
        for ao in nouveaux
    ],
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"🔔 Veille AO{tag_test} - {date_str}",
                            "weight": "Bolder",
                            "size": "Medium",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": f"**{len(nouveaux)} appel(s) d'offres detecte(s)**",
                            "wrap": True
                        },
                        {
                            "type": "TextBlock",
                            "text": resume,
                            "wrap": True
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Ouvrir le fichier Excel (SharePoint)",
                            "url": "https://steamine.sharepoint.com/:x:/r/sites/Commercial/_layouts/15/Doc.aspx?sourcedoc=%7B302D1A7B-68EB-4B24-AAD3-0E46D28999A2%7D&file=veille_ao_resultats.xlsx&action=default&mobileredirect=true"
                        }
                    ]
                }
            }
        ]
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=60)
        if 200 <= r.status_code < 300:
            log.info(f"[TEAMS] Notification envoyee avec succes (HTTP {r.status_code})")
        else:
            log.warning(f"[TEAMS] Reponse HTTP inattendue : {r.status_code} | corps : {r.text[:300]}")
    except Exception as e:
        log.error(f"[TEAMS] Erreur envoi notification Teams : {e}")
        log.error(traceback.format_exc())
