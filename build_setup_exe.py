import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
os.chdir(str(BASE_DIR))

print("=" * 70)
print("COMPILATION DE ARKAN_Setup.exe AVEC PYINSTALLER")
print("=" * 70)

# Commande PyInstaller
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--name", "ARKAN_Setup",
    "--clean",
    "--noconfirm",
    "--distpath", str(BASE_DIR),
    "arkan_setup_launcher.py"
]

print(f"Exécution : {' '.join(cmd)}\n")
res = subprocess.run(cmd, cwd=str(BASE_DIR))

if res.returncode == 0:
    print("\n" + "=" * 70)
    print("✅ SUCCÈS ! Exécutable créé à la racine :")
    exe_path = BASE_DIR / "ARKAN_Setup.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"   -> {exe_path} ({size_mb:.1f} MB)")
    print("=" * 70)
    
    # Nettoyage des dossiers build/ et spec
    build_dir = BASE_DIR / "build"
    spec_file = BASE_DIR / "ARKAN_Setup.spec"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    if spec_file.exists():
        spec_file.unlink()
else:
    print(f"\n❌ Erreur lors de la compilation (code {res.returncode})")
