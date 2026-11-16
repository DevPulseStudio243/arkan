"""
kaggle_mouse_jiggler.py
=======================
Script utilitaire Windows pour maintenir la session Kaggle active et empêcher
la mise en veille du système / écran pendant l'entraînement de modèles IA.

Fonctionnalités :
  1. Micro-mouvement de la souris (1 pixel aller-retour) toutes les 60 secondes.
  2. Appel de l'API Windows SetThreadExecutionState pour empêcher la mise en veille de l'écran.
  3. Arrêt propre avec Ctrl + C.
"""

import sys
import time
import ctypes
from datetime import datetime

# Windows API Structures
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

# Windows API Flags for Sleep Prevention
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def prevent_sleep():
    """Empêche Windows de couper l'écran ou de se mettre en veille."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    except Exception as e:
        print(f"[Avertissement] SetThreadExecutionState: {e}")

def restore_sleep():
    """Restaure les paramètres normaux de gestion d'énergie de Windows."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:
        pass

def move_mouse_micro():
    """Fait un micro-mouvement de 1 pixel aller-retour sans déranger l'utilisateur."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    # Déplacement de 1 pixel à droite
    ctypes.windll.user32.SetCursorPos(pt.x + 1, pt.y)
    time.sleep(0.05)
    # Retour à la position exacte
    ctypes.windll.user32.SetCursorPos(pt.x, pt.y)

def main():
    interval_seconds = 60
    print("=" * 65)
    print("  🟢 ARKAN - KAGGLE SESSION KEEP-ALIVE & MOUSE JIGGLER")
    print("=" * 65)
    print(f"[*] Intervalle d'activité : toutes les {interval_seconds} secondes")
    print("[*] Empêche la mise en veille de l'écran et maintient Kaggle actif")
    print("[*] Appuyez sur [Ctrl + C] pour arrêter à tout moment\n")

    prevent_sleep()
    counter = 1

    try:
        while True:
            move_mouse_micro()
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] Ping #{counter:03d} : Souris active + Session maintenue...")
            counter += 1
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n\n[!] Arrêt du Mouse Jiggler demandé par l'utilisateur.")
        restore_sleep()
        print("[✓] Paramètres de veille Windows restaurés. À bientôt !")

if __name__ == "__main__":
    main()
