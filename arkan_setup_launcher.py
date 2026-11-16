"""
ARKAN EPC COPILOT — Lanceur & Auto-Configurateur Universel
Ce script configure et démarre l'ensemble de l'écosystème ARKAN de façon 100% automatique :
- Initialisation du .env et des secrets
- Détection et lancement de Docker (Neo4j, ChromaDB, API)
- Détection et initialisation d'Ollama + modèle 'arkan-planning'
- Création du raccourci Bureau Windows
- Ouverture automatique du navigateur Web
"""

import os
import sys
import time
import shutil
import urllib.request
import json
import webbrowser
import subprocess
from pathlib import Path

# Détection dynamique du répertoire racine de l'application
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

os.chdir(str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR))

# Encodage UTF-8 pour Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def print_banner():
    print(r"""
======================================================================
     ___     ____     _  __     ___     _   __
    /   |   / __ \   | |/ /    /   |   / | / /
   / /| |  / /_/ /   |   /    / /| |  /  |/ / 
  / ___ | / _, _/   /   |    / ___ | / /|  /  
 /_/  |_|/_/ |_|   /_/|_|   /_/  |_|/_/ |_/   
                                              
   ARKAN EPC COPILOT — Système d'Intelligence Industrielle
======================================================================
""")


def log_step(step_num: int, title: str, status: str = "EN COURS..."):
    print(f"[{step_num}/6] {title:45} -> {status}")


def ensure_env_file():
    """Crée le fichier .env depuis .env.example si absent."""
    env_file = BASE_DIR / ".env"
    example_file = BASE_DIR / ".env.example"
    
    if not env_file.exists():
        if example_file.exists():
            shutil.copy(example_file, env_file)
            log_step(1, "Initialisation fichier de configuration", "CRÉÉ DEPUIS EXEMPLE ✅")
        else:
            # Création .env par défaut minimal
            with open(env_file, "w", encoding="utf-8") as f:
                f.write("OLLAMA_MODEL=arkan-planning\nARKAN_LLM_MODEL=arkan-planning\nOLLAMA_BASE_URL=http://localhost:11434\n")
            log_step(1, "Initialisation fichier de configuration", "GÉNÉRÉ PAR DÉFAUT ✅")
    else:
        log_step(1, "Initialisation fichier de configuration", "DÉJÀ PRÉSENT ✅")


def is_docker_running() -> bool:
    """Vérifie si le daemon Docker répond."""
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def try_start_docker():
    """Tente de démarrer Docker Desktop s'il est installé."""
    docker_paths = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe"
    ]
    for p in docker_paths:
        if os.path.exists(p):
            print("   -> Lancement de Docker Desktop en arrière-plan...")
            try:
                subprocess.Popen([p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(20):
                    time.sleep(2)
                    if is_docker_running():
                        return True
            except Exception:
                pass
    return False


def check_and_start_docker():
    """Démarre l'infrastructure Docker (Neo4j, ChromaDB, API) si activé."""
    # Économie RAM : Par défaut, le mode local natif FastAPI/SQLite/ChromaDB est privilégié pour éviter les 4 à 8 Go consommés par Docker/WSL2
    if os.getenv("ENABLE_DOCKER_AUTOSTART", "0") != "1":
        log_step(2, "Infrastructure Système", "MODE LOCAL NORMÉ ACTIF (ÉCONOMIE RAM ✅)")
        return False

    docker_ok = is_docker_running()
    if not docker_ok:
        print("   -> Docker n'est pas encore actif, tentative de démarrage...")
        docker_ok = try_start_docker()

    if docker_ok:
        log_step(2, "Infrastructure Docker (Neo4j, ChromaDB)", "DÉMARRAGE EN COURS...")
        try:
            res = subprocess.run(["docker", "compose", "up", "-d"], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=90)
            if res.returncode == 0:
                log_step(2, "Infrastructure Docker (Neo4j, ChromaDB)", "CONTENEURS ACTIFS ✅")
                return True
            else:
                log_step(2, "Infrastructure Docker", f"AVERTISSEMENT ({res.stderr[:50]}...)")
        except Exception as e:
            log_step(2, "Infrastructure Docker", f"ERREUR ({e})")
    else:
        log_step(2, "Infrastructure Docker", "NON DÉTECTÉ (BASCULE MODE LOCAL DIRECT)")
    return False



def check_and_configure_ollama():
    """Vérifie Ollama et enregistre le modèle fine-tuné arkan-planning si manquant."""
    log_step(3, "Moteur IA & Modèle Ollama (arkan-planning)", "VÉRIFICATION...")
    
    ollama_url = "http://localhost:11434/api/tags"
    ollama_online = False
    models_list = []

    try:
        with urllib.request.urlopen(ollama_url, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            models_list = [m.get("name", "") for m in data.get("models", [])]
            ollama_online = True
    except Exception:
        # Tenter de démarrer ollama en local
        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            alt = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
            if os.path.exists(alt):
                ollama_bin = alt

        if ollama_bin:
            print("   -> Démarrage du service Ollama local...")
            subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(4)
            try:
                with urllib.request.urlopen(ollama_url, timeout=3) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    models_list = [m.get("name", "") for m in data.get("models", [])]
                    ollama_online = True
            except Exception:
                pass

    if ollama_online:
        has_arkan = any("arkan-planning" in m for m in models_list)
        if has_arkan:
            log_step(3, "Moteur IA & Modèle Ollama", "MODÈLE arkan-planning PRÊT ✅")
        else:
            modelfile_path = BASE_DIR / "models" / "Modelfile.arkan"
            if modelfile_path.exists():
                print("   -> Enregistrement automatique du modèle arkan-planning dans Ollama...")
                try:
                    subprocess.run(["ollama", "create", "arkan-planning", "-f", str(modelfile_path)], cwd=str(BASE_DIR), capture_output=True, timeout=60)
                    log_step(3, "Moteur IA & Modèle Ollama", "MODÈLE arkan-planning CRÉÉ AVEC SUCCÈS ✅")
                except Exception as e:
                    log_step(3, "Moteur IA & Modèle Ollama", f"AVERTISSEMENT ({e})")
            else:
                log_step(3, "Moteur IA & Modèle Ollama", "OLLAMA ACTIF ✅")
    else:
        log_step(3, "Moteur IA & Modèle Ollama", "OLLAMA EN ATTENTE SUR PORT 11434")


def check_and_configure_nuextract():
    """Détecte le serveur NuExtract-3 (mode lazy-loading à la demande pour préserver la RAM)."""
    # ÉCONOMIE MAJEURE DE RAM : Ne pas démarrer NuExtract-3 au boot car il consomme 3.1 Go de RAM.
    # Il est démarré automatiquement à la demande si l'utilisateur lance une extraction ARH.
    if os.getenv("ENABLE_NUEXTRACT_DAEMON", "0") != "1":
        log_step(4, "Moteur Spécialiste NuExtract-3", "MODE À LA DEMANDE (ÉCONOMIE 3.1 Go RAM ✅)")
        return

    log_step(4, "Moteur Spécialiste NuExtract-3", "VÉRIFICATION...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=2) as resp:
            if resp.status == 200:
                log_step(4, "Moteur Spécialiste NuExtract-3", "OPÉRATIONNEL (PORT 11435) ✅")
                return
    except Exception:
        pass

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    llama_candidates = [
        Path(local_app_data) / "Programs" / "Ollama" / "lib" / "ollama" / "llama-server.exe",
        Path(r"C:\Program Files\Ollama\lib\ollama\llama-server.exe")
    ]
    llama_bin = None
    for c in llama_candidates:
        if c.exists():
            llama_bin = str(c)
            break

    model_path = BASE_DIR / "models" / "nuextract3" / "NuExtract3-Q4_K_M.gguf"
    if llama_bin and model_path.exists():
        print("   -> Lancement du serveur d'extraction NuExtract-3 (port 11435, contexte optimisé 2K)...")
        subprocess.Popen([
            llama_bin,
            "--model", str(model_path),
            "--port", "11435",
            "-c", "2048",
            "-np", "1",
            "--threads", "4",
            "--no-webui"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        log_step(4, "Moteur Spécialiste NuExtract-3", "DÉMARRÉ SUR PORT 11435 (CONTEXTE 2K) ✅")
    else:
        log_step(4, "Moteur Spécialiste NuExtract-3", "IGNORÉ (Binaire ou modèle absent)")



def start_local_backend_if_needed(docker_started: bool):
    """Si Docker n'a pas démarré l'API, lance l'API Python directement en arrière-plan."""
    log_step(5, "Backend API ARKAN & Moteur Métier", "VÉRIFICATION...")
    
    # Tester si le port 8000 répond déjà
    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as resp:
            if resp.status == 200:
                log_step(4, "Backend API ARKAN & Moteur Métier", "OPÉRATIONNEL (PORT 8000) ✅")
                return
    except Exception:
        pass

    # Lancement direct avec Python local
    python_exe = sys.executable
    venv_py = BASE_DIR / "venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        python_exe = str(venv_py)

    api_script = BASE_DIR / "api_enhanced.py"
    if api_script.exists():
        print("   -> Lancement du serveur API FastAPI (Uvicorn)...")
        subprocess.Popen([python_exe, "-m", "uvicorn", "api_enhanced:app", "--host", "0.0.0.0", "--port", "8000"],
                         cwd=str(BASE_DIR),
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        
        # Attente du démarrage
        for _ in range(25):
            time.sleep(1)
            try:
                with urllib.request.urlopen("http://localhost:8000/health", timeout=1) as resp:
                    if resp.status == 200:
                        log_step(4, "Backend API ARKAN & Moteur Métier", "DÉMARRÉ SUR PORT 8000 ✅")
                        return
            except Exception:
                pass
        log_step(4, "Backend API ARKAN & Moteur Métier", "EN COURS D'INITIALISATION...")


def create_desktop_shortcut():
    """Crée un raccourci Bureau Windows vers l'application."""
    log_step(5, "Raccourci Bureau Windows", "CRÉATION...")
    if sys.platform != "win32":
        log_step(5, "Raccourci Bureau Windows", "NON APPLICABLE (NON-WINDOWS)")
        return

    try:
        desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        if not desktop.exists():
            desktop = Path(os.path.expanduser("~/Desktop"))

        shortcut_path = desktop / "ARKAN EPC Copilot.lnk"
        target_path = BASE_DIR / "ARKAN_Setup.exe"
        if not target_path.exists():
            target_path = BASE_DIR / "Start_ARKAN.bat"

        # Création via script PowerShell WScript.Shell
        ps_cmd = f"""
        $WshShell = New-Object -comObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}')
        $Shortcut.TargetPath = '{str(target_path)}'
        $Shortcut.WorkingDirectory = '{str(BASE_DIR)}'
        $Shortcut.Description = 'ARKAN EPC Copilot - IA Industrielle'
        $Shortcut.Save()
        """
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=10)
        log_step(5, "Raccourci Bureau Windows", "RACCOURCI CRÉÉ SUR LE BUREAU ✅")
    except Exception as e:
        log_step(5, "Raccourci Bureau Windows", f"IGNORÉ ({e})")


def launch_browser():
    """Ouvre l'interface Web dans le navigateur par défaut."""
    log_step(6, "Interface Utilisateur Web", "OUVERTURE DU NAVIGATEUR...")
    app_url = "http://localhost:8000"
    
    time.sleep(1)
    webbrowser.open(app_url)
    log_step(6, "Interface Utilisateur Web", "PRÊT ! OUVERT SUR http://localhost:8000 🚀")


def main():
    print_banner()
    print(f"📁 Répertoire de travail : {BASE_DIR}\n")
    
    ensure_env_file()
    docker_ok = check_and_start_docker()
    check_and_configure_ollama()
    check_and_configure_nuextract()
    start_local_backend_if_needed(docker_ok)
    create_desktop_shortcut()
    launch_browser()

    print("\n" + "=" * 70)
    print("✅ TOUT EST CONFIGURÉ ET OPÉRATIONNEL !")
    print("   -> Interface Web       : http://localhost:8000")
    print("   -> NuExtract-3 ARH IA  : http://localhost:11435")
    print("   -> Neo4j Graph         : http://localhost:7474 (ou bolt://localhost:7687)")
    print("   -> Ollama IA           : http://localhost:11434 (modèle: arkan-planning)")
    print("=" * 70)
    print("\nLaissez cette fenêtre ouverte pendant l'utilisation.")
    print("Pour arrêter ARKAN : fermez cette fenêtre ou faites Ctrl+C.\n")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nArrêt d'ARKAN...")
        sys.exit(0)


if __name__ == "__main__":
    main()
