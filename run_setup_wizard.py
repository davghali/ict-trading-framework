"""
INTERACTIVE SETUP WIZARD — guide final pour l'user.

CLI step-by-step qui :
1. Check l'état actuel (services, credentials, data)
2. Propose les actions pour chaque composant non configuré
3. Guide pour MT5 multi-compte
4. Teste Telegram/Discord/Email alerts
5. Lance un scan test
6. Propose VPS deployment
7. Affiche le dashboard final

Usage :  python3 run_setup_wizard.py
"""
from __future__ import annotations

import sys
import os
import json
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent


def banner(txt: str, ch: str = "═") -> None:
    print("\n" + ch * 72)
    print(f"  {txt}")
    print(ch * 72)


def ask(prompt: str, default: str = "y") -> str:
    ans = input(f"  {prompt} [{default}] : ").strip().lower()
    return ans or default


def check_icon(b: bool) -> str:
    return "✅" if b else "❌"


# ══════════════════════════════════════════════════════════════════════
def check_current_state():
    """Retourne un dict de l'état actuel."""
    state = {}

    # Credentials
    env = ROOT / "user_data" / ".env"
    if env.exists():
        content = env.read_text()
        state["telegram"] = "TELEGRAM_BOT_TOKEN=" in content and \
                            not "TELEGRAM_BOT_TOKEN=\n" in content
        state["discord"] = "DISCORD_WEBHOOK_URL=" in content and \
                           not "DISCORD_WEBHOOK_URL=\n" in content
        state["anthropic"] = "ANTHROPIC_API_KEY=" in content and \
                             not "ANTHROPIC_API_KEY=\n" in content
    else:
        state.update({"telegram": False, "discord": False, "anthropic": False})

    # MT5 multi-accounts
    state["mt5_multi"] = (ROOT / "user_data" / "mt5_accounts.json").exists()

    # Services
    try:
        res = subprocess.run(["launchctl", "list"], capture_output=True,
                              text=True, timeout=5)
        state["cyborg_daemon"] = "com.ictframework.cyborg" in res.stdout
        state["supervisor_daemon"] = "com.ictframework.supervisor" in res.stdout
    except Exception:
        state["cyborg_daemon"] = False
        state["supervisor_daemon"] = False

    # Data
    data_files = list((ROOT / "data" / "raw").glob("*.parquet"))
    state["data_loaded"] = len(data_files) >= 12

    # Settings
    state["settings"] = (ROOT / "user_data" / "settings.json").exists()

    return state


# ══════════════════════════════════════════════════════════════════════
def print_status(state: dict):
    banner("🔍 ÉTAT ACTUEL DU SYSTÈME")
    print(f"\n  {check_icon(state['settings'])}  User settings (account, risk)")
    print(f"  {check_icon(state['data_loaded'])}  Data (12 assets)")
    print(f"  {check_icon(state['telegram'])}  Telegram bot token")
    print(f"  {check_icon(state['discord'])}  Discord webhook (optionnel)")
    print(f"  {check_icon(state['anthropic'])}  Claude AI auditor (optionnel)")
    print(f"  {check_icon(state['mt5_multi'])}  MT5 multi-account config")
    print(f"  {check_icon(state['cyborg_daemon'])}  Cyborg daemon running 24/7")
    print(f"  {check_icon(state['supervisor_daemon'])}  Supervisor daemon running")

    ready_core = all([state["settings"], state["data_loaded"],
                       state["telegram"], state["cyborg_daemon"]])
    ready_full = ready_core and state["mt5_multi"]

    print()
    if ready_full:
        print("  🏆 Système FULL ULTIMATE ACTIF — multi-account MT5 prêt")
    elif ready_core:
        print("  ✅ Système CORE actif — MT5 multi-account optionnel non configuré")
    else:
        print("  ⚠️  Configuration incomplète — suis le wizard ci-dessous")


# ══════════════════════════════════════════════════════════════════════
def configure_mt5_multi():
    banner("🏦 CONFIGURATION MT5 MULTI-COMPTES")
    print("""
  Le MT5 multi-account te permet de trader sur plusieurs
  comptes prop firms en parallèle (FTMO × N, The 5ers × M).

  Pour chaque compte, il te faut (depuis le dashboard FTMO/5ers) :
  • Login : numéro de compte MT5 (ex: 1234567)
  • Password : investor password ou master password
  • Server : nom du serveur (ex: FTMO-Demo, FTMO-Server)
    """)

    template = ROOT / "user_data" / "mt5_accounts.json.example"
    target = ROOT / "user_data" / "mt5_accounts.json"

    if target.exists():
        print(f"  ℹ️  Fichier existant : {target}")
        if ask("Écraser avec template vierge ?", "n") != "y":
            return
    if not template.exists():
        print("  ❌ Template manquant")
        return

    import shutil
    shutil.copy(template, target)
    print(f"  ✓ Template copié : {target}")
    print()
    print(f"  👉 Édite MAINTENANT ce fichier :")
    print(f"     nano {target}")
    print(f"     (remplace login=0 par tes vrais numéros)")
    print()
    if ask("Ouvrir dans ton éditeur par défaut ?"):
        subprocess.run(["open", str(target)])


# ══════════════════════════════════════════════════════════════════════
def test_telegram():
    banner("📱 TEST TELEGRAM")
    try:
        from src.utils.user_settings import apply_env
        from src.telegram_bot import TelegramBot
        apply_env()
        bot = TelegramBot()
        if not bot.enabled:
            print("  ❌ Telegram non configuré dans user_data/.env")
            return
        r = bot.test_connection()
        if r:
            print("  ✅ Message test envoyé sur Telegram — vérifie ton phone")
        else:
            print("  ❌ Échec envoi — vérifie le token")
    except Exception as e:
        print(f"  ❌ Erreur : {e}")


# ══════════════════════════════════════════════════════════════════════
def deploy_vps_guide():
    banner("🌩 DEPLOY VPS ORACLE CLOUD FREE (24/7 sans Mac)")
    print("""
  Déploie ton cyborg sur Oracle Cloud Free (gratuit à vie).

  Étapes :
  1. Ouvrir Oracle Cloud Free signup
  2. Créer une VM ARM64 (toujours gratuit)
  3. SSH → clone repo → bash setup_vps.sh
  4. Copier credentials → restart services

  Doc détaillée : deployment/vps/ORACLE_CLOUD_GUIDE.md
    """)
    if ask("Ouvrir Oracle Cloud signup dans le browser ?"):
        webbrowser.open("https://signup.oracle.com/cloud-free")
        print("  ✓ Navigateur ouvert")
    print()
    print(f"  📖 Guide complet : {ROOT / 'deployment' / 'vps' / 'ORACLE_CLOUD_GUIDE.md'}")


# ══════════════════════════════════════════════════════════════════════
def start_all_services():
    banner("🚀 DÉMARRAGE DE TOUS LES SERVICES")
    scripts = [
        ROOT / "scripts" / "install_cyborg.sh",
        ROOT / "scripts" / "install_supervisor.sh",
    ]
    for s in scripts:
        if s.exists():
            print(f"  → {s.name}")
            subprocess.run(["bash", str(s)], check=False)

    print()
    subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    print("  ✅ Services lancés. Vérifie Telegram pour le message de bienvenue.")


# ══════════════════════════════════════════════════════════════════════
def main():
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║  🔴 ICT CYBORG — SETUP WIZARD INTERACTIF                         ║
║  Pour finaliser les derniers 5% de ton système ultime            ║
╚═══════════════════════════════════════════════════════════════════╝
    """)

    state = check_current_state()
    print_status(state)

    # Menu
    while True:
        banner("📋 MENU")
        print("""
  1. Tester Telegram (envoie message de test)
  2. Configurer MT5 multi-comptes
  3. Démarrer tous les services (cyborg + supervisor)
  4. Guide deploy VPS Oracle Cloud
  5. Run ultimate audit (tests complets)
  6. Lancer le dashboard web local
  7. Refresh état
  0. Quitter
        """)
        choice = input("  Choix : ").strip()

        if choice == "1":
            test_telegram()
        elif choice == "2":
            configure_mt5_multi()
        elif choice == "3":
            start_all_services()
        elif choice == "4":
            deploy_vps_guide()
        elif choice == "5":
            subprocess.run([sys.executable, str(ROOT / "run_ultimate_audit.py")])
        elif choice == "6":
            subprocess.run([
                sys.executable, "-m", "streamlit", "run",
                str(ROOT / "dashboard.py"),
                "--browser.gatherUsageStats=false",
            ])
        elif choice == "7":
            state = check_current_state()
            print_status(state)
        elif choice == "0":
            print("\n  👋 À bientôt — le cyborg continue de tourner.\n")
            break
        else:
            print("  ❌ Choix invalide")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  👋 Wizard interrompu.\n")
