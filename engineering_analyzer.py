
import pdfplumber
import re
import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns Oil & Gas pour les tags techniques
PATTERNS = {
    "tag_instrument": r"\b([A-Z]{2,3}-\d{3,5}[A-Z]?)\b",  # ex: PT-101, XV-202A
    "tag_equipement": r"\b([A-Z]{1,2}-\d{3,4})\b",        # ex: P-101, V-102
    "tag_ligne": r"\b(\d{1,2}\"-?[A-Z]{1,3}-?\d{4,5})\b", # ex: 10"-HC-1001
    "tag_boucle": r"\b(L?IC-\d{3,4})\b",                  # ex: LIC-101, IC-202
}

class EngineeringAnalyzer:
    """Outil d'analyse detaillee pour les documents techniques Oil & Gas (P&IDs, ISOs, Data Sheets)."""

    def analyze_pdf(self, file_path):
        """Analyse un PDF technique pour extraire les tags, les tableaux et la structure."""
        if not os.path.exists(file_path):
            return {"error": f"Fichier non trouve : {file_path}"}

        results = {
            "filename": os.path.basename(file_path),
            "total_pages": 0,
            "tags_found": {},
            "tables": [],
            "summary": ""
        }

        try:
            with pdfplumber.open(file_path) as pdf:
                results["total_pages"] = len(pdf.pages)
                
                all_text = ""
                for i, page in enumerate(pdf.pages):
                    # 1. Extraction du texte
                    text = page.extract_text() or ""
                    all_text += text + "\n"

                    # 2. Extraction des tableaux (Data Sheets, Listes d'instruments)
                    tables = page.extract_tables()
                    for table in tables:
                        # Nettoyer le tableau (enlever les None et les chaines vides)
                        clean_table = [[str(cell).strip() if cell else "" for cell in row] for row in table]
                        if any(any(row) for row in clean_table):
                            results["tables"].append({
                                "page": i + 1,
                                "data": clean_table
                            })

                # 3. Recherche des tags techniques via Regex
                for category, pattern in PATTERNS.items():
                    matches = re.findall(pattern, all_text)
                    if matches:
                        results["tags_found"][category] = list(set(matches))

                # 4. Generer un resume structure pour l'Agent
                results["summary"] = self._generate_summary(results)
                
            return results

        except Exception as e:
            logger.error(f"Erreur lors de l'analyse technique de {file_path}: {e}")
            return {"error": str(e)}

    def _generate_summary(self, results):
        """Cree une description textuelle exploitable par le raisonnement de l'agent."""
        summary = f"Analyse technique de {results['filename']} :\n"
        summary += f"- Pages : {results['total_pages']}\n"
        
        if results['tags_found']:
            summary += "- Tags detectes :\n"
            for cat, tags in results['tags_found'].items():
                summary += f"  * {cat}: {', '.join(tags[:20])}{'...' if len(tags)>20 else ''}\n"
        
        if results['tables']:
            summary += f"- Tableaux detectes : {len(results['tables'])} (utile pour les listes de materiels ou specifications)\n"
            # Apercu du premier tableau
            first_table = results['tables'][0]['data']
            if len(first_table) > 1:
                summary += f"  * Apercu tableau page {results['tables'][0]['page']} : {first_table[0][:5]}...\n"
                
        return summary

def get_engineering_analyzer():
    return EngineeringAnalyzer()
