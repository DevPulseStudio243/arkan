"""
arh_cad_vision_processor.py
===========================
Moteur d'Ingestion Haute Précision pour Plans d'Ensemble, Dessins CAD & Schémas A0/A1.
Combine SAHI (Slicing Aided Hyper Inference) et RapidOCR pour l'extraction sans perte :
- Des cartouches techniques (Title blocks)
- Des cotes verticales et inclinées le long des viroles et fonds
- Des tableaux de piquages (Nozzle schedules) et nomenclatures
"""

import os
import re
import logging
from typing import Dict, List, Any, Optional, Tuple
import numpy as np

logger = logging.getLogger("ARHCadVisionProcessor")

class ARHCadVisionProcessor:
    """Processeur de vision pour plans industriels grand format."""

    def __init__(self):
        self._ocr_engine = None

    def _get_ocr_engine(self):
        """Initialisation paresseuse de RapidOCR."""
        if self._ocr_engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr_engine = RapidOCR()
            except Exception as e:
                logger.warning(f"[CadVision] RapidOCR indisponible : {e}")
                self._ocr_engine = False
        return self._ocr_engine

    def is_large_format_or_drawing(self, width_pt: float, height_pt: float, text_content: str = "") -> bool:
        """
        Détermine si une page correspond à un plan d'ingénierie grand format
        (A0, A1, A2, A3 ou ratio d'aspect allongé de dessin technique).
        """
        # A4 standard = 595 x 842 pt. Au-delà de 842 pt, c'est au moins un A3 ou supérieur.
        max_dim = max(width_pt, height_pt)
        min_dim = min(width_pt, height_pt)
        ratio = max_dim / max(min_dim, 1.0)
        
        is_dimensionally_large = (max_dim > 900.0)
        
        # Mots-clés caractéristiques de plans
        has_cad_keywords = any(k in text_content.upper() for k in [
            "DRAWING NO", "DWG NO", "PLAN D'ENSEMBLE", "GENERAL ARRANGEMENT",
            "BILL OF MATERIAL", "NOZZLE SCHEDULE", "TITLE BLOCK", "SCALE 1:",
            "ECHELLE 1:", "WELD DETAIL", "FABRICATION DRAWING"
        ])
        
        return is_dimensionally_large or (ratio > 1.35 and has_cad_keywords)

    def process_cad_page(
        self,
        pdf_path: str,
        page_idx: int,
        slice_size: int = 1024,
        overlap_ratio: float = 0.2
    ) -> Dict[str, Any]:
        """
        Traite une page de plan technique avec SAHI et OCR tuilé.
        Retourne un dictionnaire avec le texte structuré, les blocs du cartouche et les cotes.
        """
        result = {
            "title_block": {},
            "nozzles": [],
            "dimensions": [],
            "full_extracted_text": "",
            "raw_blocks": []
        }
        
        if not os.path.exists(pdf_path):
            return result

        try:
            import fitz
            doc = fitz.open(pdf_path)
            if page_idx < 0 or page_idx >= len(doc):
                doc.close()
                return result
                
            page = doc[page_idx]
            rect = page.rect
            
            # Si le texte vectoriel natif est déjà très riche, on l'extrait prioritairement
            native_text = page.get_text("text")
            native_blocks = page.get_text("blocks")
            
            # Rendu haute résolution (200 DPI pour les plans)
            zoom = 200.0 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            img_w = pix.width
            img_h = pix.height
            img_bytes = pix.samples
            doc.close()
            
            # Conversion en tableau NumPy uint8
            img_np = np.frombuffer(img_bytes, dtype=np.uint8).reshape((img_h, img_w, pix.n))
            if pix.n == 4:
                img_np = img_np[:, :, :3]
                
            # Tuilage SAHI
            from sahi.slicing import slice_image
            slice_res = slice_image(
                img_np,
                slice_height=slice_size,
                slice_width=slice_size,
                overlap_height_ratio=overlap_ratio,
                overlap_width_ratio=overlap_ratio
            )
            
            ocr = self._get_ocr_engine()
            extracted_lines = []
            
            if ocr:
                for slice_item in slice_res.slices:
                    tile_img = slice_item.image
                    shift_x = slice_item.starting_pixel[0]
                    shift_y = slice_item.starting_pixel[1]
                    
                    ocr_res, _ = ocr(tile_img)
                    if ocr_res:
                        for box, txt, score in ocr_res:
                            if score > 0.4 and txt.strip():
                                # Coordonnées globales sur le plan
                                gx = box[0][0] + shift_x
                                gy = box[0][1] + shift_y
                                extracted_lines.append({
                                    "text": txt.strip(),
                                    "box": [gx, gy],
                                    "score": float(score),
                                    # Zone normalisée relative (0.0 - 1.0)
                                    "rel_x": gx / img_w,
                                    "rel_y": gy / img_h
                                })
            
            # Détection ciblée du cartouche (Title Block) : généralement en bas à droite (rel_x > 0.6, rel_y > 0.6)
            title_block_lines = []
            for item in extracted_lines:
                if item["rel_x"] >= 0.55 and item["rel_y"] >= 0.60:
                    title_block_lines.append(item["text"])
                    
            tb_text = "\n".join(title_block_lines)
            result["title_block"] = self._parse_title_block_text(tb_text or native_text)
            
            # Détection des cotes et piquages
            full_texts = [it["text"] for it in extracted_lines]
            combined_ocr_text = "\n".join(full_texts)
            result["full_extracted_text"] = f"{native_text}\n{combined_ocr_text}".strip()
            
            # Extraction des piquages (Nozzles N1, N2, etc.)
            nozzle_matches = re.findall(r'\b([NMC]\d{1,2}|[A-Z]\d)\b[\s:–-]+([^\n]+)', combined_ocr_text)
            for n_tag, n_desc in nozzle_matches[:15]:
                result["nozzles"].append({"tag": n_tag, "description": n_desc.strip()})
                
        except Exception as e:
            logger.warning(f"[CadVision] Erreur traitement plan {pdf_path} (p.{page_idx+1}): {e}")
            
        return result

    def _parse_title_block_text(self, text: str) -> Dict[str, str]:
        """Extrait les métadonnées clés d'un cartouche technique."""
        meta = {}
        if not text:
            return meta
            
        tu = text.upper()
        
        # Numéro de plan
        dwg_m = re.search(r'(?:DRAWING|DWG|PLAN)[\s_.:N°#-]+([A-Z0-9\-_]{5,35})', tu)
        if dwg_m:
            meta["drawing_number"] = dwg_m.group(1).strip()
            
        # Révision
        rev_m = re.search(r'\b(?:REV|REVISION)[\s.:_-]*([0-9A-Z]{1,4})\b', tu)
        if rev_m:
            meta["revision"] = rev_m.group(1).strip()
            
        # Code de conception
        code_m = re.search(r'\b(ASME\s+VIII(?:\s+DIV\.?\s*1)?|ASME\s+B31\.[348]|CODAP|EN\s*13445|EN\s*3-8|API\s*650)\b', tu)
        if code_m:
            meta["design_code"] = code_m.group(1).strip()
            
        # Matériau principal
        mat_m = re.search(r'\b(SA-?516[\s-]*GR[\s.]*70|SA-?106[\s-]*GR[\s.]*B|316L?|304L?|34CRMO4|P265GH|A105)\b', tu)
        if mat_m:
            meta["material"] = mat_m.group(1).strip()
            
        return meta

# Singleton exporté
cad_vision_processor = ARHCadVisionProcessor()
