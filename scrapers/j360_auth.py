"""
Gestion de la connexion au compte premium J360.
Separe de j360.py pour garder le scraper original intact.

URL de login confirmee : https://app.j360.info/login/?next=/
(sous-domaine app.j360.info, distinct de www.j360.info utilise pour
les resultats publics -- cf. capture d'ecran du formulaire).
Selecteurs bases sur les placeholders reels vus dans la capture :
"Adresse e-mail", "Mot de passe", bouton "Se connecter".
"""
from config import log

_URL_LOGIN = "https://app.j360.info/login/?next=/"


def se_connecter(page, email, mot_de_passe, attendre_challenge_anubis):
    """Connecte le compte premium J360 avant le scraping.

    attendre_challenge_anubis : fonction importee de j360.py, passee en
    parametre pour eviter tout import circulaire et ne jamais modifier
    j360.py."""
    if not email or not mot_de_passe:
        print(">>> Pas d'identifiants J360 -> scraping en mode anonyme")
        log.info("J360 - pas d'identifiants, mode anonyme")
        return False

    print(f">>> Connexion au compte J360 ({email})...")
    try:
        page.goto(_URL_LOGIN, wait_until="domcontentloaded")

        if not attendre_challenge_anubis(page):
            print(">>> BLOQUE par Anubis sur la page de login")
            log.warning("J360 - bloque par Anubis sur la page de login")
            return False

        # Selecteurs bases sur les placeholders reels du formulaire
        champ_email = page.get_by_placeholder("Adresse e-mail")
        champ_password = page.get_by_placeholder("Mot de passe")

        champ_email.fill(email)
        champ_password.fill(mot_de_passe)

        # La case "Rester connecté" est deja cochee par defaut sur le
        # site (visible dans la capture) -- pas besoin d'y toucher.

        bouton_submit = page.get_by_role("button", name="Se connecter")
        bouton_submit.click()

        page.wait_for_load_state("networkidle", timeout=20000)

        # Verification de connexion reussie : on n'est plus sur la page
        # de login, et le champ email/mot de passe a disparu. Plus fiable
        # que de chercher un texte precis du menu utilisateur (qui n'est
        # visible qu'apres avoir ouvert le menu deroulant, cf. capture
        # d'ecran -- juste "Ste Amine Ste Amine" + fleche, sans texte
        # "Deconnexion"/"Mon compte" dans le DOM avant clic).
        url_hors_login = "/login" not in page.url
        champ_email_disparu = page.get_by_placeholder("Adresse e-mail").count() == 0
        connecte = url_hors_login and champ_email_disparu
        if connecte:
            print(">>> Connexion J360 reussie")
            log.info("J360 - connexion reussie")
        else:
            print(">>> Connexion J360 : statut incertain -- verifier manuellement apres login")
            log.warning("J360 - connexion : impossible de confirmer le succes")

        return connecte

    except Exception as e:
        print(f">>> ERREUR lors de la connexion J360 : {e}")
        log.error(f"J360 - erreur connexion : {e}")
        return False