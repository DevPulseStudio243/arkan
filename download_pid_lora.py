import os
import sys
import shutil
import zipfile
from pathlib import Path

# Fix Windows console & file encoding
import builtins
orig_open = builtins.open
def utf8_open(file, mode='r', *args, **kwargs):
    if 'b' not in mode and ('w' in mode or 'a' in mode) and 'encoding' not in kwargs:
        kwargs['encoding'] = 'utf-8'
    return orig_open(file, mode, *args, **kwargs)
builtins.open = utf8_open

from kaggle.api.kaggle_api_extended import KaggleApi

def main():
    kernel_id = "adleneboulouisa/arkan-pid-generator-finetune"
    target_dir = Path("arkan_pid_lora_adapter")
    output_dir = Path("kaggle_pid_output")
    output_dir.mkdir(exist_ok=True)
    
    api = KaggleApi()
    api.authenticate()
    
    print(f"Verification du statut du kernel Kaggle : {kernel_id}...")
    status_res = api.kernels_status_cli(kernel_id)
    print("Statut actuel:", status_res)
    
    print(f"\nTelechargement des fichiers de sortie...")
    try:
        outfiles, token = api.kernels_output(kernel_id, path=str(output_dir), quiet=False)
        print("Fichiers telecharges:", outfiles)
    except Exception as e:
        print("Erreur ou kernel encore en cours:", e)
        
    zip_path = output_dir / "arkan_pid_lora_adapter.zip"
    if zip_path.exists():
        print(f"Archive trouvee : {zip_path}. Extraction vers {target_dir}...")
        target_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(target_dir)
        print("Adaptateur LoRA developpe et pret dans ARKAN !")
        return True
    else:
        print("L'adaptateur LoRA n'est pas encore disponible dans l'archive.")
        return False

if __name__ == "__main__":
    main()
