"""
Service OCR & Extraction Documentaire Ultra-Rapide pour ARKAN DCC.
Combine l'extraction vectorielle native PyMuPDF (< 15ms) et un fallback raster Tesseract.
Extrait le texte brut, les zones de cartouche et indexe le contenu dans SQLite FTS5.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("arkan.dcc.ocr")

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False
    logger.warning("[OCR] PyMuPDF (fitz) non disponible.")

try:
    import pytesseract
    from PIL import Image
    PYTESSERACT_AVAILABLE = True
    # Détection automatique de l'exécutable Tesseract sous Windows si non présent sur PATH
    common_tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\MSI\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
    ]
    for p in common_tesseract_paths:
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            break
except ImportError:
    PYTESSERACT_AVAILABLE = False


def extract_document_text(file_path: str, max_pages: int = 5) -> Dict[str, Any]:
    """
    Extrait le texte intégral et repère les mots-clés du cartouche d'un fichier technique (PDF ou Image).
    Retourne un dictionnaire structuré prêt pour l'indexation FTS5 et la validation DOT-09.
    """
    path = Path(file_path)
    if not path.exists():
        return {
            "success": False,
            "error": f"Fichier introuvable : {file_path}",
            "text": "",
            "extracted_chars": 0,
            "method": "NONE"
        }

    ext = path.suffix.lower()

    # 1. Traitement des fichiers PDF via PyMuPDF (Ultra-rapide)
    if ext == ".pdf":
        if not FITZ_AVAILABLE:
            return {"success": False, "error": "PyMuPDF non installé", "text": "", "method": "NONE"}

        try:
            doc = fitz.open(str(path))
            full_text_pages: List[str] = []
            total_pages = len(doc)
            pages_to_read = min(total_pages, max_pages)

            for page_num in range(pages_to_read):
                page = doc[page_num]
                text = page.get_text("text")
                if text.strip():
                    full_text_pages.append(text.strip())

            extracted_text = "\n\n--- PAGE BREAK ---\n\n".join(full_text_pages)
            doc.close()

            if extracted_text.strip():
                return {
                    "success": True,
                    "text": extracted_text,
                    "extracted_chars": len(extracted_text),
                    "pages_analyzed": pages_to_read,
                    "total_pages": total_pages,
                    "method": "PYMUPDF_VECTORIAL",
                    "cartouche_metadata": _parse_cartouche_hints(extracted_text)
                }

            # Si le PDF est un scan pur (0 texte extrait), tentative OCR raster si pytesseract disponible
            if PYTESSERACT_AVAILABLE:
                try:
                    doc = fitz.open(str(path))
                    page = doc[0]
                    pix = page.get_pixmap(dpi=150)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_text = pytesseract.image_to_string(img, lang="fra+eng")
                    doc.close()
                    if ocr_text.strip():
                        return {
                            "success": True,
                            "text": ocr_text.strip(),
                            "extracted_chars": len(ocr_text),
                            "pages_analyzed": 1,
                            "total_pages": total_pages,
                            "method": "PYTESSERACT_RASTER",
                            "cartouche_metadata": _parse_cartouche_hints(ocr_text)
                        }
                except Exception as t_err:
                    logger.debug("[OCR] Fallback Tesseract échoué (binaire non présent ou erreur) : %s", t_err)

            return {
                "success": True,
                "text": "",
                "extracted_chars": 0,
                "pages_analyzed": pages_to_read,
                "total_pages": total_pages,
                "method": "PDF_SCAN_NO_TEXT",
                "cartouche_metadata": {}
            }

        except Exception as e:
            logger.error("[OCR] Erreur extraction PyMuPDF sur %s : %s", file_path, e)
            return {"success": False, "error": str(e), "text": "", "method": "ERROR"}

    # 2. Traitement des fichiers Images (PNG, JPG, TIFF) via Tesseract
    elif ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff"]:
        if PYTESSERACT_AVAILABLE:
            try:
                img = Image.open(str(path))
                text = pytesseract.image_to_string(img, lang="fra+eng")
                return {
                    "success": True,
                    "text": text.strip(),
                    "extracted_chars": len(text),
                    "pages_analyzed": 1,
                    "total_pages": 1,
                    "method": "PYTESSERACT_IMAGE",
                    "cartouche_metadata": _parse_cartouche_hints(text)
                }
            except Exception as e:
                return {"success": False, "error": f"OCR image impossible : {e}", "text": "", "method": "IMAGE_ERROR"}
        return {"success": False, "error": "Moteur OCR Tesseract non configuré pour les images raster", "text": "", "method": "NONE"}

    return {"success": False, "error": f"Format non supporté pour OCR : {ext}", "text": "", "method": "UNSUPPORTED"}


def _parse_cartouche_hints(text: str) -> Dict[str, str]:
    """
    Détecte par heuristique les éléments de cartouche (Doc Number, Révision, Titre, Client) dans le texte extrait.
    """
    hints = {}
    upper = text.upper()

    # Détection révision
    rev_match = re.search(r'(?:R[ÉE]VISION|REV\.?|INDICE)\s*[:=]?\s*([A-Z0-9]{1,3})\b', upper)
    if rev_match:
        hints["detected_revision"] = rev_match.group(1)

    # Détection mentions Sonatrach / Client
    if "SONATRACH" in upper:
        hints["detected_client"] = "SONATRACH"
    elif "CLIENT" in upper:
        hints["detected_client"] = "CLIENT"

    # Détection code d'approbation ou statut cartouche
    for st in ["IFR", "IFA", "IFC", "AS-BUILT", "AS BUILT", "APPROVED"]:
        if re.search(rf'\b{st}\b', upper):
            hints["detected_status"] = st
            break

    return hints
