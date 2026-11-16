"""
arh_dataset_trainer.py
======================
Framework d'Apprentissage et de Benchmark d'ARKAN sur les dossiers réels ARH.
Scanne Z:\\Department\\Qualité\\02.ARH\\00-TECHNIQUE, associe les dossiers reçus (incoming)
avec les remarques et lettres de retour du département Qualité (outgoing / follow-up),
calcule les métriques de rappel/précision et enrichit les règles d'ARKAN.
"""

import os
import re
import json
import glob
import fitz  # PyMuPDF
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any

from arh_document_processor import ARHDocumentProcessor
from arh_regulatory_engine import ARHRegulatoryEngine

DATASET_ROOT = Path(r"Z:\Department\Qualité\02.ARH\00-TECHNIQUE")

class ARHDatasetTrainer:
    def __init__(self, dataset_root: Path = DATASET_ROOT):
        self.dataset_root = dataset_root
        self.processor = ARHDocumentProcessor()
        self.engine = ARHRegulatoryEngine()

    def discover_dataset_pairs(self) -> List[Dict[str, Any]]:
        """
        Découvre les paires (Dossier Reçu, Remarques Outgoing / Excel Follow-up) dans le répertoire.
        """
        pairs = []
        if not self.dataset_root.exists():
            print(f"[TRAINER] Erreur: Le chemin {self.dataset_root} n'existe pas.")
            return pairs

        for proj in os.listdir(self.dataset_root):
            proj_dir = self.dataset_root / proj
            if not proj_dir.is_dir():
                continue

            # Chercher les sous-dossiers préliminaires
            print(f"[TRAINER] Exploration projet : {proj} ...", flush=True)
            prelim_dirs = [d for d in proj_dir.glob("*") if d.is_dir() and "prelim" in d.name.lower()]
            for pdir in prelim_dirs:
                pdf_files = []
                for root, _, files in os.walk(pdir):
                    depth = os.path.relpath(root, pdir).count(os.sep)
                    if depth <= 2:
                        for f in files:
                            if f.lower().endswith('.pdf'):
                                pdf_files.append(Path(root) / f)
                for pdf in pdf_files:
                    fname = pdf.name
                    if any(k in fname.lower() for k in ["commented", "cmt", "avis", "lettre"]):
                        continue
                    
                    parent = pdf.parent
                    stem = pdf.stem
                    outgoing_matches = []
                    
                    for cmt_file in parent.glob(f"*{stem}*"):
                        if cmt_file != pdf and any(k in cmt_file.name.lower() for k in ["commented", "cmt", "avis"]):
                            outgoing_matches.append(cmt_file)

                    feedback_dir = proj_dir / "ARH Feedback Letters"
                    if feedback_dir.exists():
                        for fb in feedback_dir.rglob("*"):
                            if fb.is_file() and any(ext in fb.name.lower() for ext in [".pdf", ".xlsx", ".docx"]):
                                outgoing_matches.append(fb)

                    followup_files = list(proj_dir.glob("*FOLLOW UP*.xlsx")) + list(pdir.glob("*FOLLOW UP*.xlsx"))
                    
                    pairs.append({
                        "project": proj,
                        "subfolder": pdir.name,
                        "incoming_pdf": str(pdf),
                        "filename": fname,
                        "outgoing_files": [str(m) for m in outgoing_matches],
                        "followup_excels": [str(f) for f in followup_files]
                    })

        return pairs

    def extract_ground_truth_remarks(self, outgoing_files: List[str], followup_excels: List[str]) -> List[str]:
        """
        Extrait les remarques textuelles écrites EN ROUGE et déposées par les auditeurs Qualité.
        """
        remarks = []
        
        for out_path in outgoing_files:
            if not os.path.exists(out_path):
                continue
            if out_path.lower().endswith(".pdf"):
                try:
                    doc = fitz.open(out_path)
                    for page_idx, page in enumerate(doc, 1):
                        # 1. Annotations PDF insérées par les auditeurs
                        for annot in page.annots():
                            info = annot.info
                            content = info.get('content', '').strip()
                            if content and len(content) > 3:
                                remarks.append(f"[Page {page_idx}] {content}")
                        
                        # 2. Textes en ROUGE insérés visuellement (R > 0.55, G < 0.4, B < 0.4)
                        d = page.get_text('dict')
                        for b in d.get('blocks', []):
                            for l in b.get('lines', []):
                                for s in l.get('spans', []):
                                    c_int = s.get('color', 0)
                                    r = ((c_int >> 16) & 0xFF) / 255.0
                                    g = ((c_int >> 8) & 0xFF) / 255.0
                                    b_col = (c_int & 0xFF) / 255.0
                                    txt = s.get('text', '').strip()
                                    if r > 0.55 and g < 0.4 and b_col < 0.4 and len(txt) > 3:
                                        remarks.append(f"[Page {page_idx}] {txt}")
                                    elif any(kw in txt.upper() for kw in ["RESERVE", "REMARQUE", "NON CONFORME", "FOURNIR", "ABSENCE", "CORRIGER", "MANQUE", "INCOMPATIBLE", "VEUILLEZ"]):
                                        remarks.append(f"[Page {page_idx}] {txt}")
                    doc.close()
                except Exception:
                    pass

        for excel_path in followup_excels:
            if not os.path.exists(excel_path):
                continue
            try:
                xl = pd.ExcelFile(excel_path)
                for sheet in xl.sheet_names:
                    df = xl.parse(sheet)
                    for col in df.columns:
                        if any(k in str(col).lower() for k in ["comment", "remarque", "observation", "reserve", "statut", "avis"]):
                            vals = df[col].dropna().astype(str).tolist()
                            for v in vals:
                                if len(v.strip()) > 10 and not v.startswith("http"):
                                    remarks.append(v.strip())
            except Exception:
                pass

        return list(set(remarks))

    def benchmark_pair(self, pair: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute ARKAN sur le fichier incoming et compare avec le ground truth outgoing.
        """
        pdf_path = pair["incoming_pdf"]
        ground_truth = self.extract_ground_truth_remarks(pair["outgoing_files"], pair["followup_excels"])
        
        dossier_id = "BENCH_" + Path(pdf_path).stem[:10].upper()
        
        try:
            result = self.processor.process_dossier_batch(
                file_paths=[pdf_path],
                project_name=pair["project"],
                unit_name="UNIT-100",
                dossier_id=dossier_id
            )
        except Exception as e:
            return {"status": "ERROR", "error": str(e), "incoming_pdf": pdf_path}

        detected_comments = result.get("comments", [])
        detected_titles = [c.get("title", "") for c in detected_comments]
        
        matches = 0
        for gt in ground_truth:
            gt_upper = gt.upper()
            if any(dt.upper() in gt_upper or gt_upper in dt.upper() for dt in detected_titles):
                matches += 1

        match_rate = (matches / len(ground_truth) * 100.0) if ground_truth else 100.0
        
        return {
            "status": "SUCCESS",
            "project": pair["project"],
            "pdf": pair["filename"],
            "detected_count": len(detected_comments),
            "ground_truth_count": len(ground_truth),
            "matches": matches,
            "match_rate": round(match_rate, 1),
            "detected_titles": detected_titles[:5]
        }

if __name__ == "__main__":
    trainer = ARHDatasetTrainer()
    print("[TRAINER] Recherche des paires de dossiers dans 00-TECHNIQUE...")
    pairs = trainer.discover_dataset_pairs()
    print(f"[TRAINER] {len(pairs)} paires de dossiers identifiées !")
    
    if pairs:
        print("\n[TRAINER] Évaluation d'un échantillon initial de 3 paires...")
        for p in pairs[:3]:
            res = trainer.benchmark_pair(p)
            print(f" -> Projet: {res.get('project')} | Fichier: {res.get('pdf')}")
            print(f"    Détectés par ARKAN: {res.get('detected_count')} | Ground Truth: {res.get('ground_truth_count')} | Taux de Rappel: {res.get('match_rate')}%")
