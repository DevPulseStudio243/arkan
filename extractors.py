# ============================================================
#  COPILOTE D'INGÉNIERIE AUGMENTÉ - Extracteurs multi-format v3.0
#  PDF / Word / Excel / PowerPoint / HTML / DXF avec OCR + Vision
#
#  NOUVEAUTÉS v3.0 :
#  - Vision : qwen2.5vl:7b (spécialisé documents techniques)
#  - PDF vectoriel AutoCAD : reconstitution spatiale 2D (PyMuPDF words)
#  - P&ID scannés : rendu 300 DPI + tiling 2×2
#  - Détection P&ID élargie (contenu + nom de fichier)
#  - Support .html/.htm (plans SVG/HTML)
#  - Support .dxf/.dwg (AutoCAD natif via ezdxf)
#  - Prompts Qwen2.5-VL optimisés pour l'ingénierie Oil & Gas
# ============================================================

import io
import re
import json
import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional

import httpx

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_VISION_MODEL,
    VISION_CACHE_PATH,
    LLM_TIMEOUT,
)

import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

# ── Cache Vision ────────────────────────────────────────────

class SQLiteVisionCache:
    """
    Thread-safe Dict-like wrapper around SQLite vision cache database.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
        self._migrate_json()

    def _init_db(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS vision_cache (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error initializing SQLite vision cache: {e}")

    def _migrate_json(self):
        # The old JSON path is self.db_path with .db replaced by .json
        json_path = self.db_path.replace(".db", ".json")
        if not os.path.exists(json_path):
            return
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if data and isinstance(data, dict):
                with self.lock:
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.executemany(
                        "INSERT OR REPLACE INTO vision_cache (key, value) VALUES (?, ?)",
                        [(k, str(v)) for k, v in data.items()]
                    )
                    conn.commit()
                    conn.close()
                logger.info(f"Successfully migrated {len(data)} entries from old JSON vision cache to SQLite.")
            
            # Rename old json file
            os.rename(json_path, json_path + ".bak")
        except Exception as e:
            logger.error(f"Error migrating JSON vision cache: {e}")

    def __contains__(self, key: str) -> bool:
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM vision_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                conn.close()
                return row is not None
            except Exception:
                return False

    def __getitem__(self, key: str) -> str:
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM vision_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    return row[0]
                raise KeyError(key)
            except Exception as e:
                if isinstance(e, KeyError):
                    raise
                return None

    def __setitem__(self, key: str, value: str):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO vision_cache (key, value) VALUES (?, ?)", (key, value))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error writing to SQLite vision cache: {e}")

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

_vision_cache_instance = None
_vision_cache_lock = threading.Lock()

def _load_vision_cache():
    global _vision_cache_instance
    with _vision_cache_lock:
        if _vision_cache_instance is None:
            _vision_cache_instance = SQLiteVisionCache(VISION_CACHE_PATH)
    return _vision_cache_instance


def _save_vision_cache(cache):
    # Already saved automatically in SQLite, no-op
    pass


# ── Prompts spécialisés pour qwen2.5vl ──────────────────────

_STANDARD_OCR_PROMPT = (
    "You are a precise OCR engine for technical documents. "
    "Extract ALL visible text from this image with 100% accuracy. "
    "Preserve tags, numbers, codes, labels and table data exactly as written. "
    "Return ONLY the raw extracted text. Do NOT add commentary or invent content."
)

_PID_OCR_PROMPT = (
    "You are an expert P&ID/PFD reader for Oil & Gas engineering. "
    "Analyze this technical drawing with maximum precision and extract ALL information "
    "structured under these 6 headings:\n\n"
    "1. EQUIPMENT TAGS & DESCRIPTIONS\n"
    "   List every equipment tag (pumps P-XXX, vessels V-XXX, heat exchangers E-XXX, "
    "compressors C-XXX, filters F-XXX, etc.) with its full description and service.\n\n"
    "2. LINE NUMBERS & PIPING SPECIFICATIONS\n"
    "   List every line number with size, schedule, material, service fluid, and insulation.\n\n"
    "3. INSTRUMENTS & CONTROL LOOPS\n"
    "   List every instrument tag (FT, PT, TT, LT, FIC, PIC, TIC, etc.), "
    "its service, range, and loop number.\n\n"
    "4. TITLE BLOCK & REVISION\n"
    "   Drawing number, title, revision letter/number, date, project name, client, contractor.\n\n"
    "5. NOTES, LEGEND & SPECIFICATIONS\n"
    "   All general notes, legends, material specs, design conditions.\n\n"
    "6. PROCESS CONDITIONS\n"
    "   Design pressure, operating pressure, temperature, flow rates, fluid properties.\n\n"
    "Be 100% faithful to the image. Do NOT invent or assume any data not visible."
)

_AUTOCAD_SPATIAL_PROMPT = (
    "You are an expert at reading AutoCAD vectorial drawings and P&ID schematics. "
    "This image contains fragmented text from an AutoCAD export. "
    "Reconstruct all equipment tags, line numbers, instrument tags, notes and title block data. "
    "Group nearby fragments that form a single tag or label. "
    "Output a clean, structured list of all identified items with their categories. "
    "Do NOT invent content not visible."
)


# ── Détection P&ID améliorée ─────────────────────────────────

_PID_FILENAME_KEYWORDS = [
    "pid", "p&id", "p_id", "pfd", "pfd", "iso", "isometric",
    "drawing", "plan", "schéma", "schema", "diagramme", "diagram",
    "process", "piping", "instrumentation", "flow", "layout",
    "implantation", "p-id", "dwg", "p&d",
]

_PID_CONTENT_PATTERNS = [
    r"\bP-\d{3}[A-Z]?\b",   # Pump tag P-101A
    r"\bV-\d{3}[A-Z]?\b",   # Vessel tag
    r"\bE-\d{3}[A-Z]?\b",   # Heat exchanger
    r"\bFT-\d{3}\b",         # Flow transmitter
    r"\bPT-\d{3}\b",         # Pressure transmitter
    r"\bTT-\d{3}\b",         # Temperature transmitter
    r"\b\d{1,4}\"-.{3,20}\b", # Line size spec like 6"-HCS-1001
    r"\bREV\s*[A-Z]\b",      # Revision block
    r"\bDWG\s*NO\b",         # Drawing number
]


def _is_pid_document(file_path: str, text_sample: str = "") -> bool:
    """Détermine si un document est un P&ID / PFD / plan technique."""
    # 1. Analyse du nom de fichier avec limites de mots pour éviter les faux positifs (comme "planning")
    name = Path(file_path).name.lower()
    name_words = re.split(r'[\s_\-\.\'\(\)]+', name)
    
    for kw in _PID_FILENAME_KEYWORDS:
        if kw in ["pid", "p&id", "p_id", "pfd", "iso", "dwg", "p-id", "p&d"]:
            if kw in name_words:
                return True
        else:
            if kw == "plan":
                if "plan" in name_words or "plans" in name_words:
                    return True
            else:
                if any(word.startswith(kw) for word in name_words):
                    return True

    # 2. Analyse du contenu si disponible (premiers 2000 chars)
    if text_sample:
        for pattern in _PID_CONTENT_PATTERNS:
            if re.search(pattern, text_sample):
                return True
    return False


# ── Reconstitution spatiale 2D (AutoCAD vectoriel) ───────────

def _extract_vectorial_spatial(file_path: str) -> str:
    """
    Reconstitution spatiale 2D pour les PDF vectoriels AutoCAD.
    Utilise les coordonnées (x, y) de chaque mot pour reconstruire
    l'ordre de lecture naturel d'un plan technique.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        all_pages_text = []

        for page_num, page in enumerate(doc):
            # Récupérer les mots avec leurs coordonnées
            words = page.get_text("words")  # [(x0, y0, x1, y1, text, block, line, word)]
            if not words:
                continue

            # Trier par ligne Y (tolérance de 5px) puis par X
            LINE_TOLERANCE = 5.0

            # Regrouper les mots par ligne Y approximative
            lines_dict = {}
            for w in words:
                x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
                if not text.strip():
                    continue
                # Trouver la ligne Y la plus proche (dans la tolérance)
                matched_y = None
                for ky in lines_dict:
                    if abs(ky - y0) <= LINE_TOLERANCE:
                        matched_y = ky
                        break
                if matched_y is None:
                    matched_y = y0
                    lines_dict[matched_y] = []
                lines_dict[matched_y].append((x0, text))

            # Trier les lignes par Y croissant (haut → bas)
            sorted_y_keys = sorted(lines_dict.keys())
            page_lines = []
            for ky in sorted_y_keys:
                # Trier les mots de la ligne par X (gauche → droite)
                words_on_line = sorted(lines_dict[ky], key=lambda w: w[0])

                # Fusionner les fragments très proches (AutoCAD fragmente les tags)
                merged_line = []
                prev_x1 = None
                prev_text = ""
                prev_x0 = None
                for wx0, wtext in words_on_line:
                    if prev_x1 is not None and (wx0 - prev_x1) < 8.0:
                        # Fragments très proches → fusionner sans espace
                        prev_text += wtext
                        prev_x1 = wx0 + len(wtext)  # approximation
                    else:
                        if prev_text:
                            merged_line.append(prev_text)
                        prev_text = wtext
                        prev_x1 = wx0 + len(wtext)
                if prev_text:
                    merged_line.append(prev_text)

                line_text = "  ".join(merged_line)
                if line_text.strip():
                    page_lines.append(line_text)

            if page_lines:
                all_pages_text.append(f"--- Page {page_num + 1} ---\n" + "\n".join(page_lines))

        doc.close()
        return "\n\n".join(all_pages_text)

    except ImportError:
        logger.warning("PyMuPDF non disponible pour la reconstitution spatiale")
        return ""
    except Exception as e:
        logger.error(f"Erreur reconstitution spatiale {file_path}: {e}")
        return ""


# ── Extraction PDF ──────────────────────────────────────────

def extract_pdf(file_path: str) -> dict:
    """
    Extrait le texte d'un PDF avec détection intelligente du type :
    - PDF vectoriel AutoCAD → reconstitution spatiale 2D
    - P&ID scanné → OCR 300 DPI + tiling + qwen2.5vl
    - PDF texte normal → extraction directe PyMuPDF/PyPDF2
    """
    try:
        from PyPDF2 import PdfReader
        
        # 1. Analyse préliminaire rapide des dimensions et du texte de garde
        reader = PdfReader(file_path)
        num_pages = len(reader.pages)
        
        page_width = 0.0
        page_height = 0.0
        if num_pages > 0:
            try:
                box = reader.pages[0].mediabox
                page_width = float(box.width)
                page_height = float(box.height)
            except Exception:
                pass

        sample_text = ""
        if num_pages > 0:
            try:
                sample_text = reader.pages[0].extract_text() or ""
            except Exception:
                pass
                
        # 2. Détermination de la nature du document (P&ID / plan technique / dessin d'ingénierie)
        is_pid_by_name_or_content = _is_pid_document(file_path, text_sample=sample_text[:2000])
        is_large_drawing = (page_width > 1000.0 or page_height > 1000.0)
        is_pid = is_pid_by_name_or_content or is_large_drawing
        
        logger.info(f"Analyse PDF: {file_path} - Pages: {num_pages} - Dims: {page_width:.1f}x{page_height:.1f} pt - Plan d'ingénierie détecté: {is_pid} (Nom/Contenu: {is_pid_by_name_or_content}, Grand Format: {is_large_drawing})")
        
        # 3. Routage
        import config
        # Si c'est un plan d'ingénierie, on contourne Docling pour utiliser le pipeline de vision / spatial spécialisé
        if getattr(config, "DOCLING_ENABLED", False) and not is_pid:
            try:
                from docling_extractor import get_docling_extractor
                ext = get_docling_extractor()
                if ext.disponible():
                    logger.info(f"Extraction Docling primaire pour document standard: {file_path}")
                    res = ext.extract_pdf(file_path)
                    if res and res.get("text"):
                        text = res["text"]
                        if res.get("tables"):
                            text = "\n\n=== TABLES EXTRAITES ===\n" + "\n\n".join(res["tables"]) + "\n\n=== FIN TABLES ===\n\n" + text
                        
                        return {
                            "text": text,
                            "pages": res["metadata"].get("pages", 1),
                            "format": "pdf",
                            "source": file_path,
                            "is_pid": False,
                        }
            except Exception as e:
                logger.warning(f"Échec extraction Docling (fallback vers chaîne standard): {e}")

        # --- Pipeline d'extraction standard / plan ---
        full_text = []
        page_lengths = []
        
        # Tentative d'utilisation de PyMuPDF (fitz) d'abord
        use_fitz = False
        try:
            import fitz
            use_fitz = True
        except ImportError:
            pass
            
        if use_fitz:
            logger.info(f"Utilisation de PyMuPDF (fitz) pour l'extraction de texte standard de {file_path}")
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    text = page.get_text("text") or ""
                    full_text.append(text)
                    page_lengths.append(len(text.strip()))
                doc.close()
            except Exception as fe:
                logger.warning(f"Échec d'ouverture PyMuPDF: {fe}, fallback PyPDF2")
                use_fitz = False
                
        if not use_fitz:
            logger.info(f"Utilisation de PyPDF2 pour l'extraction de texte standard de {file_path}")
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                full_text.append(text)
                page_lengths.append(len(text.strip()))

        combined = "\n".join(full_text)
        coherent_words = [w for w in combined.split() if len(w) >= 3 and w.isalpha()]
        avg_words_per_page = len(coherent_words) / max(num_pages, 1)

        # Détection AutoCAD vectoriel : texte présent mais fragmenté
        is_autocad_vectorial = (
            0 < avg_words_per_page < 20 and
            len(combined.strip()) > 100 and
            num_pages > 0
        )

        # Détection PDF scanné ou hybride (très peu de texte par page ou pages blanches/scannées)
        has_blank_pages = num_pages > 1 and any(l < 40 for l in page_lengths)
        is_scanned = (len(combined.strip()) < 100 or has_blank_pages) and num_pages > 0

        # Traitement spécialisé pour les plans d'ingénierie
        if is_pid:
            spatial_text = _extract_vectorial_spatial(file_path)
            
            if not spatial_text or len(spatial_text.strip()) < 150 or is_scanned:
                logger.info(f"Plan d'ingénierie scanné ou sans texte vectoriel suffisant → OCR vision avec {OLLAMA_VISION_MODEL}")
                ocr_text = _ocr_pdf_pages(file_path, reader, is_pid=True)
                if ocr_text:
                    combined = ocr_text
                elif spatial_text:
                    combined = spatial_text
            else:
                logger.info(f"Plan d'ingénierie vectoriel traité par reconstitution spatiale: {file_path}")
                combined = spatial_text
                
        # Traitement pour les documents standards (sans Docling)
        else:
            if is_autocad_vectorial:
                logger.info(f"PDF vectoriel AutoCAD détecté: {file_path} → reconstitution spatiale 2D")
                spatial_text = _extract_vectorial_spatial(file_path)
                if spatial_text and len(spatial_text) > len(combined) and not has_blank_pages:
                    combined = spatial_text
                else:
                    logger.info(f"Fallback OCR vision AutoCAD/Hybride pour: {file_path}")
                    ocr_text = _ocr_pdf_pages(file_path, reader, is_pid=False)
                    if ocr_text:
                        combined = ocr_text

            elif is_scanned:
                logger.info(f"PDF scanné détecté: {file_path} → tentative OCR vision {OLLAMA_VISION_MODEL}")
                ocr_text = _ocr_pdf_pages(file_path, reader, is_pid=False)
                if ocr_text:
                    combined = ocr_text

        return {
            "text": combined,
            "pages": num_pages,
            "format": "pdf",
            "source": file_path,
            "is_pid": is_pid,
        }

    except Exception as e:
        logger.error(f"Erreur extraction PDF {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "pdf", "source": file_path, "error": str(e)}


def _ocr_pdf_pages(file_path: str, reader, is_pid: bool = False) -> str:
    """
    OCR des pages PDF via PyMuPDF (rendu image haute résolution) + qwen2.5vl.
    - P&ID : 300 DPI + tiling 2x2 pour les grands plans
    - Standard : 200 DPI
    """
    # Vérifier le cache
    cache = _load_vision_cache()
    try:
        file_hash = hashlib.md5(Path(file_path).read_bytes()).hexdigest()
    except Exception:
        file_hash = hashlib.md5(file_path.encode()).hexdigest()

    cache_key = f"{file_hash}_{'pid' if is_pid else 'std'}"
    if cache_key in cache:
        logger.info(f"Cache vision trouvé pour {file_path}")
        return cache[cache_key]

    texts = []
    # Résolution : 200 DPI pour P&ID (bon compromis qualité / VRAM GPU), 150 DPI pour les autres
    dpi = 200 if is_pid else 150
    zoom = dpi / 72.0

    # Méthode 1 : PyMuPDF (fitz) — rendu page entière haute résolution
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        max_pages = min(len(doc), 15)

        for i in range(max_pages):
            try:
                page_cache_key = f"{file_hash}_p{i+1}_{'pid' if is_pid else 'std'}"
                if page_cache_key in cache:
                    logger.info(f"Cache vision trouvé pour {file_path} - Page {i+1}")
                    texts.append(cache[page_cache_key])
                    continue

                page = doc[i]
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Tiling pour les grands plans P&ID (> 2000px de large ou de haut)
                if is_pid and (pix.width > 2000 or pix.height > 2000):
                    logger.info(f"P&ID grand format ({pix.width}x{pix.height}px) → tiling 2×2")
                    tile_texts = _tile_and_ocr(img_bytes, pix.width, pix.height, is_pid=True)
                    if tile_texts:
                        page_text = f"--- Page {i+1} (tiled) ---\n" + "\n".join(tile_texts)
                        texts.append(page_text)
                        cache[page_cache_key] = page_text
                        _save_vision_cache(cache)
                        continue

                b64_image = base64.b64encode(img_bytes).decode("utf-8")
                text = _call_vision_model_b64(b64_image, f"Page {i+1}", is_pid=is_pid)
                if text and len(text.strip()) > 10:
                    page_text = f"--- Page {i+1} ---\n{text}"
                    texts.append(page_text)
                    cache[page_cache_key] = page_text
                    _save_vision_cache(cache)
                    logger.info(f"OCR page {i+1}/{max_pages} ({dpi} DPI): {len(text)} chars (Sauvegardé au cache)")
            except Exception as e:
                logger.warning(f"Erreur OCR page {i+1}: {e}")
                continue

        doc.close()

    except ImportError:
        logger.warning("PyMuPDF non installé — fallback PyPDF2")
        try:
            max_pages = min(len(reader.pages), 10)
            for i in range(max_pages):
                try:
                    page = reader.pages[i]
                    resources = page.get("/Resources")
                    if resources is None:
                        continue
                    if hasattr(resources, "get_object"):
                        resources = resources.get_object()
                    xobject = resources.get("/XObject")
                    if xobject is None:
                        continue
                    if hasattr(xobject, "get_object"):
                        xobject = xobject.get_object()
                    for obj_name in xobject:
                        xobj = xobject[obj_name]
                        if hasattr(xobj, "get_object"):
                            xobj = xobj.get_object()
                        subtype = xobj.get("/Subtype")
                        if hasattr(subtype, "get_object"):
                            subtype = subtype.get_object()
                        if str(subtype) == "/Image":
                            text = _call_vision_model(xobj, f"Page {i+1}", is_pid=is_pid)
                            if text:
                                texts.append(f"--- Page {i+1} ---\n{text}")
                except Exception as e:
                    logger.warning(f"Erreur OCR fallback page {i+1}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Erreur OCR fallback: {e}")

    except Exception as e:
        logger.error(f"Erreur OCR PyMuPDF: {e}")

    result = "\n\n".join(texts)

    if result:
        cache[cache_key] = result
        _save_vision_cache(cache)

    return result


def _tile_and_ocr(img_bytes: bytes, width: int, height: int, is_pid: bool = True) -> list:
    """
    Découpe une grande image en grille 2×2 avec 10% de recouvrement
    et applique l'OCR sur chaque pavé. Idéal pour les plans A0/A1.
    Chaque tuile est redimensionnée à max 1280px pour éviter les OOM GPU.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        overlap_x = int(width * 0.10)
        overlap_y = int(height * 0.10)
        half_w = width // 2
        half_h = height // 2

        tiles = [
            (0, 0, half_w + overlap_x, half_h + overlap_y),                         # Haut-gauche
            (half_w - overlap_x, 0, width, half_h + overlap_y),                     # Haut-droite
            (0, half_h - overlap_y, half_w + overlap_x, height),                    # Bas-gauche
            (half_w - overlap_x, half_h - overlap_y, width, height),                # Bas-droite
        ]

        MAX_TILE_DIM = 1280  # Limite pour éviter les OOM GPU

        tile_texts = []
        for idx, (x0, y0, x1, y1) in enumerate(tiles):
            tile_img = img.crop((x0, y0, x1, y1))

            # Redimensionner la tuile si trop grande pour le GPU
            tw, th = tile_img.size
            if tw > MAX_TILE_DIM or th > MAX_TILE_DIM:
                scale = min(MAX_TILE_DIM / tw, MAX_TILE_DIM / th)
                tile_img = tile_img.resize((int(tw * scale), int(th * scale)), Image.LANCZOS)
                logger.info(f"Tuile {idx} redimensionnée: {tw}x{th} → {tile_img.size[0]}x{tile_img.size[1]}")

            tile_buffer = io.BytesIO()
            tile_img.save(tile_buffer, format="PNG", optimize=True)
            tile_b64 = base64.b64encode(tile_buffer.getvalue()).decode("utf-8")

            label = ["Haut-gauche", "Haut-droite", "Bas-gauche", "Bas-droite"][idx]
            text = _call_vision_model_b64(tile_b64, f"Zone {label}", is_pid=is_pid)
            if text and len(text.strip()) > 5:
                tile_texts.append(f"[Zone {label}]\n{text}")

        return tile_texts

    except Exception as e:
        logger.warning(f"Tiling échoué: {e}")
        return []


# Modèle vision léger utilisé en fallback quand le modèle principal manque de VRAM
_VISION_FALLBACK_MODEL = "qwen2.5vl:3b"


def _call_vision_model_b64(b64_image: str, context: str = "", is_pid: bool = False) -> str:
    """
    Appelle qwen2.5vl (ou le modèle vision configuré) avec une image en base64.
    Sélectionne le prompt adapté au type de document.
    Tente le modèle principal puis bascule sur le modèle léger (3b) en cas d'erreur.
    """
    prompt = _PID_OCR_PROMPT if is_pid else _STANDARD_OCR_PROMPT

    # Essayer d'abord le modèle principal, puis le fallback léger
    models_to_try = [OLLAMA_VISION_MODEL]
    if _VISION_FALLBACK_MODEL != OLLAMA_VISION_MODEL:
        models_to_try.append(_VISION_FALLBACK_MODEL)

    for model in models_to_try:
        try:
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [b64_image],
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                        "num_ctx": 4096,
                        "top_p": 1.0,
                    },
                },
                timeout=LLM_TIMEOUT,
            )

            if response.status_code == 200:
                result = response.json().get("response", "")
                if result and len(result.strip()) > 5:
                    if model != OLLAMA_VISION_MODEL:
                        logger.info(f"Vision fallback {model} réussi pour {context}")
                    return result
            else:
                logger.warning(f"Vision {model} erreur HTTP {response.status_code} pour {context} — tentative suivante")

        except Exception as e:
            logger.warning(f"Vision {model} exception pour {context}: {e} — tentative suivante")

    logger.error(f"Tous les modèles vision ont échoué pour {context}")
    return ""


def _call_vision_model(image_data, context: str = "", is_pid: bool = False) -> str:
    """Appelle le modèle vision Ollama pour l'OCR (fallback PyPDF2)."""
    try:
        if isinstance(image_data, bytes):
            b64_image = base64.b64encode(image_data).decode("utf-8")
        elif hasattr(image_data, "get_data"):
            b64_image = base64.b64encode(image_data.get_data()).decode("utf-8")
        else:
            return ""

        return _call_vision_model_b64(b64_image, context, is_pid=is_pid)

    except Exception as e:
        logger.error(f"Erreur appel vision model: {e}")
    return ""


# ── Extraction Word ─────────────────────────────────────────

def extract_docx(file_path: str) -> dict:
    """Extrait le texte d'un fichier Word (.docx), y compris les tableaux et en-têtes."""
    try:
        from docx import Document

        doc = Document(file_path)
        paragraphs = []

        # En-têtes et pieds de page
        for section in doc.sections:
            for para in section.header.paragraphs:
                if para.text.strip():
                    paragraphs.append(f"[HEADER] {para.text}")

        # Corps du document
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)

        # Tableaux
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))

        return {
            "text": "\n".join(paragraphs),
            "pages": len(paragraphs) // 40 + 1,
            "format": "docx",
            "source": file_path,
        }

    except Exception as e:
        logger.error(f"Erreur extraction DOCX {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "docx", "source": file_path, "error": str(e)}


# ── Extraction Excel ────────────────────────────────────────

def extract_xlsx(file_path: str) -> dict:
    """Extrait le texte d'un fichier Excel (.xlsx)."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(file_path, data_only=True)
        sheets_text = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                sheets_text.append(f"=== Feuille: {sheet_name} ===\n" + "\n".join(rows))

        return {
            "text": "\n\n".join(sheets_text),
            "pages": len(wb.sheetnames),
            "format": "xlsx",
            "source": file_path,
        }

    except Exception as e:
        logger.error(f"Erreur extraction XLSX {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "xlsx", "source": file_path, "error": str(e)}


# ── Extraction PowerPoint ───────────────────────────────────

def extract_pptx(file_path: str) -> dict:
    """Extrait le texte d'un fichier PowerPoint (.pptx)."""
    try:
        from pptx import Presentation

        prs = Presentation(file_path)
        slides_text = []

        for i, slide in enumerate(prs.slides):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            texts.append(para.text.strip())
                if shape.has_table:
                    for row in shape.table.rows:
                        cells = [c.text.strip() for c in row.cells if c.text.strip()]
                        if cells:
                            texts.append(" | ".join(cells))
            if texts:
                slides_text.append(f"--- Slide {i+1} ---\n" + "\n".join(texts))

        return {
            "text": "\n\n".join(slides_text),
            "pages": len(prs.slides),
            "format": "pptx",
            "source": file_path,
        }

    except Exception as e:
        logger.error(f"Erreur extraction PPTX {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "pptx", "source": file_path, "error": str(e)}


# ── Extraction HTML (plans SVG/HTML) ────────────────────────

def extract_html(file_path: str) -> dict:
    """
    Extrait le texte d'un fichier HTML, y compris les éléments SVG
    (plans d'implantation, PFD générés, diagrammes).
    """
    try:
        from bs4 import BeautifulSoup

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")

        texts = []

        # Titre
        title = soup.find("title")
        if title:
            texts.append(f"[TITRE] {title.get_text(strip=True)}")

        # En-têtes
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            t = tag.get_text(strip=True)
            if t:
                texts.append(f"[SECTION] {t}")

        # Tableaux
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if any(cells):
                    texts.append(" | ".join(c for c in cells if c))

        # Éléments SVG (plans techniques SVG)
        for svg_text in soup.find_all(["text", "tspan"]):
            t = svg_text.get_text(strip=True)
            if t and len(t) > 1:
                texts.append(t)

        # Paragraphes et divs
        for tag in soup.find_all(["p", "li", "td", "div"]):
            t = tag.get_text(strip=True)
            if t and len(t) > 5 and t not in texts:
                texts.append(t)

        # Dédupliquer en préservant l'ordre
        seen = set()
        unique_texts = []
        for t in texts:
            if t not in seen:
                seen.add(t)
                unique_texts.append(t)

        combined = "\n".join(unique_texts)

        is_pid = _is_pid_document(file_path, text_sample=combined[:2000])

        return {
            "text": combined,
            "pages": 1,
            "format": "html",
            "source": file_path,
            "is_pid": is_pid,
        }

    except Exception as e:
        logger.error(f"Erreur extraction HTML {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "html", "source": file_path, "error": str(e)}


# ── Extraction DXF/DWG (AutoCAD natif) ──────────────────────

def extract_dxf(file_path: str) -> dict:
    """
    Extrait toutes les entites textuelles et le MTO d'un fichier DXF/DWG AutoCAD pour ARKAN.
    - Format DWG binaire : conversion ultra-rapide en DXF via le moteur autonome LibreDWG
    - Extraction isometrique MTO specialisee (dwg_iso_extractor) si plan isometrique
    - Extraction vectorielle ezdxf par calque pour tout autre plan (P&ID, PFD, implantation)
    """
    p = Path(file_path)
    suffix = p.suffix.lower()

    # 1. Si le fichier est un plan isometrique DWG/DXF, extraire directement la nomenclature MTO
    try:
        from dwg_iso_extractor import process_dwg_isometric
        iso_res = process_dwg_isometric(file_path)
        if iso_res.get("status") == "success" and iso_res.get("formatted_text") and (iso_res.get("bom_items") or iso_res.get("spools")):
            logger.info("Plan isometrique detecte (%s) : extraction directe de la nomenclature MTO", p.name)
            return {
                "text": iso_res["formatted_text"],
                "pages": 1,
                "format": suffix.replace(".", ""),
                "source": file_path,
                "is_pid": False,
                "is_isometric": True,
                "metadata": iso_res.get("metadata", {}),
                "bom_items": iso_res.get("bom_items", []),
                "mto": iso_res.get("bom_items", []),
                "spools": iso_res.get("spools", []),
                "total_pipe_length_m": iso_res.get("total_pipe_length_m", 0.0),
                "total_steel_weight_kg": iso_res.get("total_steel_weight_kg", 0.0)
            }
    except Exception as e_iso:
        logger.debug("Extraction isometrique directe ignoree pour %s: %s", p.name, e_iso)

    # 2. Si le fichier est un DWG binaire standard, convertir en DXF via dwg_converter
    actual_dxf_path = file_path
    if suffix == ".dwg":
        try:
            from dwg_converter import ensure_dxf
            actual_dxf_path = ensure_dxf(file_path)
            logger.info("Conversion DWG -> DXF reussie pour %s -> %s", p.name, Path(actual_dxf_path).name)
        except Exception as e_dwg:
            logger.warning("Conversion DWG vers DXF impossible (%s) pour %s, repli vision", e_dwg, p.name)
            return _extract_dwg_via_vision(file_path)

    # 3. Extraction vectorielle calque par calque via ezdxf
    try:
        import ezdxf

        doc = ezdxf.readfile(actual_dxf_path)
        msp = doc.modelspace()

        layers_text: dict = {}

        def add_to_layer(layer: str, text_val: str):
            text_val = text_val.strip()
            if not text_val:
                return
            layer_clean = layer.strip() or "DEFAULT"
            layers_text.setdefault(layer_clean, [])
            if text_val not in layers_text[layer_clean]:
                layers_text[layer_clean].append(text_val)

        for entity in msp:
            try:
                layer = entity.dxf.layer if hasattr(entity.dxf, "layer") else "DEFAULT"

                if entity.dxftype() == "TEXT":
                    add_to_layer(layer, entity.dxf.text)

                elif entity.dxftype() == "MTEXT":
                    raw = entity.plain_mtext() if hasattr(entity, "plain_mtext") else str(entity.dxf.text)
                    clean = re.sub(r"\\[A-Za-z;]", " ", raw)
                    clean = re.sub(r"\{[^}]*\}", "", clean)
                    add_to_layer(layer, clean.strip())

                elif entity.dxftype() == "ATTDEF":
                    add_to_layer(layer, entity.dxf.text)

                elif entity.dxftype() == "INSERT":
                    for attrib in getattr(entity, "attribs", []):
                        add_to_layer(layer, attrib.dxf.text)

            except Exception:
                continue

        output_lines = [f"=== Plan AutoCAD : {p.name} ==="]
        for layer_name, items in sorted(layers_text.items()):
            output_lines.append(f"\n[Calque: {layer_name}]")
            output_lines.extend(f"  {item}" for item in items)

        combined = "\n".join(output_lines)
        is_pid = _is_pid_document(file_path, text_sample=combined[:2000])

        return {
            "text": combined,
            "pages": 1,
            "format": suffix.replace(".", ""),
            "source": file_path,
            "is_pid": is_pid,
        }

    except ImportError:
        logger.warning("ezdxf non installe : extraction DXF/DWG indisponible")
        return {"text": "", "pages": 0, "format": suffix.replace(".", ""), "source": file_path,
                "error": "ezdxf non installe"}

    except Exception as e:
        logger.warning("Erreur lecture DXF (%s) : %s", p.name, e)
        return _extract_dwg_via_vision(file_path)


def _extract_dwg_via_vision(file_path: str) -> dict:
    """
    Fallback pour les DWG binaires : tente de les lire via PyMuPDF
    (qui supporte certains DWG via son moteur interne), sinon retourne
    un message informatif avec les métadonnées disponibles.
    """
    try:
        import fitz

        # PyMuPDF peut ouvrir certains fichiers DWG via son moteur
        doc = fitz.open(file_path)
        texts = []
        for i in range(min(len(doc), 5)):
            page = doc[i]
            # Essai extraction texte direct
            page_text = page.get_text("text")
            if page_text.strip():
                texts.append(f"--- Page {i+1} ---\n{page_text}")
            else:
                # Rendu image + vision
                mat = fitz.Matrix(2.0, 2.0)  # 144 DPI
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                vision_text = _call_vision_model_b64(b64, f"Page {i+1}", is_pid=True)
                if vision_text:
                    texts.append(f"--- Page {i+1} ---\n{vision_text}")
        doc.close()

        combined = "\n\n".join(texts)
        is_pid = _is_pid_document(file_path, text_sample=combined[:2000])

        return {
            "text": combined if combined else f"[DWG binaire - fichier: {Path(file_path).name}]",
            "pages": 1,
            "format": "dwg",
            "source": file_path,
            "is_pid": is_pid,
        }

    except Exception as e2:
        logger.warning(f"DWG vision fallback échoué pour {file_path}: {e2}")
        # Retourner au moins le nom du fichier comme métadonnée
        return {
            "text": f"[Plan AutoCAD DWG : {Path(file_path).name} — conversion requise]",
            "pages": 0,
            "format": "dwg",
            "source": file_path,
            "is_pid": _is_pid_document(file_path),
        }



# ── Extraction texte brut ───────────────────────────────────

def extract_text(file_path: str) -> dict:
    """Extrait le texte d'un fichier texte brut."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return {
            "text": text,
            "pages": 1,
            "format": "txt",
            "source": file_path,
        }
    except Exception as e:
        logger.error(f"Erreur extraction TXT {file_path}: {e}")
        return {"text": "", "pages": 0, "format": "txt", "source": file_path, "error": str(e)}


# ── Dispatcher ──────────────────────────────────────────────

EXTRACTORS = {
    # Documents bureautiques
    ".pdf":  extract_pdf,
    ".docx": extract_docx,
    ".doc":  extract_docx,
    ".xlsx": extract_xlsx,
    ".xls":  extract_xlsx,
    ".pptx": extract_pptx,
    ".ppt":  extract_pptx,
    # Texte brut
    ".txt":  extract_text,
    ".csv":  extract_text,
    ".log":  extract_text,
    ".xml":  extract_text,
    ".json": extract_text,
    # Plans HTML/SVG (PFD, P&ID générés)
    ".html": extract_html,
    ".htm":  extract_html,
    # Plans AutoCAD natifs
    ".dxf":  extract_dxf,
    ".dwg":  extract_dxf,   # DWG → ezdxf (si fichier DXF-compatible)
}


def extract_file(file_path: str) -> dict:
    """
    Extrait le contenu d'un fichier en choisissant l'extracteur approprié.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    extractor = EXTRACTORS.get(suffix)
    if extractor is None:
        logger.warning(f"Format non supporté: {suffix} ({file_path})")
        return {
            "text": "",
            "pages": 0,
            "format": suffix,
            "source": file_path,
            "error": f"Format non supporté: {suffix}",
        }

    logger.info(f"Extraction: {file_path} (format: {suffix})")
    return extractor(file_path)
