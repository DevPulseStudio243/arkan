#!/usr/bin/env python3
# ============================================================
#  ARKAN LITE - Lanceur Unifie
#  IA locale Oil & Gas avec agents intelligents
#  Usage: python arkan_start.py [options]
#
#  Options:
#    --mode=base         Lance la version de base (v2.0)
#    --mode=enhanced     Lance la version amelioree (v3.0) [defaut]
#    --port=XXXX         Port du serveur (defaut: 8000)
#    --data-path=PATH    Chemin vers les documents Oil & Gas
#    --skip-checks       Ne pas verifier Ollama/modeles
#    --training          Lancer un cycle d'entrainement au demarrage
#    --install           Installer les dependances et configurer
#    --help              Afficher l'aide
# ============================================================

import os
import sys
import json
import time
import shutil
import subprocess
import argparse
import logging
from pathlib import Path

# ============================================================
#  Constants
# ============================================================

BANNER = r"""
     _      ____    _  __     _      _   _     _      _   _
    / \    |  _ \  | |/ /    / \    | \ | |   | |    (_) | |_  ___
   / _ \   | |_) | | ' /    / _ \   |  \| |   | |    | | | __|/ _ \
  / ___ \  |  _ <  | . \   / ___ \  | |\  |   | |___ | | | |_|  __/
 /_/   \_\ |_| \_\ |_|\_\ /_/   \_\ |_| \_|   |_____||_|  \__|\___|

  IA locale Oil & Gas - Pipeline RAG avec Agents Intelligents
  v3.0 Enhanced - Anti-hallucination & Apprentissage continu
"""

REQUIRED_MODELS = {
    "llm": "llama3.1:8b",
    "embed": "nomic-embed-text",
    "vision": "llava:7b",
}

PERSISTENCE_FILES = [
    "knowledge_db.json",
    "knowledge_graph.json",
    "feedback_db.json",
    "vocabulary.json",
    "vision_cache.json",
    "project_model.json",
    "project_taxonomy.json",
    "project_entities.json",
    "project_relations.json",
    "agent_state.json",
    "agent_history.json",
    "conversation_memory.json",
    "task_queue.json",
    "metrics.json",
    "cache_index.json",
    "error_log.json",
    "training_log.json",
]

SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".docx", ".xlsx",
    ".xls", ".pptx", ".csv", ".json", ".xml",
}

# ============================================================
#  Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("arkan_launcher")

# ── Rotation automatique des logs ────────────────────────────────────────────
# arkan.log : max 5 MB × 3 fichiers de backup (rotation automatique)
# Empêche le log de grossir sans limite (521 KB → ∞ sans cette correction).
try:
    from logging.handlers import RotatingFileHandler as _RFH
    _log_file = Path(__file__).parent / "arkan.log"
    _rotating_handler = _RFH(
        str(_log_file),
        maxBytes=5 * 1024 * 1024,   # 5 MB par fichier
        backupCount=3,               # arkan.log + arkan.log.1/2/3
        encoding="utf-8",
    )
    _rotating_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    )
    # Attacher le handler rotatif au logger racine (capte TOUS les modules)
    _root_logger = logging.getLogger()
    _root_logger.addHandler(_rotating_handler)
    logger.info(
        "[Logs] RotatingFileHandler actif : %s (max 5 MB × 3 fichiers)", _log_file
    )
except Exception as _log_e:
    logger.warning("[Logs] Impossible d'activer la rotation des logs : %s", _log_e)

# ============================================================
#  Utility Functions
# ============================================================

def print_header(title):
    """Print a formatted section header."""
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_step(step_num, total, description):
    """Print a progress step."""
    print(f"\n  [{step_num}/{total}] {description}")
    print("  " + "-" * 50)


def print_ok(message):
    """Print a success message."""
    print(f"  [OK] {message}")


def print_warn(message):
    """Print a warning message."""
    print(f"  [!!] {message}")


def print_fail(message):
    """Print an error message."""
    print(f"  [ERREUR] {message}")


def run_command(cmd, check=True, capture=True, timeout=120):
    """Run a shell command and return the result."""
    try:
        if isinstance(cmd, str):
            import shlex
            cmd = shlex.split(cmd)
        result = subprocess.run(
            cmd,
            shell=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            logger.warning("Command failed: %s\n%s", cmd, stderr)
            return None
        return result
    except subprocess.TimeoutExpired:
        logger.error("Command timed out: %s", cmd)
        return None
    except Exception as e:
        logger.error("Command error: %s - %s", cmd, e)
        return None


def check_python():
    """Verify Python version >= 3.10."""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print_ok(f"Python {version.major}.{version.minor}.{version.micro}")
        return True
    print_fail(f"Python 3.10+ requis (actuel: {version.major}.{version.minor})")
    return False


def check_ollama():
    """Check if Ollama is installed and running."""
    # Check if installed
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        print_warn("Ollama non trouve dans le PATH")
        print("  Installer depuis: https://ollama.ai/download")
        return False

    # Check if running
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            print_ok("Ollama est installe et en cours d'execution")
            return True
    except Exception:
        pass

    print_warn("Ollama est installe mais ne semble pas en cours d'execution")
    print("  Lancez: ollama serve")
    return False


def check_models():
    """Check if required Ollama models are available."""
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=10)
        if resp.status_code != 200:
            return False

        available = {m["name"].split(":")[0]: m["name"] for m in resp.json().get("models", [])}
        all_ok = True

        for role, model_name in REQUIRED_MODELS.items():
            base_name = model_name.split(":")[0]
            if base_name in available or model_name in [m for m in available.values()]:
                print_ok(f"Modele {role}: {model_name}")
            else:
                print_warn(f"Modele {role} manquant: {model_name}")
                print(f"    Telecharger: ollama pull {model_name}")
                all_ok = False

        return all_ok
    except Exception as e:
        print_fail(f"Impossible de verifier les modeles: {e}")
        return False


def install_dependencies():
    """Install Python dependencies from requirements.txt."""
    req_path = Path(__file__).parent / "requirements.txt"
    if not req_path.exists():
        print_fail("requirements.txt non trouve")
        return False

    print("  Installation des dependances Python...")
    result = run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(req_path), "-q"],
        timeout=300,
    )
    if result and result.returncode == 0:
        print_ok("Dependances installees")
        return True
    else:
        print_fail("Echec de l'installation des dependances")
        return False


def init_persistence_files():
    """Initialize JSON persistence files if they don't exist."""
    base_dir = Path(__file__).parent
    created = 0

    for filename in PERSISTENCE_FILES:
        filepath = base_dir / filename
        if not filepath.exists():
            # feedback_db and knowledge_db use arrays, others use objects
            if filename in ("feedback_db.json",):
                default = "[]"
            else:
                default = "{}"
            filepath.write_text(default, encoding="utf-8")
            created += 1

    if created:
        print_ok(f"{created} fichiers de persistance initialises")
    else:
        print_ok("Fichiers de persistance deja presents")
    return True


def init_data_directory(data_path):
    """Ensure the data directory exists."""
    dp = Path(data_path)
    dp.mkdir(parents=True, exist_ok=True)
    print_ok(f"Repertoire de donnees: {dp.resolve()}")

    # Count documents
    count = sum(1 for f in dp.rglob("*") if f.suffix.lower() in SUPPORTED_EXTENSIONS)
    if count:
        print_ok(f"{count} document(s) technique(s) trouve(s)")
    else:
        print_warn("Aucun document trouve - ajoutez vos fichiers Oil & Gas dans ce dossier")

    return True


def init_directories():
    """Create required directories."""
    base_dir = Path(__file__).parent
    dirs = [
        base_dir / "chroma_db",
        base_dir / "uploads",
        base_dir / "training_data",
        base_dir / "training_exports",
        base_dir / "fine_tuned_models",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    print_ok("Repertoires crees/verifies")
    return True


def verify_imports(mode):
    """Verify that all required modules can be imported."""
    base_dir = Path(__file__).parent
    original_path = sys.path.copy()

    # Ensure the arkan_lite directory is in sys.path
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    errors = []

    # Base modules
    base_modules = [
        "config",
        "query_planner",
        "retriever",
        "prompts",
        "indexer",
        "extractors",
        "classifier",
        "entities",
        "guardrails",
        "feedback",
        "knowledge_graph",
        "vocabulary",
        "auto_indexer",
    ]

    enhanced_modules = [
        "config_enhanced",
        "agents",
        "training",
        "project_understanding",
        "file_processor",
    ]

    modules_to_check = base_modules
    if mode == "enhanced":
        modules_to_check += enhanced_modules

    for mod_name in modules_to_check:
        try:
            __import__(mod_name)
            print_ok(f"Module: {mod_name}")
        except ImportError as e:
            print_fail(f"Module: {mod_name} - {e}")
            errors.append(mod_name)
        except Exception as e:
            print_warn(f"Module: {mod_name} - Avertissement: {e}")

    sys.path = original_path
    return len(errors) == 0


def run_training_cycle():
    """Run an initial training cycle."""
    base_dir = Path(__file__).parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    try:
        from training import ContinuousTrainer
        trainer = ContinuousTrainer()
        summary = trainer.run_full_cycle()
        print_ok(f"Cycle d'entrainement termine: {json.dumps(summary, indent=2, default=str)}")
        return True
    except Exception as e:
        print_warn(f"Entrainement echoue: {e}")
        return False


def start_server(mode, port):
    """Start the FastAPI server."""
    base_dir = Path(__file__).parent

    # Determine which API module to use
    api_module = "api_enhanced" if mode == "enhanced" else "api"
    api_file = base_dir / f"{api_module}.py"

    if not api_file.exists():
        print_fail(f"Module API non trouve: {api_file}")
        return False

    print_header("DEMARRAGE DU SERVEUR")
    print(f"\n  Mode:     {mode.upper()}")
    print(f"  Port:     {port}")
    print(f"  Module:   {api_module}")
    print(f"  UI:       http://localhost:{port}")
    print(f"  API Docs: http://localhost:{port}/docs")
    print(f"\n  Appuyez sur Ctrl+C pour arreter le serveur\n")

    # Set environment variables
    os.environ.setdefault("PYTHONPATH", str(base_dir))

    try:
        cmd = [
            sys.executable, "-m", "uvicorn",
            f"{api_module}:app",
            "--host", "0.0.0.0",
            "--port", str(port),
        ]
        if os.environ.get("ARKAN_RELOAD", "false").lower() == "true":
            cmd.extend(["--reload", "--reload-dir", str(base_dir)])
            print("  Reload auto-restart enabled.")
        else:
            print("  Reload auto-restart disabled (production/stable mode).")
            
        subprocess.run(cmd, cwd=str(base_dir))
    except KeyboardInterrupt:
        print("\n\n  Serveur arrete proprement.")
    except Exception as e:
        print_fail(f"Erreur demarrage serveur: {e}")
        return False

    return True


# ============================================================
#  Main Entry Point
# ============================================================

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="ARKAN Lite - IA locale Oil & Gas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python arkan_start.py                          # Lance en mode enhanced
  python arkan_start.py --mode=base              # Lance en mode base
  python arkan_start.py --install                # Installe et configure
  python arkan_start.py --port=9000              # Port personnalise
  python arkan_start.py --data-path=/mes/docs    # Dossier documents
  python arkan_start.py --training               # Avec entrainement initial
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["base", "enhanced"],
        default="enhanced",
        help="Mode de fonctionnement (defaut: enhanced)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port du serveur HTTP (defaut: 8000)",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=None,
        help="Chemin vers les documents Oil & Gas",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Ne pas verifier Ollama et les modeles",
    )
    parser.add_argument(
        "--training",
        action="store_true",
        help="Lancer un cycle d'entrainement au demarrage",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Installer les dependances et configurer le systeme",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    print(BANNER)
    args = parse_args()

    base_dir = Path(__file__).parent

    # Set data path environment variable if provided
    if args.data_path:
        os.environ["RAG_DATA_PATH"] = args.data_path
        data_path = args.data_path
    else:
        data_path = os.environ.get("RAG_DATA_PATH", str(base_dir / "data"))

    total_steps = 7
    if args.install:
        total_steps = 8
    if args.training:
        total_steps += 1

    step = 0

    # -- Step 1: Python Version Check --
    step += 1
    print_step(step, total_steps, "Verification de Python")
    if not check_python():
        sys.exit(1)

    # -- Step 2: Install Dependencies (optional) --
    if args.install:
        step += 1
        print_step(step, total_steps, "Installation des dependances")
        if not install_dependencies():
            print_warn("Certaines dependances n'ont pas pu etre installees")
            print("  Verifiez manuellement: pip install -r requirements.txt")

    # -- Step 3: Create Directories --
    step += 1
    print_step(step, total_steps, "Initialisation des repertoires")
    init_directories()
    init_data_directory(data_path)

    # -- Step 4: Initialize Persistence Files --
    step += 1
    print_step(step, total_steps, "Initialisation des fichiers de persistance")
    init_persistence_files()

    # -- Step 5: Check Ollama --
    if not args.skip_checks:
        step += 1
        print_step(step, total_steps, "Verification d'Ollama")
        ollama_ok = check_ollama()
        if ollama_ok:
            check_models()
        else:
            print_warn("Ollama n'est pas disponible - le systeme necessera Ollama pour fonctionner")
            print("  1. Installez Ollama: https://ollama.ai/download")
            print("  2. Lancez: ollama serve")
            print(f"  3. Telechargez les modeles:")
            for role, model in REQUIRED_MODELS.items():
                print(f"     ollama pull {model}")
    else:
        step += 1
        print_step(step, total_steps, "Verification d'Ollama (ignoree)")
        print_warn("Verifications ignorees (--skip-checks)")

    # -- Step 6: Verify Module Imports --
    step += 1
    print_step(step, total_steps, "Verification des modules Python")

    # Add base_dir to sys.path for imports
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    if not verify_imports(args.mode):
        print_fail("Certains modules ne peuvent pas etre importes")
        print("  Verifiez que toutes les dependances sont installees")
        print("  Lancez: python arkan_start.py --install")

    # -- Step 7: Training Cycle (optional) --
    if args.training:
        step += 1
        print_step(step, total_steps, "Cycle d'entrainement initial")
        run_training_cycle()

    # -- Step 8: Start Server --
    step += 1
    print_step(step, total_steps, "Demarrage du serveur")
    start_server(args.mode, args.port)


if __name__ == "__main__":
    main()
