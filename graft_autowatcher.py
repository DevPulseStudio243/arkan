#!/usr/bin/env python3
"""
ARKAN GRAFT AUTO-WATCHER
Surveille les modifications de fichiers Python/JS et reconstruit automatiquement
le graphe Graft après un délai de stabilisation de 30 secondes.
Tourne en daemon en arrière-plan.
"""
import os
import sys
import time
import subprocess
import threading
import datetime
import pathlib

WATCH_DIR = pathlib.Path(__file__).parent
GRAFT_CMD = str(WATCH_DIR / "node_modules" / ".bin" / "graft.cmd")
EXTENSIONS = {".py", ".js", ".ts"}
DEBOUNCE_SECONDS = 30  # attend 30s de stabilité avant de rebuilder
LOG_FILE = WATCH_DIR / "graft_autowatcher.log"

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def rebuild_graft():
    log("🔄 Déclenchement rebuild Graft...")
    try:
        env = os.environ.copy()
        env["PATH"] = str(WATCH_DIR / "node_modules" / ".bin") + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            [GRAFT_CMD, "build"],
            cwd=str(WATCH_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            env=env
        )
        if result.returncode == 0:
            # Compter les noeuds
            import json
            graph_path = WATCH_DIR / "graft" / ".graph" / "wiring.json"
            if graph_path.exists():
                with open(graph_path, encoding="utf-8") as f:
                    data = json.load(f)
                nodes = len(data.get("nodes", []))
                edges = len(data.get("edges", []))
                log(f"✅ Graft rebuilt avec succès — {nodes} nœuds, {edges} arêtes")
            else:
                log("✅ Graft rebuilt avec succès")
        else:
            log(f"⚠️ Graft rebuild erreur (code {result.returncode}): {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log("⚠️ Graft rebuild timeout (>180s)")
    except Exception as e:
        log(f"❌ Erreur rebuild: {e}")

class FileWatcher:
    def __init__(self, watch_dir: pathlib.Path):
        self.watch_dir = watch_dir
        self.pending_rebuild = False
        self.last_change = 0
        self.timer: threading.Timer | None = None
        self._snapshot = self._take_snapshot()
        log(f"🟢 ARKAN Graft AutoWatcher démarré — surveillance de {watch_dir}")
        log(f"   Extensions: {EXTENSIONS}")
        log(f"   Délai de stabilisation: {DEBOUNCE_SECONDS}s")

    def _take_snapshot(self) -> dict:
        """Prend un snapshot des mtimes de tous les fichiers surveillés."""
        snapshot = {}
        ignore_dirs = {"node_modules", ".git", "__pycache__", "graft", ".venv", "venv"}
        for root, dirs, files in os.walk(self.watch_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for fname in files:
                if pathlib.Path(fname).suffix in EXTENSIONS:
                    fpath = pathlib.Path(root) / fname
                    try:
                        snapshot[str(fpath)] = fpath.stat().st_mtime
                    except OSError:
                        pass
        return snapshot

    def _schedule_rebuild(self):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(DEBOUNCE_SECONDS, rebuild_graft)
        self.timer.daemon = True
        self.timer.start()

    def poll(self):
        """Vérifie les changements toutes les 5 secondes."""
        while True:
            time.sleep(5)
            try:
                new_snapshot = self._take_snapshot()
                changed = []
                # Fichiers modifiés ou nouveaux
                for path, mtime in new_snapshot.items():
                    if path not in self._snapshot or self._snapshot[path] != mtime:
                        changed.append(path)
                # Fichiers supprimés
                for path in self._snapshot:
                    if path not in new_snapshot:
                        changed.append(path)

                if changed:
                    rel_changed = [os.path.relpath(p, self.watch_dir) for p in changed[:3]]
                    log(f"📝 {len(changed)} fichier(s) modifié(s): {rel_changed} → rebuild dans {DEBOUNCE_SECONDS}s")
                    self._snapshot = new_snapshot
                    self._schedule_rebuild()
            except Exception as e:
                log(f"⚠️ Erreur poll: {e}")

def main():
    log("=" * 60)
    log("  ARKAN GRAFT AUTO-WATCHER v1.0")
    log("=" * 60)
    watcher = FileWatcher(WATCH_DIR)
    # Rebuild initial au démarrage
    threading.Thread(target=rebuild_graft, daemon=True).start()
    # Boucle de surveillance
    watcher.poll()

if __name__ == "__main__":
    main()
