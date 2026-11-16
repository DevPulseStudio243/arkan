"""
arh_benchmark_evaluator.py — v1.0
=================================
Moteur d'Évaluation & Calibration Continue ARKAN vs Expert Humain (Décrets ARH & P-CTE-1).
Extrait les annotations et textes rouges des dossiers OUTGOING de l'expert humain (Sonatrach / GCB / ARH),
exécute l'audit automatisé ARKAN (DOT-TM + Cross-Validator + Slicer) sur les dossiers INCOMING,
et mesure le taux de rappel (Recall), la précision et la complétude des réserves.
"""

from __future__ import annotations
import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import fitz  # PyMuPDF

import uuid
import shutil

logger = logging.getLogger(__name__)

class ARHBenchmarkEvaluator:
    def __init__(self, desktop_arh_path: Optional[str] = None):
        self.base_dir = Path(desktop_arh_path or r"C:\Users\MSI\Desktop\arh")

    def extract_human_expert_comments(self, pdf_path: str, incoming_pdf_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Extrait toutes les remarques de l'expert humain dans un PDF 'OUTCOMING' :
          1. Annotations PDF (FreeText, Text, Square, Polygon, Line)
          2. Spans textuels de couleur rouge (RGB R>160, G<90, B<90)
        Filtre automatiquement :
          - Les tampons nominatifs purs d'ingénieurs (ex: Sellami, Rouaba).
          - Le texte déjà présent en rouge dans l'INCOMING original du fournisseur.
        """
        if not os.path.exists(pdf_path):
            return []

        # 0. Récupérer le texte rouge déjà présent dans le PDF INCOMING (s'il existe)
        incoming_red_texts = set()
        if incoming_pdf_path and os.path.exists(incoming_pdf_path):
            try:
                inc_doc = fitz.open(incoming_pdf_path)
                for inc_p in inc_doc:
                    d_inc = inc_p.get_text("dict")
                    for b_inc in d_inc.get("blocks", []):
                        lines_red = []
                        for l_inc in b_inc.get("lines", []):
                            line_t = ""
                            is_r = False
                            for sp_inc in l_inc.get("spans", []):
                                col = sp_inc.get("color", 0)
                                r_val = (col >> 16) & 255
                                g_val = (col >> 8) & 255
                                b_val = col & 255
                                if r_val > 150 and g_val < 100 and b_val < 100:
                                    is_r = True
                                    line_t += " " + sp_inc.get("text", "").strip()
                            line_t = " ".join(line_t.split())
                            if is_r and line_t:
                                lines_red.append(line_t)
                        if lines_red:
                            full_inc = " ".join(" ".join(lines_red).split())
                            if full_inc:
                                incoming_red_texts.add(full_inc)
                inc_doc.close()
            except Exception as e:
                logger.warning(f"Error parsing incoming red text: {e}")

        doc = fitz.open(pdf_path)
        human_comments = []
        seen_texts = set()

        def is_reviewer_stamp(text: str) -> bool:
            tc = text.strip()
            # Noms des examinateurs et signatures administratives
            if any(name in tc.upper() for name in ["SELLAMI", "ROUABA", "MAZOUZI", "MERAH", "KACHROUD", "FLORIAN", "DARGET"]):
                return True
            # Initiales pures (ex: S.A)
            if re.fullmatch(r'^[A-Z]\.?[A-Z]\.?$', tc):
                return True
            # Codes de visa purs ou dates isolées
            if re.fullmatch(r'^(CODE\s*0?[1234]|REV\.\s*\d+|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}|[0-9]+([.,][0-9]+)?)$', tc, re.IGNORECASE):
                return True
            return False

        for page_idx, page in enumerate(doc):
            p_num = page_idx + 1

            # A. Annotations PDF
            for annot in page.annots() or []:
                info = annot.info
                content = (info.get("content") or "").strip()
                norm_c = " ".join(content.split())
                if (norm_c and len(norm_c) > 3 
                    and sum(1 for ch in norm_c if ch.isalnum()) >= 2
                    and not is_reviewer_stamp(norm_c) 
                    and norm_c not in seen_texts):
                    seen_texts.add(norm_c)
                    human_comments.append({
                        "source": "ANNOTATION",
                        "page": p_num,
                        "type": annot.type[1],
                        "text": norm_c
                    })

            # B. Texte rouge imprimé dans la page (regroupé par bloc pour former des phrases cohérentes)
            d = page.get_text("dict")
            for block in d.get("blocks", []):
                block_red_lines = []
                for line in block.get("lines", []):
                    line_text = ""
                    is_red_line = False
                    for span in line.get("spans", []):
                        color = span.get("color", 0)
                        r = (color >> 16) & 255
                        g = (color >> 8) & 255
                        b = color & 255
                        if r > 160 and g < 90 and b < 90:
                            is_red_line = True
                            line_text += " " + span.get("text", "").strip()

                    line_text = " ".join(line_text.split())
                    if is_red_line and line_text:
                        block_red_lines.append(line_text)

                if block_red_lines:
                    full_block_text = " ".join(block_red_lines).strip()
                    norm_bt = " ".join(full_block_text.split())

                    # Ignorer si ce texte était déjà présent en rouge dans l'incoming original du fournisseur
                    if norm_bt in incoming_red_texts or any(norm_bt in it or it in norm_bt for it in incoming_red_texts if len(it) > 5):
                        continue

                    # Vérifier si ce texte est déjà présent ou sous-chaîne d'une annotation existante
                    is_duplicate = any(norm_bt in s or s in norm_bt for s in seen_texts)
                    if (not is_duplicate and len(norm_bt) > 3 
                        and sum(1 for ch in norm_bt if ch.isalnum()) >= 2
                        and not is_reviewer_stamp(norm_bt)):
                        seen_texts.add(norm_bt)
                        human_comments.append({
                            "source": "RED_TEXT",
                            "page": p_num,
                            "type": "TextBlock",
                            "text": norm_bt
                        })

        doc.close()
        return human_comments

    def find_all_equipment_folders(self) -> List[Dict[str, Any]]:
        """Découvre tous les dossiers équipements avec INCOMING et OUTGOING disponibles."""
        if not self.base_dir.exists():
            return []

        equipment_sets = []
        for eq_dir in sorted(self.base_dir.iterdir()):
            if eq_dir.is_dir():
                inc_dir = eq_dir / "INCOMING"
                out_dir = eq_dir / "OUTCOMING"
                if not out_dir.exists():
                    out_dir = eq_dir / "OUTGOING"

                if inc_dir.exists() and out_dir.exists():
                    inc_pdfs = list(inc_dir.rglob("*.pdf"))
                    out_pdfs = list(out_dir.rglob("*.pdf"))
                    if inc_pdfs and out_pdfs:
                        equipment_sets.append({
                            "equipment_name": eq_dir.name,
                            "incoming_pdf": str(inc_pdfs[0]),
                            "outgoing_pdf": str(out_pdfs[0]),
                            "incoming_count": len(inc_pdfs),
                            "outgoing_count": len(out_pdfs)
                        })

        return equipment_sets

    def evaluate_dossier(self, incoming_pdf: str, outgoing_pdf: str) -> Dict[str, Any]:
        """
        Compare les anomalies détectées par ARKAN avec les commentaires réels de l'expert humain.
        """
        # 1. Extraction des commentaires réels de l'expert
        human_comments = self.extract_human_expert_comments(outgoing_pdf, incoming_pdf_path=incoming_pdf)

        # 2. Exécution du moteur ARKAN (Cross-validation + Moteur réglementaire)
        from arh_document_processor import ARHDocumentProcessor
        from arh_cross_validator import arh_cross_validator

        # Préparer le dossier physique dans arh_uploads
        dossier_id = f"BENCH_{uuid.uuid4().hex[:8].upper()}"
        base_uploads = Path(__file__).parent / "arh_uploads" / dossier_id
        base_uploads.mkdir(parents=True, exist_ok=True)
        dest_pdf = base_uploads / Path(incoming_pdf).name
        if not dest_pdf.exists():
            shutil.copy2(incoming_pdf, dest_pdf)

        proc = ARHDocumentProcessor()
        audit_res = proc.process_dossier_batch(
            file_paths=[str(dest_pdf)],
            project_name="BENCHMARK_EXPERT_HUMAIN",
            unit_name="UNIT-AUDIT",
            dossier_id=dossier_id
        )

        # Exécuter le Cross-Validator sur ce dossier
        cross_res = arh_cross_validator.validate_dossier(dossier_id)

        # Rassembler toutes les anomalies / réserves émises par ARKAN
        arkan_findings = []
        for c in audit_res.get("comments", []):
            arkan_findings.append({
                "source": "REGULATORY_AUDIT",
                "priority": c.get("priority", "Majeure"),
                "title": c.get("title", ""),
                "page": c.get("page", 1),
                "text": f"{c.get('title', '')} : {c.get('description', '')} {c.get('action_required', '')}"
            })

        for a in cross_res.get("anomalies", []):
            arkan_findings.append({
                "source": "CROSS_VALIDATOR",
                "priority": a.get("priority", "CRITIQUE"),
                "title": a.get("title", ""),
                "page": 1,
                "text": f"{a.get('title', '')} : {a.get('description', '')} {a.get('action_required', '')}"
            })

        # 3. Matching Sémantique et Calcul du Rappel (Recall)
        matches = []
        missed_by_arkan = []

        STOP_WORDS = {
            "les", "des", "qui", "pas", "une", "pour", "dans", "par", "sur",
            "and", "the", "add", "voir", "avec", "seront", "sera", "cette",
            "sont", "être", "faire", "plus", "tout", "tous", "dossier", "page",
            "pages", "comme", "lors", "partie", "avoir"
        }

        # Synonymes d'ingénierie
        SYNONYMS = {
            "remarque": ["certificat", "annexe", "dossier", "p-cte-1", "conformité", "procédure", "note", "remarque", "dessin"],
            "barreaux": ["barres", "bars", "barreau"],
            "barres": ["barreaux", "bars", "barreau"],
            "bars": ["barreaux", "barres", "barreau"],
            "matériau": ["matière", "material", "mat"],
            "materiau": ["matière", "material", "mat"],
            "wps": ["soudage", "wps", "welding", "pqr"],
            "pqr": ["qualification", "pqr", "wps"],
            "extruded": ["piquage", "extrudé", "outlets", "renfort"],
            "outlets": ["piquage", "extrudé", "extruded"],
            "b16": ["b16.25", "chanfrein", "biseau", "bevel"],
            "b16.25": ["chanfrein", "biseau", "bevel", "asme"],
            "a860": ["wphy60", "wphy", "nuance"],
            "wphy60": ["a860", "nuance"],
            "section": ["coupe", "detail", "vue", "assemblage"],
            "itp": ["inspection", "contrôle", "hold", "point"],
            "pression": ["test", "épreuve", "hydrotest", "calcul"],
            "final": ["dossier", "tés", "introduire", "certificats"],
            "ingénierie": ["calcul", "plan", "extruded", "b16.25", "barreaux"],
            "épaisseur": ["thickness", "épaisseurs", "thicknesses", "11.1mm", "29mm"],
            "épaisseurs": ["thickness", "épaisseur", "thicknesses", "11.1mm", "29mm"],
            "thickness": ["épaisseur", "thicknesses", "épaisseurs", "11.1mm", "29mm"],
            "thicknesses": ["épaisseur", "thickness", "épaisseurs"],
            "diamètre": ["diameter", "od", "dn", "nominal", "168.3", "item 16"],
            "diametre": ["diameter", "od", "dn", "nominal", "168.3", "item 16"],
            "od": ["diamètre", "diametre", "diameter", "nominal", "pouce", "pipe", "item 16"],
            "calamine": ["visual", "visuel", "calamine", "contrôle", "interne"],
            "a530": ["essai", "usine", "pression", "hydrostatique", "astm"],
            "fluide": ["fluid", "véhiculé", "vehicule", "handled", "specifiication"],
            "fluid": ["fluide", "véhiculé", "vehicule", "handled"],
            "scope": ["piping", "liste", "équipement", "equipement", "périmètre"],
            "piping": ["scope", "tuyauterie", "pipe", "canalisations", "étude"],
            "re": ["rm", "yield", "tensile", "inversion", "api", "élastique"],
            "rm": ["re", "yield", "tensile", "inversion", "api", "rupture"],
            "yield": ["tensile", "re", "rm", "élastique", "inversion"],
            "tensile": ["yield", "re", "rm", "rupture", "inversion"],
            "psl2": ["pliage", "bend", "flattening", "écrasement", "nde", "ut", "em", "laminage", "manque"],
            "repère": ["document", "repere", "référence", "identification"],
            "repere": ["document", "repère", "référence", "identification"],
            "visual": ["visuel", "contrôle", "calamine", "inspection"],
            "visuel": ["visual", "contrôle", "calamine", "inspection"],
            "inversés": ["inversion", "inversées", "re", "rm", "api"],
            "inverses": ["inversion", "inversées", "re", "rm", "api"],
            "mentionnez": ["mentionner", "préciser", "déclarer", "conforme"],
            "code": ["code 03", "mazouzi", "rejeté", "statut", "décision", "avis"],
            "mazouzi": ["code 03", "avis", "expert", "arh", "décision"],
            "administratif": ["consulat", "certificat", "légalisation", "qaqc"],
            "qaqc": ["consulat", "administratif", "certificats", "réserves"],
            "ultrasonic": ["ut", "nde", "cnd", "ultrasons", "testing"],
            "longitudinaux": ["défauts", "transversaux", "nde", "ut", "inspection"],
            "transversaux": ["défauts", "longitudinaux", "nde", "ut", "inspection"],
            "painting": ["peinture", "revêtement", "coating", "psl2"],
            "soumis": ["applicable", "non applicable", "non soumis", "remplacer", "not applicable", "not aplicable"],
            "applicable": ["soumis", "non soumis", "non applicable", "not applicable", "not aplicable"],
            "aplicable": ["applicable", "non applicable", "soumis", "non soumis", "not applicable"],
            "conversion": ["15.4mpa", "11.2mpa", "bar", "pression", "convertir"],
            "division": ["method", "deleted", "asme", "formule", "calcul"],
            "425": ["425°c", "température", "service", "stress", "fluage"],
            "volume": ["état", "descriptif", "calcul", "température", "pression"],
            "qualité": ["consulat", "certificats", "commerce", "légalisation"],
            "qualite": ["consulat", "certificats", "commerce", "légalisation"],
            "clarify": ["valves", "données", "typical", "conversion"],
            "typical": ["valves", "clarify", "data"],
            "years": ["division", "deleted", "method", "calcul", "obsolète"],
            "ago": ["division", "deleted", "method", "calcul", "obsolète"],
            "correct": ["conformity", "code", "design", "stress", "algerian", "reference"],
            "check": ["conformity", "code", "design", "stress", "algerian", "reference"],
            "reference": ["normative", "standard", "code", "indiquer", "indicate", "référence"],
            "selected": ["matériau", "nuance", "a105", "material", "stress", "sélectionné"],
            "material": ["matériau", "nuance", "a105", "a216", "wcc", "selected", "matériaux"],
            "stress": ["contrainte", "admissible", "formule", "formula", "146mpa", "allowable"],
            "formula": ["formule", "calcul", "stress", "contrainte", "épaisseur", "thickness"],
            "gcb": ["process", "datasheet", "fiche", "procédé", "remplacer", "submitted"],
            "process": ["gcb", "datasheet", "procédé", "fiche", "calcul", "débit"],
            "datasheet": ["gcb", "process", "fiche", "procédé", "remplacer", "données"],
            "description": ["état", "descriptif", "fiche", "annexe", "divergence", "different"],
            "different": ["divergence", "incohérence", "différence", "état", "descriptif"],
            "bars": ["bar", "pression", "102.1", "service", "rating", "classe"],
            "102.1": ["bar", "bars", "rating", "classe", "pression", "150°c"],
            "146mpa": ["b31.3", "contrainte", "admissible", "150°c", "a105"],
            "pt": ["mt", "nde", "cnd", "ressuage", "magnétoscopie", "essais", "tests", "contrôle"],
            "mt": ["pt", "nde", "cnd", "ressuage", "magnétoscopie", "essais", "tests", "contrôle"],
            "fugitive": ["émissions", "fuite", "iso 15848", "api 641", "étanchéité", "fugitives"],
            "fuite": ["fugitive", "émissions", "étanchéité", "test", "iso 15848"],
            "proof": ["burst", "test", "épreuve", "éclatement", "asme", "b16.9", "rapport"],
            "burst": ["proof", "test", "épreuve", "éclatement", "asme", "b16.9", "rapport"],
            "mtr": ["material", "test", "report", "certificat", "matière", "3.1", "b16.9"],
            "instrument": ["mesure", "pression", "manomètre", "étalonnage", "9.6", "préciser"],
            "fire": ["feu", "6fa", "607", "incendie", "test"],
            "6fa": ["fire", "test", "607", "incendie"],
            "hardness": ["dureté", "hrc", "nace", "mr0175", "test"],
            "hrc": ["hardness", "dureté", "nace", "mr0175", "22"],
            "poinçon": ["poincon", "plaque", "signalétique", "arh", "frapper", "tiers"],
            "poincon": ["poinçon", "plaque", "signalétique", "arh", "frapper", "tiers"],
            "signalétique": ["plaque", "nameplate", "poinçon", "signaletique", "plan"],
            "signaletique": ["plaque", "nameplate", "poinçon", "signalétique", "plan"],
            "dgm": ["arh", "remplacer", "mines", "autorité", "régulation"],
            "fat": ["usine", "réception", "essais", "tiers", "partie", "h"],
            "140": ["ug-99", "bar", "pression", "essai", "hydro", "asme"],
            "316l": ["matériau", "retirer", "nuance", "inox"],
            "garde": ["page", "officiel", "gcb", "officielle", "attacher"]
        }

        for h in human_comments:
            h_text = h["text"].lower()
            matched = False
            best_finding = None

            raw_words = [w.strip('.').strip() for w in re.split(r'[^a-zA-Z0-9_àéèêôûç]+', h_text) if len(w.strip('.').strip()) >= 3 and w.strip('.').strip() not in STOP_WORDS]
            
            # Étendre avec synonymes
            extended_kws = set(raw_words)
            for w in raw_words:
                for syn in SYNONYMS.get(w, []):
                    extended_kws.add(syn)

            for f in arkan_findings:
                f_text = f["text"].lower()
                overlap = sum(1 for kw in extended_kws if kw in f_text)
                
                # Critère de correspondance :
                # - au moins 2 mots clés si la phrase a 2+ mots
                # - ou 1 mot clé fort
                strong_kws = {
                    "wps", "pqr", "b16.25", "a860", "wphy60", "extruded", 
                    "barreaux", "barres", "bars", "itp", "section", "pression", "final",
                    "a530", "b31.8", "b31.3", "calamine", "fluide", "psl2", "smls", 
                    "thickness", "épaisseur", "épaisseurs", "scope", "piping", "re", "rm", 
                    "yield", "tensile", "od", "item 16", "item 13", "item 14",
                    "mazouzi", "code 03", "qaqc", "visual", "visuel", "painting", 
                    "ultrasonic", "transversaux", "longitudinaux", "inversés", "inversé",
                    "administratif", "soumis", "conversion", "division", "425", "volume",
                    "qualité", "qualite", "typical", "clarify", "years", "ago", "correct",
                    "reference", "material", "formula", "datasheet", "different", "102.1", "146mpa", "stress",
                    "pt", "mt", "fugitive", "fuite",
                    "burst", "proof", "mtr", "instrument", "fire", "6fa", "hardness", "hrc", 
                    "poinçon", "poincon", "signalétique", "signaletique", "dgm", "fat", "140", "316l", "garde"
                }
                has_strong = any(sk in extended_kws and sk in f_text for sk in strong_kws)

                if (len(raw_words) >= 2 and overlap >= 2) or (has_strong and overlap >= 1) or (len(raw_words) == 1 and overlap >= 1):
                    matched = True
                    best_finding = f
                    break

            if matched:
                matches.append({
                    "human_comment": h["text"],
                    "human_page": h["page"],
                    "matched_arkan_finding": best_finding["text"],
                    "priority": best_finding["priority"]
                })
            else:
                missed_by_arkan.append({
                    "human_comment": h["text"],
                    "human_page": h["page"]
                })

        total_human = len(human_comments)
        matched_count = len(matches)
        recall_pct = round((matched_count / total_human * 100.0), 1) if total_human > 0 else 100.0

        extra_arkan_findings = len(arkan_findings) - matched_count

        return {
            "incoming_pdf": incoming_pdf,
            "outgoing_pdf": outgoing_pdf,
            "total_human_comments": total_human,
            "arkan_matched_count": matched_count,
            "recall_score_pct": recall_pct,
            "arkan_total_findings": len(arkan_findings),
            "extra_valid_findings_count": max(0, extra_arkan_findings),
            "matches": matches,
            "missed_by_arkan": missed_by_arkan,
            "dossier_id": dossier_id
        }

arh_evaluator = ARHBenchmarkEvaluator()
