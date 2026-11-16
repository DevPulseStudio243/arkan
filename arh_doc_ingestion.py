"""
arh_doc_ingestion.py
====================
Module d'ingestion et de segmentation multi-pages pour dossiers ARH.

Capacités :
  1. Segmentation multi-pages avec préservation stricte des numéros de page réels.
  2. Classification automatique des pages par chapitre réglementaire ARH :
     - PART_3_MATIERE  : Certificats EN 10204 3.1, chimie C/Mn, essais Charpy, NACE
     - PART_4_EPREUVES : PV d'épreuve hydrostatique, diagrammes pression-temps
     - PART_5_CALCULS  : Notes de calcul mécanique (ASME UG-27, Barlow, API)
     - PART_8_SOUDAGE  : WPS, PQR, WOPQ, rapports PWHT
     - PART_10_ITP     : Inspection & Test Plan, points Hold/Witness ARH, CND
     - PART_11_ATEX    : Certificats ATEX/IECEx, boucles SIL, fiches sécurité
  3. Extraction contextuelle ciblée pour éliminer le bruit sur les gros dossiers.
"""

import re
import os
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("ARHDocIngestion")
logger.setLevel(logging.INFO)

SECTION_KEYWORDS = {
    "PART_3_MATIERE": [
        "CERTIFICAT MATIERE", "EN 10204", "TYPE 3.1", "MILL TEST", "MTR",
        "COMPOSITION CHIMIQUE", "ANALYSE CHIMIQUE", "ESSAI DE TRACTION",
        "ESSAI DE RESILIENCE", "CHARPY", "COULEE", "HEAT NO", "HEAT NUMBER",
        "NACE MR0175", "HIC", "SSCC", "DURETE", "HARDNESS"
    ],
    "PART_4_EPREUVES": [
        "EPREUVE HYDROSTATIQUE", "HYDROSTATIC TEST", "PRESSION D EPREUVE",
        "TEST PRESSURE", "ENREGISTREUR DE PRESSION", "MANOMETRE ETALONNE",
        "PV D EPREUVE", "HOLD TIME", "DUREE DE MAINTIEN", "CALANDRE",
        "TUBE SIDE", "SHELL SIDE", "CORPS DE VANNE", "SHELL TEST"
    ],
    "PART_5_CALCULS": [
        "NOTE DE CALCUL", "DESIGN CALCULATION", "PRESSION DE CALCUL",
        "DESIGN PRESSURE", "PMA", "PMS", "ASME UG-27", "BARLOW",
        "SURPAISSEUR DE CORROSION", "CORROSION ALLOWANCE", "CONTRAINTE ADMISSIBLE",
        "ALLOWABLE STRESS", "EFFICACITE DE JOINT", "JOINT EFFICIENCY",
        "EPAISSEUR MINIMALE", "MINIMUM REQUIRED THICKNESS"
    ],
    "PART_8_SOUDAGE": [
        "WPS", "PQR", "DESCRIPTIF DE MODE OPERATOIRE", "QUALIFICATION SOUDEUR",
        "WPQ", "WOPQ", "ASME SECTION IX", "METAL D APPORT", "ELECTRODE",
        "PWHT", "TRAITEMENT THERMIQUE APRES SOUDAGE", "RECUIT DE DETENSION",
        "DIAGRAMME TEMPERATURE TEMPS"
    ],
    "PART_10_ITP": [
        "ITP", "PLAN D INSPECTION", "INSPECTION AND TEST PLAN", "POINT D ARRET",
        "HOLD POINT", "WITNESS POINT", "SURVEILLANCE", "ORGANISME TIERS",
        "TPI", "CND", "NDE", "RADIOGRAPHIE", "ULTRASONS", "RESSUAGE",
        "MAGNETOSCOPIE", "CONTROLE NON DESTRUCTIF", "ASME SECTION V"
    ],
    "PART_11_ATEX": [
        "ATEX", "IECEX", "ZONE 1", "ZONE 2", "SECURITE INTRINSEQUE",
        "ANTIDEFLAGRANT", "EX D", "EX IA", "EX E", "SIL", "SIL 2", "SIL 3",
        "IEC 61508", "IEC 61511", "CERTIFICAT DE CONFORMITE ATEX"
    ]
}


class ARHDocPage:
    def __init__(self, page_num: int, text: str, source_file: str = "Dossier ARH"):
        self.page_num = page_num
        self.text = text.strip()
        self.source_file = source_file
        self.sections: List[str] = self._classify_sections()

    def _classify_sections(self) -> List[str]:
        tu = self.text.upper()
        detected = []
        for sec_id, keywords in SECTION_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in tu)
            if count >= 1:
                detected.append(sec_id)
        return detected if detected else ["GENERAL"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_num": self.page_num,
            "text": self.text,
            "source_file": self.source_file,
            "sections": self.sections,
            "char_count": len(self.text)
        }


class ARHDocumentIngestion:
    @classmethod
    def parse_text_with_page_markers(cls, raw_text: str, filename: str = "Dossier Technique") -> List[ARHDocPage]:
        page_pattern = re.compile(r'(?:[-=]{3,}\s*PAGE\s*(\d+)\s*[-=]{3,}|(?:^|\n)PAGE\s*(\d+)\s*[:\-\n]|\x0c)', re.IGNORECASE)
        splits = page_pattern.split(raw_text)
        pages: List[ARHDocPage] = []

        if len(splits) <= 1:
            lines = raw_text.split('\n')
            current_page_lines = []
            current_page_num = 1
            current_len = 0

            for line in lines:
                current_page_lines.append(line)
                current_len += len(line) + 1
                if current_len >= 1400:
                    page_text = '\n'.join(current_page_lines)
                    pages.append(ARHDocPage(current_page_num, page_text, filename))
                    current_page_lines = []
                    current_page_num += 1
                    current_len = 0

            if current_page_lines:
                page_text = '\n'.join(current_page_lines)
                pages.append(ARHDocPage(current_page_num, page_text, filename))
        else:
            i = 0
            page_num_auto = 1
            while i < len(splits):
                chunk = splits[i]
                if chunk is None:
                    i += 1
                    continue
                if chunk.strip().isdigit():
                    page_num_auto = int(chunk.strip())
                    i += 1
                    if i < len(splits):
                        content = splits[i]
                        if content and content.strip():
                            pages.append(ARHDocPage(page_num_auto, content, filename))
                else:
                    if chunk.strip():
                        pages.append(ARHDocPage(page_num_auto, chunk, filename))
                        page_num_auto += 1
                i += 1

        if not pages:
            pages.append(ARHDocPage(1, raw_text, filename))

        logger.info("[Ingestion] '%s' découpé en %d page(s)", filename, len(pages))
        return pages

    @classmethod
    def get_section_text(cls, pages: List[ARHDocPage], section_name: str) -> Tuple[str, List[int]]:
        matching_pages = [p for p in pages if section_name in p.sections or "GENERAL" in p.sections]
        if not matching_pages:
            matching_pages = pages[:3]

        combined_text = "\n\n".join([f"--- [PAGE {p.page_num}] ---\n{p.text}" for p in matching_pages])
        page_nums = [p.page_num for p in matching_pages]
        return combined_text, page_nums

    @classmethod
    def compile_evidence_locator(cls, pages: List[ARHDocPage], search_term: str) -> Optional[Dict[str, Any]]:
        st_clean = search_term.upper().strip()
        for p in pages:
            tu = p.text.upper()
            if st_clean in tu:
                lines = [l.strip() for l in p.text.split('\n') if st_clean in l.upper()]
                quote = lines[0] if lines else search_term
                return {
                    "page": p.page_num,
                    "quote": quote[:140],
                    "source_file": p.source_file
                }
        return None
