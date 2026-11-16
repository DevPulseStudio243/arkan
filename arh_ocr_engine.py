"""
arh_ocr_engine.py - Moteur d'OCR Ultra-Performant PaddleOCR / RapidOCR pour ARKAN
----------------------------------------------------------------------------------
Fournit une extraction OCR rapide et structurée pour les documents ARH scannés,
les certificats de conformité, PV d'épreuve hydrostatique et fiches techniques.
"""

import io
import os
import logging
from typing import Dict, Any, List, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger("arh_ocr_engine")

_OCR_ENGINE_INSTANCE = None

def get_ocr_engine():
    """Initialise et retourne le moteur OCR PaddleOCR (via RapidOCR ONNX)."""
    global _OCR_ENGINE_INSTANCE
    if _OCR_ENGINE_INSTANCE is not None:
        return _OCR_ENGINE_INSTANCE

    try:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE_INSTANCE = RapidOCR()
        logger.info("[ARKAN-OCR] Moteur PaddleOCR (RapidOCR PP-OCRv4 ONNX) initialisé avec succès.")
        return _OCR_ENGINE_INSTANCE
    except ImportError:
        logger.warning("[ARKAN-OCR] rapidocr_onnxruntime non disponible, tentative pytesseract...")
        try:
            import pytesseract
            # BUG FIX #9 : configurer le chemin de l'exécutable tesseract sur Windows
            import platform
            if platform.system() == "Windows":
                import os
                tesseract_paths = [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                    os.getenv("TESSERACT_CMD", ""),
                ]
                for tp in tesseract_paths:
                    if tp and os.path.isfile(tp):
                        pytesseract.pytesseract.tesseract_cmd = tp
                        logger.info("[ARKAN-OCR] Tesseract trouvé : %s", tp)
                        break
            _OCR_ENGINE_INSTANCE = "pytesseract"
            return _OCR_ENGINE_INSTANCE
        except ImportError:
            # BUG FIX #8 : alerte explicite au lieu d'un fallback silencieux
            logger.warning("[ARKAN-OCR] Aucun moteur OCR disponible (rapidocr, pytesseract). Les documents scannés ne seront pas analysés.")
            _OCR_ENGINE_INSTANCE = "vision_fallback"
            return _OCR_ENGINE_INSTANCE
    except Exception as e:
        logger.error(f"[ARKAN-OCR] Erreur initialisation OCR: {e}")
        return None


def extract_ocr_from_image(img_input) -> str:
    """
    Extrait le texte lisible d'une image (PIL Image, bytes ou numpy array).
    Retourne une chaîne de texte propre avec sauts de ligne réordonnés.
    """
    engine = get_ocr_engine()
    if engine is None:
        return ""

    try:
        if isinstance(img_input, bytes):
            img_np = np.array(Image.open(io.BytesIO(img_input)))
        elif isinstance(img_input, Image.Image):
            img_np = np.array(img_input)
        elif isinstance(img_input, np.ndarray):
            img_np = img_input
        else:
            return ""

        if hasattr(engine, '__call__'):
            # RapidOCR (PaddleOCR ONNX)
            results, _ = engine(img_np)
            if not results:
                return ""
            # results est une liste de [bbox, text, confidence]
            lines = []
            for item in results:
                if len(item) >= 2 and item[1]:
                    txt = str(item[1]).strip()
                    try:
                        conf = float(item[2]) if len(item) >= 3 else 1.0
                    except Exception:
                        conf = 1.0
                    if len(txt) > 0 and conf > 0.3:
                        lines.append(txt)
            return "\n".join(lines)

        elif engine == "pytesseract":
            import pytesseract
            pil_img = Image.fromarray(img_np) if isinstance(img_np, np.ndarray) else img_input
            return pytesseract.image_to_string(pil_img, lang="fra+eng")

        elif engine == "vision_fallback":
            # BUG FIX #8 : cas explicitement géré — aucun moteur OCR disponible
            # On retourne vide mais on en informe le caller une fois via le logger
            logger.debug("[ARKAN-OCR] vision_fallback actif - extraction OCR indisponible.")
            return ""

    except Exception as e:
        logger.error(f"[ARKAN-OCR] Erreur extraction image: {e}")
        return ""

    return ""


def extract_ocr_coords_from_image(img_input) -> List[Dict[str, Any]]:
    """
    Extrait les textes et leurs rectangles de coordonnées d'une image.
    Retourne une liste de {"text": ..., "bbox": [xmin, ymin, xmax, ymax]}.
    """
    engine = get_ocr_engine()
    if engine is None:
        return []

    try:
        if isinstance(img_input, bytes):
            img_np = np.array(Image.open(io.BytesIO(img_input)))
        elif isinstance(img_input, Image.Image):
            img_np = np.array(img_input)
        elif isinstance(img_input, np.ndarray):
            img_np = img_input
        else:
            return []

        if hasattr(engine, '__call__'):
            # RapidOCR (PaddleOCR ONNX)
            results, _ = engine(img_np)
            if not results:
                return []
            
            blocks = []
            for item in results:
                if len(item) >= 2 and item[1]:
                    txt = str(item[1]).strip()
                    try:
                        conf = float(item[2]) if len(item) >= 3 else 1.0
                    except Exception:
                        conf = 1.0
                    if len(txt) > 0 and conf > 0.3:
                        bbox = item[0]  # list of 4 points: [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
                        xs = [pt[0] for pt in bbox]
                        ys = [pt[1] for pt in bbox]
                        blocks.append({
                            "text": txt,
                            "bbox": [min(xs), min(ys), max(xs), max(ys)]
                        })
            return blocks

        elif engine == "pytesseract":
            import pytesseract
            pil_img = Image.fromarray(img_np) if isinstance(img_np, np.ndarray) else img_input
            # Utilise image_to_data pour récupérer les boîtes de coordonnées sous forme de dict
            data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT, lang="fra+eng")
            blocks = []
            n_boxes = len(data['level'])
            for i in range(n_boxes):
                txt = str(data['text'][i]).strip()
                if txt:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    blocks.append({
                        "text": txt,
                        "bbox": [float(x), float(y), float(x + w), float(y + h)]
                    })
            return blocks

    except Exception as e:
        logger.error(f"[ARKAN-OCR] Erreur extraction coordonnées image: {e}")
        return []

    return []


def ocr_pdf_document(pdf_path: str, max_pages: int = 30, dpi: int = 300) -> str:
    """
    Rend chaque page d'un PDF scanné en haute résolution (300 DPI)
    et applique PaddleOCR (RapidOCR) pour extraire le texte complet.
    """
    if not os.path.exists(pdf_path):
        return ""

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("[ARKAN-OCR] PyMuPDF (fitz) absent pour le rendu PDF.")
        return ""

    extracted_pages = []

    try:
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages)

        for i in range(total_pages):
            page = doc[i]
            # Matrice de zoom pour 300 DPI (72 DPI * 4.1667 = 300 DPI)
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            img_bytes = pix.tobytes("png")
            page_text = extract_ocr_from_image(img_bytes)

            if page_text and len(page_text.strip()) > 10:
                extracted_pages.append(f"--- PAGE {i+1} (OCR) ---\n{page_text}")

        doc.close()
    except Exception as e:
        logger.error(f"[ARKAN-OCR] Erreur OCR sur le PDF {pdf_path}: {e}")

    return "\n\n".join(extracted_pages)
