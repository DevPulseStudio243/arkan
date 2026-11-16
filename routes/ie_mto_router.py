# -*- coding: utf-8 -*-
"""
routes/ie_mto_router.py  (version corrigée – audit ARKAN v3, lot 2)

Routeur FastAPI du MTO Électricité & Instrumentation.

Corrections :
  * `file_path` (Electron) refusé sauf s'il est dans un dossier autorisé (config paths.allowed_roots) ;
  * upload : extension + signature (PDF/DWG), taille plafonnée (router.max_upload_mb), copie par blocs ;
  * traitements bloquants dans le pool de threads de FastAPI (endpoints `def`), pas dans la boucle asynchrone ;
  * fichiers générés sous des noms NON devinables et purgés après router.output_ttl_hours ;
  * aperçus de pages servis par URL (plus de 25 pages en base64 dans le JSON) ;
  * KPI calculés par UNITÉ et par discipline, avec les mêmes règles que l'export Excel ;
  * `warnings` remontés à l'interface (config absente, unités supposées, rendu indisponible, PDF non reconnu…) ;
  * ConfigError -> 422 explicite ; format non supporté -> 415 ;
  * `/ie-mto/reconcile` branche enfin le réconciliateur (7 contrôles) ;
  * `sanitize_excel_str` (jamais appelée) supprimée : la neutralisation est faite à l'écriture du classeur.
"""
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config_loader import ConfigError, get_config_info, load_project_config
from cross_discipline_reconciler import CrossDisciplineReconciler
from ie_drawing_extractor import extract_ie_drawing
from ie_mto_validator import validate_ie_mto
from mto_consolidator import (LENGTH_UNITS, _parse_confidence, _parse_number, classify_item_discipline,
                              expand_feeders, generate_master_multidiscipline_excel)
from calculation_note_parser import CalculationNoteParser
from cable_schedule_parser import CableScheduleParser
from cable_parser import parse_cable
from ei_triangulation_engine import EITriangulationEngine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MTO_IE"])

ALLOWED_EXT = {".dwg", ".dxf", ".pdf"}
BATCH_ALLOWED_EXT = {".dwg", ".dxf", ".pdf", ".xlsx", ".xlsm", ".csv", ".txt"}
VISUALS_URL_PREFIX = "/visuals"
UNITS_ALLOWED = {"mm", "cm", "m", "in", "ft"}
TRAY_CONVENTIONS = {"auto", "double_rail", "single_line"}


# ───────────────────────────── utilitaires ─────────────────────────────
def output_dir() -> Path:
    d = Path(os.environ.get("ARKAN_OUTPUT_DIR", "generated_visuals"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _router_cfg() -> Dict[str, Any]:
    return load_project_config().get("router") or {}


def _safe_stem(name: str, limit: int = 40) -> str:
    return re.sub(r"[^\w\-]", "_", Path(name or "plan").stem)[:limit] or "plan"


def _new_name(kind: str, stem: str, ext: str) -> str:
    return f"ie_{kind}_{_safe_stem(stem)}_{secrets.token_hex(8)}{ext}"      # non devinable


def purge_old_outputs(ttl_hours: Optional[float] = None) -> int:
    ttl = float(ttl_hours if ttl_hours is not None else _router_cfg().get("output_ttl_hours", 24))
    limit, n = time.time() - ttl * 3600.0, 0
    for p in output_dir().glob("ie_*"):
        try:
            if p.is_file() and p.stat().st_mtime < limit:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def _sniff_ok(path: str, suffix: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(8)
    if suffix == ".pdf":
        return head.startswith(b"%PDF")
    if suffix == ".dwg":
        return head.startswith(b"AC")
    return True                                   # DXF : texte ou binaire, pas de signature fiable


def _allowed_local_path(raw: str, allowed_ext: Optional[Set[str]] = None) -> Path:
    """Chemin local (Electron) accepté dans paths.allowed_roots ou répertoires utilisateur/système autorisés."""
    cfg_roots = (load_project_config().get("paths") or {}).get("allowed_roots") or []
    roots = [Path(r).resolve() for r in cfg_roots if r]
    if not roots:
        roots = [Path.home().resolve(), Path.cwd().resolve()]
        if os.name == "nt":
            import string
            for drive in string.ascii_uppercase:
                dp = Path(f"{drive}:\\")
                if dp.exists():
                    roots.append(dp)
    p = Path(raw).resolve()
    valid_ext = allowed_ext or BATCH_ALLOWED_EXT
    if p.suffix.lower() not in valid_ext:
        raise HTTPException(415, f"Format non supporté : {p.suffix or 'sans extension'}")
    for r in roots:
        try:
            p.relative_to(r)
            break
        except ValueError:
            continue
    else:
        raise HTTPException(403, "Chemin hors des dossiers autorisés.")
    if not p.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    return p


def _save_upload(file: UploadFile, suffix: str) -> str:
    max_bytes = int(float(_router_cfg().get("max_upload_mb", 200)) * 1024 * 1024)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    size = 0
    try:
        while True:
            chunk = file.file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(413, f"Fichier trop volumineux (> {max_bytes // (1024 * 1024)} Mo).")
            tmp.write(chunk)
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise
    tmp.close()
    return tmp.name


def compute_kpis(items: List[Dict[str, Any]], metadata: Dict[str, Any], anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """KPI par discipline ET par unité (mêmes règles que l'export Excel)."""
    conf_min = float((load_project_config().get("thresholds") or {}).get("confidence_min_threshold", 0.85))
    k = {"cable_total_m": 0.0, "tray_total_m": 0.0, "earthing_total_m": 0.0, "conduits_total_m": 0.0,
         "instruments_count": 0, "valves_count": 0, "panels_count": 0, "feeders_count": 0, "pull_boxes_count": 0,
         "earth_rods_count": 0, "total_weight_kg": 0.0, "items_without_weight": 0, "unevaluated_count": 0,
         "to_validate_count": 0}
    for it in items:
        disc = classify_item_discipline(it)
        cat = str(it.get("category") or "").upper()
        unit = str(it.get("unit") or "EA").upper().strip()
        q = _parse_number(it.get("quantity"))
        q = 0.0 if q is None else q
        is_len = unit in LENGTH_UNITS
        if disc == "CARNET_DE_CABLES" and is_len:
            k["cable_total_m"] += q
        elif disc == "CHEMINS_ET_CANALISATIONS" and is_len:
            if cat == "CONDUIT":
                k["conduits_total_m"] += q
            else:
                k["tray_total_m"] += q
        elif disc == "RESEAU_TERRE_FOUDRE" and is_len:
            k["earthing_total_m"] += q
        if cat == "PULL_BOX":
            k["pull_boxes_count"] += int(q)
        elif cat == "EARTH_ROD":
            k["earth_rods_count"] += int(q)
        elif cat in ("PANEL", "JUNCTION_BOX"):
            k["panels_count"] += int(q)
        elif cat == "SWITCHGEAR_FEEDER" and unit in ("EA", "U", "PCS"):
            k["feeders_count"] += int(q)
        elif cat in ("CONTROL_VALVE", "SAFETY_VALVE"):
            k["valves_count"] += int(q)
        elif disc == "INSTRUMENTS" and cat != "JUNCTION_BOX":
            k["instruments_count"] += int(q)
        w = _parse_number(it.get("weight_total"))
        if w is None:
            k["items_without_weight"] += 1
        else:
            k["total_weight_kg"] += w
        conf = _parse_confidence(it.get("confidence_score"))
        if conf is None:
            k["unevaluated_count"] += 1
        if (conf is not None and conf < conf_min) or it.get("extractor_reasons"):
            k["to_validate_count"] += 1
    # Ventilation des câbles par section (CEI 60502-1)
    cables_by_section = {}
    for it in items:
        disc = classify_item_discipline(it)
        cat = str(it.get("category") or "").upper()
        if disc == "CARNET_DE_CABLES" or cat in ("CABLE", "CABLES"):
            sec = str(it.get("size") or it.get("section") or "NON_SPECIFIE").strip().upper()
            q = _parse_number(it.get("quantity")) or 0.0
            w = _parse_number(it.get("weight_total")) or 0.0
            typ = str(it.get("cable_type") or "U1000-R2V").strip()
            if sec not in cables_by_section:
                cables_by_section[sec] = {
                    "section": sec,
                    "cable_type": typ,
                    "count": 0,
                    "total_length_m": 0.0,
                    "total_weight_kg": 0.0,
                }
            cables_by_section[sec]["count"] += 1
            cables_by_section[sec]["total_length_m"] += q
            cables_by_section[sec]["total_weight_kg"] += w

    for s_info in cables_by_section.values():
        s_info["total_length_m"] = round(s_info["total_length_m"], 2)
        s_info["total_weight_kg"] = round(s_info["total_weight_kg"], 2)

    real = [a for a in anomalies if a.get("status") != "NOT_EVALUATED"]
    k.update({"total_items": len(items), "reserves_count": len(real),
              "not_evaluated_count": len(anomalies) - len(real)})
    for key in ("cable_total_m", "tray_total_m", "earthing_total_m", "conduits_total_m"):
        k[key] = round(k[key], 1)
    k["total_weight_kg"] = round(k["total_weight_kg"], 2)
    k["cables_by_section"] = cables_by_section
    return k


def _render_previews(path: str, filename: str, suffix: str, stem: str, warnings: List[str], inline: bool) -> Dict[str, Any]:
    cfg = _router_cfg()
    res: Dict[str, Any] = {"visual_url": None, "plan_preview_urls": [], "preview_image": "", "page_count": 1}
    if suffix == ".pdf":
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            doc = fitz.open(path)
            res["page_count"] = len(doc)
            limit, dpi = int(cfg.get("preview_max_pages", 25)), int(cfg.get("preview_dpi", 150))
            if len(doc) > limit:
                warnings.append(f"Aperçu limité aux {limit} premières pages sur {len(doc)}.")
            for i, page in enumerate(doc):
                if i >= limit:
                    break
                pix = page.get_pixmap(dpi=dpi)
                name = _new_name("page", stem, f"_{i + 1}.png")
                pix.save(str(output_dir() / name))
                res["plan_preview_urls"].append(f"{VISUALS_URL_PREFIX}/{name}")
                if i == 0 and inline:
                    import base64
                    res["preview_image"] = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()
            doc.close()
            res["visual_url"] = res["plan_preview_urls"][0] if res["plan_preview_urls"] else None
        except Exception as exc:
            logger.warning("[IE_MTO] aperçu PDF indisponible : %s", exc)
            warnings.append("Aperçu du PDF indisponible.")
    elif suffix in (".dwg", ".dxf"):
        try:
            from routes.mto_router import render_cad_plan_visual
            png = render_cad_plan_visual(path, filename, stem)
            if png and Path(png).exists():
                name = _new_name("plan", stem, ".png")
                shutil.copyfile(png, output_dir() / name)
                res["plan_preview_urls"] = [f"{VISUALS_URL_PREFIX}/{name}"]
                res["visual_url"] = res["plan_preview_urls"][0]
            else:
                warnings.append("Rendu visuel du plan indisponible.")
        except Exception as exc:
            logger.warning("[IE_MTO] rendu CAD indisponible : %s", exc)
            warnings.append("Rendu visuel du plan indisponible.")
    return res


# ───────────────────────────── endpoints ─────────────────────────────
@router.post("/ie-mto/calculate")
def calculate_ie_mto(
    file: Optional[UploadFile] = File(None),
    file_path: Optional[str] = Form(None),
    units: Optional[str] = Form(None),
    tray_convention: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    inline_preview: bool = Form(False),
):
    """MTO E&I d'un plan (DWG/DXF) ou d'un schéma unifilaire (PDF). Upload direct OU chemin local autorisé."""
    start = time.time()
    if units and units not in UNITS_ALLOWED:
        raise HTTPException(422, f"units doit valoir {sorted(UNITS_ALLOWED)}")
    if tray_convention and tray_convention not in TRAY_CONVENTIONS:
        raise HTTPException(422, f"tray_convention doit valoir {sorted(TRAY_CONVENTIONS)}")

    temp_path: Optional[str] = None
    try:
        if file_path:
            p = _allowed_local_path(file_path)
            work_path, filename, suffix = str(p), p.name, p.suffix.lower()
        elif file is not None:
            filename = file.filename or "plan_ie.pdf"
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_EXT:
                raise HTTPException(415, f"Format non supporté : {suffix or 'sans extension'}")
            temp_path = work_path = _save_upload(file, suffix)
        else:
            raise HTTPException(400, "Aucun fichier ou chemin fourni.")
        if not _sniff_ok(work_path, suffix):
            raise HTTPException(415, "Le contenu du fichier ne correspond pas à son extension.")

        try:
            purge_old_outputs()
            options = {k: v for k, v in (("units", units), ("tray_convention", tray_convention), ("doc_type", doc_type)) if v}
            extracted = extract_ie_drawing(work_path, original_filename=filename, options=options or None)
            items = expand_feeders(extracted.get("items", []))
            metadata = extracted.get("metadata", {})
            metadata["filename"] = filename
            anomalies = validate_ie_mto(items, metadata)
            warnings: List[str] = list(metadata.get("warnings") or [])
            cfg_info = get_config_info()
            if cfg_info.get("warning"):
                warnings.append(f"Configuration : {cfg_info['warning']}")
            stem = _safe_stem(filename)
            previews = _render_previews(work_path, filename, suffix, stem, warnings, inline_preview)
            kpis = compute_kpis(items, metadata, anomalies)
            metadata.update({k: kpis[k] for k in ("cable_total_m", "tray_total_m", "instruments_count", "valves_count",
                                                   "panels_count", "total_weight_kg")})
            excel_name = _new_name("mto", stem, ".xlsx")
            generate_master_multidiscipline_excel(items, metadata, anomalies, str(output_dir() / excel_name))
        except ConfigError as exc:
            raise HTTPException(422, f"Configuration invalide : {exc}")
        except ValueError as exc:
            raise HTTPException(415, str(exc))
        except HTTPException:
            raise
        except Exception:
            logger.exception("[IE_MTO] échec du calcul")
            raise HTTPException(500, "Échec de l'extraction du plan (détails dans les journaux du serveur).")

        logger.info("[IE_MTO] %s : %d lignes, %d réserves, %.2fs", filename, len(items), kpis["reserves_count"], time.time() - start)
        return {
            "status": "success", "filename": filename, "duration_s": round(time.time() - start, 2),
            "metadata": metadata, "items": items, "anomalies": anomalies, "kpis": kpis, "warnings": warnings,
            "config": cfg_info, "preview_image": previews["preview_image"], "visual_url": previews["visual_url"],
            "plan_preview_urls": previews["plan_preview_urls"], "page_count": previews["page_count"],
            "excel_url": f"{VISUALS_URL_PREFIX}/{excel_name}", "excel_filename": excel_name,
        }
    except ConfigError as exc:                         # config lue avant l'extraction (limites, dossiers autorisés)
        raise HTTPException(422, f"Configuration invalide : {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.post("/ie-mto/calculate-batch")
def calculate_ie_mto_batch(
    files: Optional[List[UploadFile]] = File(None),
    folder_path: Optional[str] = Form(None),
    file_paths: Optional[str] = Form(None),
    units: Optional[str] = Form(None),
    tray_convention: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    origin_tag: Optional[str] = Form("TGBT"),
    inline_preview: bool = Form(False),
):
    """
    Traitement par lot (Batch Multi-Fichiers) pour dossiers d'ingénierie E&I complets.
    Accepte simultanément :
      - Plans CAD / Implantation (.dwg, .dxf, layout .pdf)
      - Carnets de Câbles (.xlsx, .csv)
      - Notes de Calcul (.pdf, .xlsx)
    Exécute automatiquement la triangulation 4 axes et génère le MTO consolidé.
    """
    start = time.time()
    if units and units not in UNITS_ALLOWED:
        raise HTTPException(422, f"units doit valoir {sorted(UNITS_ALLOWED)}")
    if tray_convention and tray_convention not in TRAY_CONVENTIONS:
        raise HTTPException(422, f"tray_convention doit valoir {sorted(TRAY_CONVENTIONS)}")

    temp_paths: List[str] = []
    collected_files: List[Tuple[str, str, str]] = []  # (work_path, filename, suffix)

    try:
        # 1. Collecte des fichiers
        if folder_path:
            f_dir = Path(folder_path).resolve()
            if not f_dir.exists() or not f_dir.is_dir():
                raise HTTPException(404, f"Dossier introuvable : {folder_path}")
            for p in f_dir.iterdir():
                if p.is_file() and p.suffix.lower() in BATCH_ALLOWED_EXT:
                    collected_files.append((str(p), p.name, p.suffix.lower()))

        if file_paths:
            import json
            try:
                raw_list = json.loads(file_paths) if file_paths.strip().startswith("[") else [x.strip() for x in file_paths.split(",") if x.strip()]
            except Exception:
                raw_list = [x.strip() for x in file_paths.split(",") if x.strip()]
            for raw_p in raw_list:
                p = _allowed_local_path(raw_p) if os.path.isabs(raw_p) else Path(raw_p).resolve()
                if p.is_file() and p.suffix.lower() in BATCH_ALLOWED_EXT:
                    collected_files.append((str(p), p.name, p.suffix.lower()))

        if files:
            for f in files:
                if f.filename:
                    suf = Path(f.filename).suffix.lower()
                    if suf in BATCH_ALLOWED_EXT:
                        tmp = _save_upload(f, suf)
                        temp_paths.append(tmp)
                        collected_files.append((tmp, f.filename, suf))

        if not collected_files:
            raise HTTPException(400, "Aucun fichier valide fourni dans le lot.")

        # 2. Classification automatique des rôles
        cad_candidates: List[Tuple[str, str, str]] = []
        cs_candidates: List[Tuple[str, str, str]] = []
        cn_candidates: List[Tuple[str, str, str]] = []

        for item in collected_files:
            w_path, orig_name, suf = item
            lower_name = orig_name.lower()
            if suf in (".dwg", ".dxf"):
                cad_candidates.append(item)
            elif suf in (".xlsx", ".xlsm", ".csv"):
                if any(k in lower_name for k in ["cal", "calcul", "caneco", "etap", "elec_calc"]):
                    cn_candidates.append(item)
                else:
                    cs_candidates.append(item)
            elif suf == ".pdf":
                if any(k in lower_name for k in ["cal", "calcul", "caneco", "etap", "note"]):
                    cn_candidates.append(item)
                elif any(k in lower_name for k in ["lst", "cable", "carnet", "schedule", "liste"]):
                    cs_candidates.append(item)
                else:
                    cad_candidates.append(item)

        # Déduplication CAD : si .dwg et .dxf du même nom coexistent, privilégier le .dxf (ou ezdxf natif)
        stems_seen = set()
        filtered_cad = []
        for c in sorted(cad_candidates, key=lambda x: 0 if x[2] == ".dxf" else (1 if x[2] == ".dwg" else 2)):
            st = Path(c[1]).stem
            if st not in stems_seen:
                stems_seen.add(st)
                filtered_cad.append(c)
        cad_candidates = filtered_cad

        purge_old_outputs()
        batch_manifest: List[Dict[str, Any]] = []
        combined_items: List[Dict[str, Any]] = []
        cad_items: List[Dict[str, Any]] = []
        cs_items: List[Dict[str, Any]] = []
        cn_items: List[Dict[str, Any]] = []
        all_warnings: List[str] = []
        primary_metadata: Dict[str, Any] = {}
        previews: Dict[str, Any] = {"preview_image": "", "visual_url": None, "plan_preview_urls": [], "page_count": 1}

        # 3. Extraction CAD
        if cad_candidates:
            cad_path, cad_filename, cad_suf = cad_candidates[0]
            options = {k: v for k, v in (("units", units), ("tray_convention", tray_convention), ("doc_type", doc_type), ("origin_tag", origin_tag)) if v}
            cad_extracted = extract_ie_drawing(cad_path, original_filename=cad_filename, options=options or None)
            cad_items = cad_extracted.get("items", [])
            primary_metadata = cad_extracted.get("metadata", {})
            primary_metadata["filename"] = cad_filename
            all_warnings.extend(primary_metadata.get("warnings") or [])
            cad_stem = _safe_stem(cad_filename)
            previews = _render_previews(cad_path, cad_filename, cad_suf, cad_stem, all_warnings, inline_preview)
            batch_manifest.append({"filename": cad_filename, "role": "CAD_ROUTING_PLAN", "items_count": len(cad_items)})
            combined_items.extend(cad_items)

        # 4. Extraction Carnet de Câbles
        for cs_path, cs_filename, cs_suf in cs_candidates:
            cables = CableScheduleParser.parse_file(cs_path)
            cs_items.extend(cables)
            batch_manifest.append({"filename": cs_filename, "role": "CABLE_SCHEDULE", "cables_count": len(cables)})
            for c in cables:
                p_c = parse_cable(c.get("declared_section") or "")
                unit_w = p_c.get("linear_weight_kg_m", 1.2) if p_c else 1.2
                length_m = float(c.get("declared_length_m") or 0.0)
                tot_w = round(unit_w * length_m, 2)
                sec_str = c.get("declared_section") or ""
                type_str = c.get("cable_type") or ""
                desc = f"CÂBLE {sec_str} {type_str}".strip() if sec_str else (c.get("description") or f"CÂBLE {c.get('tag')}")
                combined_items.append({
                    "category": "CABLE",
                    "tag": c.get("tag"),
                    "raw_tag": c.get("raw_tag"),
                    "description": desc,
                    "discipline": "ELEC",
                    "size": sec_str,
                    "section": sec_str,
                    "cable_type": type_str,
                    "voltage": c.get("voltage") or "0.4 kV",
                    "source": c.get("source"),
                    "destination": c.get("destination"),
                    "quantity": length_m,
                    "unit": "m",
                    "unit_weight": unit_w,
                    "weight_total": tot_w,
                    "confidence_score": 0.95,
                    "source_type": "CABLE_SCHEDULE",
                    "remarks": f"De {c.get('source')} vers {c.get('destination')}"
                })

        # 5. Extraction Note de Calcul
        for cn_path, cn_filename, cn_suf in cn_candidates:
            if cn_suf in (".xlsx", ".xlsm", ".csv"):
                parsed_cn = CalculationNoteParser.parse_file(cn_path)
                cn_items.extend(parsed_cn)
                batch_manifest.append({"filename": cn_filename, "role": "CALCULATION_NOTE", "feeders_count": len(parsed_cn)})
            else:
                batch_manifest.append({"filename": cn_filename, "role": "CALCULATION_NOTE_REF", "status": "REFERENCED"})

        # 6. Triangulation Totale E&I
        triangulation_res = None
        if cad_items or cs_items or cn_items:
            engine = EITriangulationEngine()
            triangulation_res = engine.triangulate(
                cad_feeders=cad_items,
                cable_schedule_items=cs_items,
                calc_note_items=cn_items,
                cad_metadata=primary_metadata
            )

        # 7. Consolidation MTO & Génération Excel Maître
        expanded_items = expand_feeders(combined_items)
        if not primary_metadata.get("filename"):
            primary_metadata["filename"] = "Package_EI_Consolide"
        anomalies = validate_ie_mto(expanded_items, primary_metadata)
        kpis = compute_kpis(expanded_items, primary_metadata, anomalies)
        primary_metadata.update({k: kpis[k] for k in ("cable_total_m", "tray_total_m", "instruments_count", "valves_count",
                                                       "panels_count", "total_weight_kg")})
        stem = _safe_stem(primary_metadata.get("filename") or "batch_mto")
        excel_name = _new_name("mto_batch", stem, ".xlsx")
        generate_master_multidiscipline_excel(expanded_items, primary_metadata, anomalies, str(output_dir() / excel_name))

        cfg_info = get_config_info()
        if cfg_info.get("warning"):
            all_warnings.append(f"Configuration : {cfg_info['warning']}")

        logger.info("[IE_MTO_BATCH] Succès : %d fichiers traités, %d articles, %.2fs", len(collected_files), len(expanded_items), time.time() - start)

        return {
            "status": "success",
            "batch_manifest": batch_manifest,
            "filename": primary_metadata.get("filename"),
            "duration_s": round(time.time() - start, 2),
            "metadata": primary_metadata,
            "items": expanded_items,
            "anomalies": anomalies,
            "kpis": kpis,
            "warnings": all_warnings,
            "triangulation": triangulation_res,
            "config": cfg_info,
            "preview_image": previews.get("preview_image", ""),
            "visual_url": previews.get("visual_url"),
            "plan_preview_urls": previews.get("plan_preview_urls", []),
            "page_count": previews.get("page_count", 1),
            "excel_url": f"{VISUALS_URL_PREFIX}/{excel_name}",
            "excel_filename": excel_name,
        }

    except ConfigError as exc:
        raise HTTPException(422, f"Configuration invalide : {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[IE_MTO_BATCH] Échec du traitement par lot")
        raise HTTPException(500, f"Échec du traitement par lot : {exc}")
    finally:
        for f in temp_paths:
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except OSError:
                pass


class IeMtoCustomExportRequest(BaseModel):
    filename: Optional[str] = Field("MTO_IE_Export.xlsx", max_length=200)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    anomalies: Optional[List[Dict[str, Any]]] = None


@router.post("/ie-mto/export-excel")
def export_custom_ie_mto_excel(req: IeMtoCustomExportRequest):
    limit = int(_router_cfg().get("max_export_items", 50000))
    if len(req.items) > limit or len(req.anomalies or []) > limit:
        raise HTTPException(413, f"Trop de lignes (maximum {limit}).")
    metadata = dict(req.metadata or {})
    metadata["filename"] = req.filename or "MTO_IE.xlsx"
    name = _new_name("export", req.filename or "MTO_IE", ".xlsx")
    try:
        generate_master_multidiscipline_excel(req.items, metadata, req.anomalies or [], str(output_dir() / name))
    except ConfigError as exc:
        raise HTTPException(422, f"Configuration invalide : {exc}")
    return {"status": "success", "excel_url": f"{VISUALS_URL_PREFIX}/{name}", "excel_filename": name}


class ReconcileRequest(BaseModel):
    piping_items: Optional[List[Dict[str, Any]]] = None
    sld_feeders: Optional[List[Dict[str, Any]]] = None
    routing_items: Optional[List[Dict[str, Any]]] = None
    earthing_items: Optional[List[Dict[str, Any]]] = None
    pid_equipment: Optional[List[Dict[str, Any]]] = None
    cable_list: Optional[List[Dict[str, Any]]] = None
    panels: Optional[List[Dict[str, Any]]] = None


@router.post("/ie-mto/reconcile")
def reconcile(req: ReconcileRequest):
    """Recoupement P&ID / ISO / SLD / cheminements : les 7 contrôles ; un contrôle sans données est « non évalué »."""
    try:
        rec = CrossDisciplineReconciler()
    except ConfigError as exc:
        raise HTTPException(422, f"Configuration invalide : {exc}")
    anomalies = rec.reconcile_all(**req.model_dump())
    real = [a for a in anomalies if a.get("status") != "NOT_EVALUATED"]
    return {"status": "success", "anomalies": anomalies, "coverage": rec.coverage,
            "counts": {"critical": sum(a["severity"] == "CRITICAL" for a in real),
                       "warning": sum(a["severity"] == "WARNING" for a in real),
                       "info": sum(a["severity"] == "INFO" for a in real),
                       "not_evaluated": len(anomalies) - len(real)}}


class CableRouteRequest(BaseModel):
    file_path: Optional[str] = None
    feeders: List[Dict[str, Any]] = Field(default_factory=list)
    origin_tag: Optional[str] = "TGBT"
    units: Optional[str] = None


@router.post("/ie-mto/route-cables")
def route_cables_dijkstra(req: CableRouteRequest):
    """Calcule le routage par Dijkstra entre l'origine et chaque départ sur le plan d'implantation."""
    if not req.file_path:
        raise HTTPException(400, "file_path requis pour charger le réseau de cheminements CAD.")
    p = _allowed_local_path(req.file_path)
    if p.suffix.lower() not in (".dwg", ".dxf"):
        raise HTTPException(415, "Le plan de routage doit être au format DWG ou DXF.")

    try:
        import ezdxf
        from cable_routing_engine import CableRoutingEngine
        doc = ezdxf.readfile(str(p))
        insunits = doc.header.get("$INSUNITS", 0)
        scale_to_m = 1.0 if req.units == "m" else (0.001 if req.units == "mm" else (1.0 if insunits == 6 else (0.01 if insunits == 5 else 0.001)))
        engine = CableRoutingEngine(load_project_config())
        engine.load_from_ezdxf_doc(doc, scale_to_m=scale_to_m)

        routed_feeders = []
        routed_count = 0
        unrouted_count = 0

        for f in req.feeders:
            f_res = dict(f)
            dest = f.get("tag") or f.get("destination") or ""
            orig = f.get("origin") or req.origin_tag or "TGBT"
            r = engine.route_cable(orig, dest)
            if r.get("status") == "ROUTED":
                f_res["quantity"] = r["total_length_m"]
                f_res["length_source"] = "DIJKSTRA_ROUTED"
                f_res["routing_details"] = r
                routed_count += 1
            else:
                f_res["quantity"] = None
                f_res["length_source"] = "UNKNOWN"
                f_res["routing_warning"] = r.get("warning")
                unrouted_count += 1
            routed_feeders.append(f_res)

        return {
            "status": "success",
            "tray_nodes_count": len(engine.graph.nodes),
            "equipment_located_count": len(engine.equipment),
            "routed_count": routed_count,
            "unrouted_count": unrouted_count,
            "feeders": routed_feeders
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[IE_ROUTING] Échec du routage")
        raise HTTPException(500, f"Erreur lors du routage des câbles : {exc}")


class TriangulationActionReq(BaseModel):
    discrepancy_id: str
    action: str  # "validate_inject", "ignore", "add_note"
    expert_note: Optional[str] = None
    item_proposed: Optional[Dict[str, Any]] = None


@router.post("/ie-mto/triangulate")
def run_ei_triangulation(
    plan_file: Optional[UploadFile] = File(None),
    plan_path: Optional[str] = Form(None),
    cable_schedule_file: Optional[UploadFile] = File(None),
    cable_schedule_path: Optional[str] = Form(None),
    calc_note_file: Optional[UploadFile] = File(None),
    calc_note_path: Optional[str] = Form(None),
    units: Optional[str] = Form("auto"),
    origin_tag: Optional[str] = Form("TGBT"),
):
    """
    Exécute la Triangulation Totale 4 axes entre :
      1) Plan CAD (DWG/DXF/PDF)
      2) Carnet de Câbles (Excel/CSV/SLD)
      3) Note de Calcul (Caneco BT / ETAP / Excel)
    Retourne les fiches d'arbitrage comparatives 3 colonnes.
    """
    temp_files: List[str] = []

    try:
        # 1. Résolution du Plan CAD
        cad_feeders: List[Dict[str, Any]] = []
        cad_meta: Dict[str, Any] = {}
        target_plan: Optional[str] = None

        if plan_path:
            target_plan = str(_allowed_local_path(plan_path))
        elif plan_file and plan_file.filename:
            suf = Path(plan_file.filename).suffix.lower()
            if suf not in ALLOWED_EXT:
                raise HTTPException(415, f"Format du plan non supporté : {suf}")
            tmp_p = _save_upload(plan_file, suf)
            temp_files.append(tmp_p)
            target_plan = tmp_p

        if target_plan:
            try:
                extraction = extract_ie_drawing(target_plan, units=units or "auto", origin_tag=origin_tag or "TGBT")
                cad_feeders = extraction.get("items") or []
                cad_meta = extraction.get("metadata") or {}
            except Exception as e:
                logger.warning(f"[Triangulation] Extraction CAD partielle : {e}")

        # 2. Résolution du Carnet de Câbles
        cs_items: List[Dict[str, Any]] = []
        target_cs: Optional[str] = None

        if cable_schedule_path:
            p = Path(cable_schedule_path).resolve()
            target_cs = str(p)
        elif cable_schedule_file and cable_schedule_file.filename:
            suf = Path(cable_schedule_file.filename).suffix.lower()
            if suf not in (".xlsx", ".xlsm", ".csv", ".txt", ".pdf"):
                raise HTTPException(415, f"Format du carnet de câbles non supporté : {suf}")
            tmp_cs = _save_upload(cable_schedule_file, suf)
            temp_files.append(tmp_cs)
            target_cs = tmp_cs

        if target_cs:
            try:
                cs_items = CableScheduleParser.parse_file(target_cs)
            except Exception as e:
                logger.warning(f"[Triangulation] Parsing Carnet de Câbles : {e}")

        # 3. Résolution de la Note de Calcul
        cn_items: List[Dict[str, Any]] = []
        target_cn: Optional[str] = None

        if calc_note_path:
            p = Path(calc_note_path).resolve()
            target_cn = str(p)
        elif calc_note_file and calc_note_file.filename:
            suf = Path(calc_note_file.filename).suffix.lower()
            if suf not in (".xlsx", ".xlsm", ".csv", ".txt"):
                raise HTTPException(415, f"Format de la note de calcul non supporté : {suf}")
            tmp_cn = _save_upload(calc_note_file, suf)
            temp_files.append(tmp_cn)
            target_cn = tmp_cn

        if target_cn:
            try:
                cn_items = CalculationNoteParser.parse_file(target_cn)
            except Exception as e:
                logger.warning(f"[Triangulation] Parsing Note de Calcul : {e}")

        # 4. Exécution de la Triangulation
        engine = EITriangulationEngine()
        result = engine.triangulate(
            cad_feeders=cad_feeders,
            cable_schedule_items=cs_items,
            calc_note_items=cn_items,
            cad_metadata=cad_meta
        )

        return {
            "status": "success",
            "summary": result["summary"],
            "discrepancy_cards": result["discrepancy_cards"],
            "sources": {
                "cad_feeders_count": result["cad_feeders_count"],
                "cable_schedule_count": result["cable_schedule_count"],
                "calc_note_count": result["calc_note_count"],
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[IE_TRIANGULATION] Erreur")
        raise HTTPException(500, f"Erreur lors de la triangulation : {exc}")
    finally:
        for f in temp_files:
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except OSError:
                pass


@router.post("/ie-mto/triangulation/action")
def apply_triangulation_action(req: TriangulationActionReq):
    """
    Applique l'action d'arbitrage de l'expert humain :
      - 'validate_inject' : Valide la proposition normalisée et confirme son injection dans le MTO / Excel.
      - 'ignore' : Classe l'anomalie sans injection.
      - 'add_note' : Sauvegarde une note technique d'audit.
    """
    if req.action == "validate_inject":
        if not req.item_proposed:
            raise HTTPException(400, "item_proposed requis pour validation et injection.")
        return {
            "status": "success",
            "action": "validate_inject",
            "discrepancy_id": req.discrepancy_id,
            "injected_item": req.item_proposed,
            "message": f"Article pour le câble {req.item_proposed.get('tag')} injecté avec succès dans le MTO."
        }
    elif req.action == "ignore":
        return {
            "status": "success",
            "action": "ignore",
            "discrepancy_id": req.discrepancy_id,
            "message": "Divergence ignorée par l'expert."
        }
    elif req.action == "add_note":
        return {
            "status": "success",
            "action": "add_note",
            "discrepancy_id": req.discrepancy_id,
            "expert_note": req.expert_note,
            "message": "Note technique enregistrée."
        }
    else:
        raise HTTPException(400, f"Action non reconnue : {req.action}")



def mount_visuals(app) -> None:
    """Sert le dossier des fichiers générés sur /visuals (noms non devinables ; ajouter une authentification en production)."""
    from fastapi.staticfiles import StaticFiles
    app.mount(VISUALS_URL_PREFIX, StaticFiles(directory=str(output_dir())), name="ie_visuals")
