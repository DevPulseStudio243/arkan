"""
dwg_converter.py
=================
Convertisseur DWG vers DXF multi-moteurs pour ARKAN.

Moteurs (essayes dans l'ordre jusqu'a obtenir un DXF VALIDE) :
  1. GNU LibreDWG  (bin/cad/dwg2dxf.exe ou dwg2dxf du PATH)
  2. Acme CAD Converter (si installe)
  3. AutoCAD accoreconsole (si installe)
  4. ODA File Converter (si installe)
  5. Automatisation COM AutoCAD (autocad_worker)

Corrections par rapport a la version precedente :
  - un moteur n'est declare reussi que si le DXF produit se relit avec ezdxf et contient des entites
    (avant : simple test taille > 100 octets, un DXF tronque passait pour valide)
  - chaque moteur ecrit dans un fichier TEMPORAIRE, deplace ensuite de facon atomique : un ancien .dxf
    laisse a l'emplacement cible n'est plus pris pour le resultat d'un moteur en echec
  - cache par CONTENU (md5 du DWG) : un DWG revise sous le meme nom est reconverti
  - timeout proportionnel a la taille du DWG (60 s fixes faisaient echouer les gros plans)
  - sans chemin de sortie, le DXF n'est plus ecrit a cote du DWG mais dans le cache
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("dwg_converter")


class DWGConversionError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# Localisation des moteurs
# ----------------------------------------------------------------------------
def _find_libredwg() -> str:
    """Localise dwg2dxf integre dans ARKAN ou sur le systeme."""
    here = Path(__file__).parent
    candidates = [here / "bin" / "cad" / "dwg2dxf.exe", here / "bin" / "cad" / "dwg2dxf",
                  here / "dwg2dxf.exe", Path(r"D:\DATA BASE IA\bin\cad\dwg2dxf.exe")]
    for c in candidates:
        if c.suffix.lower() == ".exe" and os.name != "nt":
            continue                       # un .exe Windows n'est pas executable hors Windows (Permission denied)
        try:
            if c.exists():
                return str(c.resolve())
        except OSError:
            continue
    return shutil.which("dwg2dxf") or ""


def _find_acme_converter() -> str:
    for c in (r"C:\Program Files (x86)\Acme CAD Converter\AcmeCADConverter.exe",
              r"C:\Program Files\Acme CAD Converter\AcmeCADConverter.exe"):
        if Path(c).exists():
            return c
    return shutil.which("AcmeCADConverter") or ""


def _find_accoreconsole() -> str:
    for year in range(2025, 2019, -1):          # du plus recent au plus ancien
        p = rf"C:\Program Files\Autodesk\AutoCAD {year}\accoreconsole.exe"
        if Path(p).exists():
            return p
    return shutil.which("accoreconsole") or ""


def _find_oda_converter() -> str:
    for name in ("ODAFileConverter", "oda_file_converter", r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"):
        path = shutil.which(name) or (name if Path(name).exists() else None)
        if path:
            return str(path)
    return ""


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------
def cache_dir() -> Path:
    """Dossier de cache DXF (surchargeable par ARKAN_CAD_CACHE)."""
    d = Path(os.environ.get("ARKAN_CAD_CACHE") or Path(__file__).parent / "cad_cache" / "dxf")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _timeout_for(dwg: Path) -> int:
    """Timeout en secondes : 120 s + 120 s par Mo de DWG (plafonne a 900 s). ARKAN_DWG_TIMEOUT force la valeur."""
    env = os.environ.get("ARKAN_DWG_TIMEOUT")
    if env and env.isdigit():
        return int(env)
    return int(min(900, 120 + 120 * dwg.stat().st_size / (1 << 20)))


def validate_dxf(path: Path | str, min_entities: int = 1) -> bool:
    """Un DXF est valide s'il se relit et contient au moins `min_entities` entites en espace objet."""
    p = Path(path)
    if not p.exists() or p.stat().st_size < 100:
        return False
    try:
        import ezdxf
    except ImportError:                                   # sans ezdxf : controle minimal de structure
        head = p.read_bytes()[:4096]
        return b"SECTION" in head and b"ENTITIES" in p.read_bytes()
    try:
        try:
            doc = ezdxf.readfile(str(p))
        except Exception:
            from ezdxf import recover
            doc, _ = recover.readfile(str(p))
        return sum(1 for _ in doc.modelspace()) >= min_entities
    except Exception as exc:
        logger.warning("DXF invalide %s : %s", p.name, exc)
        return False


def _version_digits(out_version: str) -> str:
    v = out_version.upper().replace("ACAD", "").replace("R", "") or "2018"
    return v if v in ("12", "14", "2000", "2004", "2007", "2010", "2013", "2018") else "2018"


# ----------------------------------------------------------------------------
# Moteurs : chacun ecrit dans `out` (chemin temporaire) et peut lever une exception
# ----------------------------------------------------------------------------
def _engine_libredwg(dwg: Path, out: Path, out_version: str, timeout: int) -> None:
    exe = _find_libredwg()
    if not exe:
        raise FileNotFoundError("dwg2dxf introuvable")
    env = os.environ.copy()
    env["PATH"] = str(Path(exe).parent) + os.pathsep + env.get("PATH", "")      # DLL a cote de l'exe
    res = subprocess.run([exe, "-y", "--as", f"r{_version_digits(out_version)}", "-o", str(out), str(dwg)],
                         capture_output=True, text=True, errors="replace", timeout=timeout, env=env)
    if res.returncode not in (0,):
        # dwg2dxf renvoie un code != 0 pour des avertissements sur objets inconnus : la validation du fichier tranche
        logger.info("dwg2dxf code retour %s : %s", res.returncode, (res.stderr or "")[-200:])


def _engine_acme(dwg: Path, out: Path, out_version: str, timeout: int) -> None:
    exe = _find_acme_converter()
    if not exe:
        raise FileNotFoundError("Acme CAD Converter introuvable")
    subprocess.run([exe, "/r", f"/x{_version_digits(out_version)}", str(dwg), str(out)],
                   capture_output=True, text=True, errors="replace", timeout=timeout)


def _engine_accore(dwg: Path, out: Path, out_version: str, timeout: int) -> None:
    exe = _find_accoreconsole()
    if not exe:
        raise FileNotFoundError("accoreconsole introuvable")
    scr = out.parent / "convert.scr"
    scr.write_text('FILEDIA 0\nCMDDIA 0\nDXFOUT\n"%s"\n16\nQUIT\nY\n' % str(out).replace("\\", "/"),
                   encoding="utf-8")
    subprocess.run([exe, "/i", str(dwg), "/s", str(scr)], capture_output=True, text=True,
                   errors="replace", timeout=timeout)


def _engine_oda(dwg: Path, out: Path, out_version: str, timeout: int) -> None:
    exe = _find_oda_converter()
    if not exe:
        raise FileNotFoundError("ODA File Converter introuvable")
    with tempfile.TemporaryDirectory() as in_dir, tempfile.TemporaryDirectory() as out_dir:
        shutil.copy(dwg, Path(in_dir) / dwg.name)
        subprocess.run([exe, in_dir, out_dir, out_version, "DXF", "0", "1", "*.dwg"],
                       capture_output=True, text=True, errors="replace", timeout=timeout)
        produced = Path(out_dir) / (dwg.stem + ".dxf")
        if produced.exists():
            shutil.move(str(produced), str(out))


def _engine_com(dwg: Path, out: Path, out_version: str, timeout: int) -> None:
    from autocad_worker import convert_dwg_to_dxf_direct
    convert_dwg_to_dxf_direct(str(dwg), str(out))


_ENGINES: List[Tuple[str, Callable]] = [
    ("LibreDWG", _engine_libredwg), ("Acme CAD Converter", _engine_acme),
    ("AutoCAD accoreconsole", _engine_accore), ("ODA File Converter", _engine_oda),
    ("AutoCAD COM", _engine_com),
]


# ----------------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------------
def convert_dwg_to_dxf(dwg_path: str, output_dxf_path: Optional[str] = None, out_version: str = "ACAD2018") -> str:
    """Convertit un DWG en DXF et retourne le chemin du DXF produit (valide).

    Sans `output_dxf_path`, le resultat est le fichier du cache (<stem>_<md5>.dxf).
    Avec `output_dxf_path`, le DXF y est copie ; le cache est utilise s'il contient deja ce DWG.
    """
    dwg = Path(dwg_path).resolve()
    if not dwg.exists():
        raise DWGConversionError(f"Fichier DWG introuvable : {dwg}")

    cached = cache_dir() / f"{dwg.stem}_{_md5(dwg)[:12]}.dxf"
    target = Path(output_dxf_path).resolve() if output_dxf_path else cached

    if cached.exists() and validate_dxf(cached):
        logger.info("DXF en cache : %s", cached)
        return _deliver(cached, target)

    timeout = _timeout_for(dwg)
    errors: List[str] = []
    for name, engine in _ENGINES:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.dxf"
            try:
                engine(dwg, out, out_version, timeout)
            except FileNotFoundError:
                continue                                  # moteur non installe : suivant
            except subprocess.TimeoutExpired:
                errors.append(f"{name} : timeout {timeout}s")
                logger.warning("%s : timeout apres %ss pour %s", name, timeout, dwg.name)
                continue
            except Exception as exc:
                errors.append(f"{name} : {exc}")
                logger.warning("%s a echoue pour %s : %s", name, dwg.name, exc)
                continue
            if validate_dxf(out):
                part = cached.with_suffix(".part")                # ecriture dans le cache puis remplacement atomique
                shutil.copyfile(out, part)
                os.replace(part, cached)
                logger.info("Conversion DWG->DXF reussie via %s (%d octets)", name, cached.stat().st_size)
                return _deliver(cached, target)
            errors.append(f"{name} : DXF produit invalide ou vide")
            logger.warning("%s : DXF invalide pour %s, moteur suivant", name, dwg.name)

    detail = " ; ".join(errors) or "aucun moteur installe"
    raise DWGConversionError(f"Impossible de convertir {dwg.name} en DXF ({detail}).")


def _deliver(cached: Path, target: Path) -> str:
    if target != cached:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        shutil.copyfile(cached, tmp)
        os.replace(tmp, target)                           # remplacement atomique
    return str(target)


def ensure_dxf(path: str) -> str:
    """Retourne un chemin DXF exploitable, en convertissant depuis DWG si besoin."""
    low = str(path).lower()
    if low.endswith(".dxf"):
        return str(path)
    if low.endswith(".dwg"):
        return convert_dwg_to_dxf(path)
    raise DWGConversionError(f"Extension non supportee : {path} (attendu .dxf ou .dwg)")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python dwg_converter.py <fichier.dwg> [sortie.dxf]")
        sys.exit(1)
    try:
        print(f"[OK] Conversion reussie : {convert_dwg_to_dxf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)}")
    except Exception as err:
        print(f"[ERREUR] Echec de conversion : {err}")
        sys.exit(2)
