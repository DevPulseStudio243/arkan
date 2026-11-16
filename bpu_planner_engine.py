"""
bpu_planner_engine.py
=====================
Moteur Expert d'Extraction de Bordereau des Prix Unitaires (BPU / DQE / BOQ)
et de Génération Automatique de Planning CPM pour Projets Industriels & Oil & Gas.

Capacités :
  1. Extraction multi-formats :
     - Fichiers Excel (.xlsx, .xls) via pandas & openpyxl avec détection automatique des en-têtes
     - Fichiers PDF via PyMuPDF (fitz) avec analyse tabulaire
     - Fichiers CSV / TSV
     - Texte brut copié-collé depuis Excel / Word
  2. Normalisation intelligente des unités d'œuvre pétrolières (m³, ml, DI, tonne, u, lot, etc.).
  3. Appariement sémantique & RAG avec la base des 452 tâches expertes (planning_knowledge.db).
  4. Calcul automatique des durées par application des rendements étalonnés et équipes types.
  5. Séquençage logique inter-disciplines et calcul CPM NetworkX (Chemin critique, marges).
  6. Injection automatique des phases de Pré-Commissioning (Fiches A) et Commissioning (Fiches B).
"""

from __future__ import annotations

import io
import re
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd
import fitz  # PyMuPDF
import networkx as nx

from planning_knowledge_db import planning_db
from planning_generation_engine import (
    planning_rag, planning_cpm, planning_guardrails,
    TachePlanning, RendementDetail, EquipeRole, PlanningResponse
)
from planning_commissioning_knowledge import commissioning_engine

logger = logging.getLogger("arkan.bpu_planner")

# ══════════════════════════════════════════════════════════════════════════════
# DICTIONNAIRE DE NORMALISATION DES UNITÉS D'ŒUVRE
# ══════════════════════════════════════════════════════════════════════════════
UNIT_SYNONYMS: Dict[str, str] = {
    "m3": "m³", "m³": "m³", "cu.m": "m³", "cum": "m³", "m3/h": "m³/h",
    "ml": "ml", "m": "ml", "metre": "ml", "mètre": "ml", "meter": "ml", "lm": "ml", "lin.m": "ml",
    "t": "tonne (t)", "tonne": "tonne (t)", "tonnes": "tonne (t)", "ton": "tonne (t)", "to": "tonne (t)", "kg": "kg",
    "di": "DI (Diamètre-Pouce)", "di.": "DI (Diamètre-Pouce)", "diametre-pouce": "DI (Diamètre-Pouce)", "dia-inch": "DI (Diamètre-Pouce)", "inch-dia": "DI (Diamètre-Pouce)", "dp": "DI (Diamètre-Pouce)",
    "u": "u", "u.": "u", "unite": "u", "unité": "u", "unit": "u", "ea": "u", "each": "u", "nb": "u", "nbre": "u", "pcs": "u", "pce": "u", "item": "u",
    "m2": "m²", "m²": "m²", "sqm": "m²", "sq.m": "m²", "m2/j": "m²/j",
    "ff": "lot", "forfait": "lot", "ens": "lot", "ensemble": "lot", "lot": "lot", "ls": "lot", "lump sum": "lot",
    "joint": "joint", "jnt": "joint", "coude": "coude", "vanne": "vanne", "buse": "buse", "relais": "relais",
    "boucle": "boucle (Loop)", "loop": "boucle (Loop)", "test": "test", "doc": "document", "document": "document"
}

def normalize_unit(unit_raw: str) -> str:
    """Normalise une chaîne d'unité vers la nomenclature standard ARKAN."""
    if not unit_raw:
        return "u"
    clean = re.sub(r'[^a-zA-Z0-9³/²\.\-]', '', str(unit_raw).strip().lower())
    return UNIT_SYNONYMS.get(clean, unit_raw.strip())


# ══════════════════════════════════════════════════════════════════════════════
# 1. EXTRACTEUR UNIVERSEL DE BPU (EXCEL, PDF, CSV, TEXTE)
# ══════════════════════════════════════════════════════════════════════════════

class BPUExtractor:
    """Extracteur universel et tolérant aux pannes pour Bordereaux des Prix Unitaires."""

    @staticmethod
    def extract_from_excel(file_bytes: bytes, filename: str = "bpu.xlsx") -> List[Dict[str, Any]]:
        """Extrait les articles BPU depuis un classeur Excel (.xlsx, .xls)."""
        items = []
        try:
            excel_file = io.BytesIO(file_bytes)
            xl = pd.ExcelFile(excel_file)
            
            # Parcourir les feuilles
            for sheet_name in xl.sheet_names:
                df = xl.parse(sheet_name)
                sheet_items = BPUExtractor._parse_dataframe(df, source=f"Excel:{sheet_name}")
                if sheet_items:
                    items.extend(sheet_items)
                    break  # Prendre la première feuille contenant des données BPU valides
            
            # Si vide, tenter avec header=None
            if not items and xl.sheet_names:
                df_raw = xl.parse(xl.sheet_names[0], header=None)
                items = BPUExtractor._parse_raw_unstructured_dataframe(df_raw, source=filename)

        except Exception as e:
            logger.error(f"[BPUExtractor] Erreur lecture Excel : {e}")
            raise ValueError(f"Impossible de lire le fichier Excel : {str(e)}")

        return items

    @staticmethod
    def extract_from_pdf(file_bytes: bytes, filename: str = "bpu.pdf") -> List[Dict[str, Any]]:
        """Extrait les articles BPU depuis un fichier PDF vectoriel ou scanné."""
        items = []
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text_lines = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                # 1. Extraction des tableaux structurés si disponibles
                tabs = page.find_tables()
                if tabs.tables:
                    for tab in tabs:
                        df = tab.to_pandas()
                        tab_items = BPUExtractor._parse_dataframe(df, source=f"PDF:Page{page_num+1}")
                        if tab_items:
                            items.extend(tab_items)
                
                # Récupérer les lignes de texte brutes
                text = page.get_text("text")
                if text:
                    full_text_lines.extend(text.splitlines())

            # Si aucun tableau formel n'a été extrait, parser le texte en mode heuristique
            if not items and full_text_lines:
                items = BPUExtractor.extract_from_text("\n".join(full_text_lines))

        except Exception as e:
            logger.error(f"[BPUExtractor] Erreur lecture PDF : {e}")
            raise ValueError(f"Impossible de lire le document PDF : {str(e)}")

        return items

    @staticmethod
    def extract_from_csv(csv_text: str) -> List[Dict[str, Any]]:
        """Extrait les articles depuis une chaîne CSV ou TSV."""
        items = []
        try:
            # Détection du délimiteur (; ou , ou tab)
            delimiter = ';' if ';' in csv_text else '\t' if '\t' in csv_text else ','
            df = pd.read_csv(io.StringIO(csv_text), sep=delimiter)
            items = BPUExtractor._parse_dataframe(df, source="CSV")
            if not items:
                items = BPUExtractor.extract_from_text(csv_text)
        except Exception:
            items = BPUExtractor.extract_from_text(csv_text)
        return items

    @staticmethod
    def extract_from_text(pasted_text: str) -> List[Dict[str, Any]]:
        """Extrait les articles BPU depuis du texte copié-collé libre ou tabulé."""
        items = []
        lines = pasted_text.strip().splitlines()
        item_counter = 1

        for line in lines:
            line_clean = line.strip()
            if not line_clean or len(line_clean) < 5:
                continue

            # Ignorer les lignes d'en-tête évidentes
            if any(h in line_clean.lower() for h in ["désignation", "designation", "prix unitaire", "montant", "quantite", "unité", "total"]):
                continue

            # 1. Découpage par tabulation, point-virgule ou barre verticale
            parts = re.split(r'[\t;|]', line_clean)
            if len(parts) >= 3:
                code_cand = parts[0].strip()
                desc_cand = parts[1].strip()
                unit_cand = parts[2].strip()
                qty_cand = parts[3].strip() if len(parts) > 3 else "1.0"
                
                qty_val = BPUExtractor._parse_float(qty_cand)
                if qty_val is None:
                    qty_val = BPUExtractor._parse_float(unit_cand)
                    if qty_val is not None:
                        unit_cand = parts[3].strip() if len(parts) > 3 else "u"

                if desc_cand and len(desc_cand) > 3:
                    items.append({
                        "item_code": code_cand if len(code_cand) < 15 else f"ART-{item_counter:03d}",
                        "designation": desc_cand,
                        "unite": normalize_unit(unit_cand),
                        "quantite": qty_val if qty_val is not None else 1.0,
                        "prix_unitaire": BPUExtractor._parse_float(parts[4]) if len(parts) > 4 else None,
                        "ligne_source": line_clean
                    })
                    item_counter += 1
                    continue

            # 2. Détection par motif regex d'espaces : Code + Description + (Unité + Quantité) ou (Quantité + Unité)
            # Pattern A : 1.01 Fouille en rigole m3 2500 (ou 1.01 Fouille en rigole m3 2500 450)
            m_a = re.match(r'^(?:(?:art|item|n°|poste)?\s*([0-9]+(?:\.[0-9]+)*))?\s*[:\-\.]?\s*(.+?)\s+(m³|m3|ml|t|tonne|tonnes|di|u|lot|m²|m2|ens|forfait)\s+(\d+(?:[\.,]\d+)?)(?:\s+([\d\s\.,]+))?$', line_clean, re.I)
            if m_a:
                code_val = m_a.group(1) or f"ART-{item_counter:03d}"
                desc_val = m_a.group(2).strip()
                unit_val = m_a.group(3).strip()
                qty_val = BPUExtractor._parse_float(m_a.group(4)) or 1.0
                pu_val = BPUExtractor._parse_float(m_a.group(5)) if m_a.group(5) else None

                if desc_val:
                    items.append({
                        "item_code": code_val,
                        "designation": desc_val,
                        "unite": normalize_unit(unit_val),
                        "quantite": qty_val,
                        "prix_unitaire": pu_val,
                        "ligne_source": line_clean
                    })
                    item_counter += 1
                    continue

            # Pattern B : 1.01 Fouille en rigole 2500 m3 (ou 1.01 Fouille en rigole 2500 m3 450)
            m_b = re.match(r'^(?:(?:art|item|n°|poste)?\s*([0-9]+(?:\.[0-9]+)*))?\s*[:\-\.]?\s*(.+?)\s+(\d+(?:[\.,]\d+)?)\s+(m³|m3|ml|t|tonne|tonnes|di|u|lot|m²|m2|ens|forfait|[a-zA-Z³²\/\.]+)(?:\s+([\d\s\.,]+))?$', line_clean, re.I)
            if m_b:
                code_val = m_b.group(1) or f"ART-{item_counter:03d}"
                desc_val = m_b.group(2).strip()
                qty_val = BPUExtractor._parse_float(m_b.group(3)) or 1.0
                unit_val = m_b.group(4).strip()
                pu_val = BPUExtractor._parse_float(m_b.group(5)) if m_b.group(5) else None

                if desc_val:
                    items.append({
                        "item_code": code_val,
                        "designation": desc_val,
                        "unite": normalize_unit(unit_val),
                        "quantite": qty_val,
                        "prix_unitaire": pu_val,
                        "ligne_source": line_clean
                    })
                    item_counter += 1
                    continue

            # Pattern C : Recherche globale du dernier bloc quantité + unité dans la ligne
            num_match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(m³|m3|ml|t|tonnes?|di|pouces?|u|lot|m²|m2)\b', line_clean, re.I)
            if num_match:
                qty_val = BPUExtractor._parse_float(num_match.group(1)) or 1.0
                unit_val = num_match.group(2)
                desc_val = line_clean[:num_match.start()].strip()
                # Enlever le code de tête s'il existe
                m_code = re.match(r'^(?:(?:art|item|n°|poste)?\s*([0-9]+(?:\.[0-9]+)*))?\s*[:\-\.]?\s*(.*)$', desc_val, re.I)
                code_val = (m_code.group(1) if m_code else None) or f"ART-{item_counter:03d}"
                desc_clean = (m_code.group(2) if m_code else desc_val).strip()

                if desc_clean and len(desc_clean) > 2:
                    items.append({
                        "item_code": code_val,
                        "designation": desc_clean,
                        "unite": normalize_unit(unit_val),
                        "quantite": qty_val,
                        "prix_unitaire": None,
                        "ligne_source": line_clean
                    })
                    item_counter += 1

        return items

    @staticmethod
    def _parse_dataframe(df: pd.DataFrame, source: str = "") -> List[Dict[str, Any]]:
        """Détecte les colonnes clés dans un DataFrame pandas et extrait les articles."""
        items = []
        if df.empty or len(df) < 1:
            return items

        # Nettoyage des noms de colonnes
        cols = [str(c).strip().lower() for c in df.columns]
        
        idx_col = None
        desc_col = None
        unit_col = None
        qty_col = None
        pu_col = None

        # Identification précise des colonnes
        for orig_c, c in zip(df.columns, cols):
            if any(k in c for k in ["prix", "p.u", "pu", "rate", "price"]) or "prix unitaire" in c:
                pu_col = orig_c
            elif any(k in c for k in ["quantite", "quantité", "qty", "qte", "qté", "metré", "métré", "quantities", "quantity"]):
                qty_col = orig_c
            elif (any(k in c for k in ["unite", "unité", "unit", "u.m", "um"]) and "prix" not in c and "pu" not in c) or c == "u":
                unit_col = orig_c
            elif any(k in c for k in ["code", "item", "n°", "no", "num", "article", "poste", "ref"]):
                idx_col = orig_c
            elif any(k in c for k in ["designation", "désignation", "description", "libelle", "libellé", "travaux", "intitule", "intitulé"]):
                desc_col = orig_c

        # Si pas de desc_col trouvée, chercher la première colonne textuelle
        if not desc_col:
            for c in df.columns:
                if df[c].dtype == object and df[c].str.len().mean() > 10:
                    desc_col = c
                    break

        if not desc_col:
            return items

        item_counter = 1
        for _, row in df.iterrows():
            desc_val = str(row.get(desc_col, "")).strip()
            if not desc_val or desc_val.lower() in ["nan", "none", "total", "sous-total"] or len(desc_val) < 3:
                continue

            # Quantité
            qty_raw = row.get(qty_col, 1.0) if qty_col else 1.0
            qty_val = BPUExtractor._parse_float(qty_raw) or 1.0

            # Unité
            unit_raw = str(row.get(unit_col, "u")).strip() if unit_col else "u"
            if unit_raw.lower() in ["nan", "none"]:
                unit_raw = "u"

            # Code item
            code_raw = str(row.get(idx_col, f"ART-{item_counter:03d}")).strip() if idx_col else f"ART-{item_counter:03d}"
            if code_raw.lower() in ["nan", "none"]:
                code_raw = f"ART-{item_counter:03d}"

            # Prix unitaire
            pu_val = BPUExtractor._parse_float(row.get(pu_col)) if pu_col else None

            items.append({
                "item_code": code_raw,
                "designation": desc_val,
                "unite": normalize_unit(unit_raw),
                "quantite": qty_val,
                "prix_unitaire": pu_val,
                "source": source
            })
            item_counter += 1

        return items

    @staticmethod
    def _parse_raw_unstructured_dataframe(df: pd.DataFrame, source: str = "") -> List[Dict[str, Any]]:
        """Gère les feuilles Excel sans ligne d'en-tête formelle."""
        text_lines = []
        for _, row in df.iterrows():
            row_str = "\t".join([str(v) for v in row if pd.notna(v)])
            if row_str.strip():
                text_lines.append(row_str)
        return BPUExtractor.extract_from_text("\n".join(text_lines))

    @staticmethod
    def _parse_float(val: Any) -> Optional[float]:
        """Convertit une chaîne en flottant en gérant virgules, espaces et symboles."""
        if val is None or pd.isna(val):
            return None
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).replace(' ', '').replace('\xa0', '').replace(',', '.')
            # Nettoyer les caractères monétaires
            s = re.sub(r'[^0-9\.\-]', '', s)
            return float(s) if s else None
        except Exception:
            return None

    @staticmethod
    def enrich_item_with_knowledge(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse sémantiquement l'article du BPU via le RAG et planning_knowledge.db (452 tâches) :
        - Détermine la discipline WBS
        - Trouve la tâche de référence matched
        - Extrait le rendement journalier calibré
        - Calcule la durée physique (Quantité / Rendement)
        - Extrait la composition d'équipe type et les outillages
        """
        desig = item.get("designation", "").strip()
        unite = item.get("unite", "u")
        qty = max(0.01, float(item.get("quantite", 1.0)))

        rag_matches = planning_rag.search_similar_tasks(desig, top_k=1, unite=unite)
        if rag_matches:
            match = rag_matches[0]
            discipline = match.get("discipline", "06_TUYAUTERIE_MONTAGE_SITE")
            rend_val = max(0.01, float(match.get("rendement_valeur", 10.0)))
            rend_unite = match.get("rendement_unite", f"{unite}/jour/équipe")
            duree = round(qty / rend_val, 1)
            if duree < 0.5:
                duree = 0.5

            equipe_raw = json.loads(match.get("composition_json", "[]")) if isinstance(match.get("composition_json"), str) else match.get("composition_json", [])
            mat_raw = json.loads(match.get("ressources_json", "[]")) if isinstance(match.get("ressources_json"), str) else match.get("ressources_json", ["Outillage standard"])
            sources = [match.get("source", "Référentiel EPC")]
            if match.get("normes_associees"):
                sources.append(match.get("normes_associees"))

            item["matched_task_id"] = match.get("id_tache")
            item["matched_task_name"] = match.get("nom_tache")
            item["wbs_discipline"] = discipline
            item["wbs_discipline_nom"] = discipline.split("_", 1)[1].replace("_", " ") if "_" in discipline else discipline
            item["rendement_valeur"] = rend_val
            item["rendement_unite"] = rend_unite
            item["duree_estimee_jours"] = duree
            item["equipe_type"] = equipe_raw
            item["ressources_materielles"] = mat_raw
            item["confidence_score"] = round(float(match.get("score_pertinence", 0.90)) * 100, 1)
            item["sources"] = sources
        else:
            # Fallback robuste
            item["matched_task_id"] = f"TASK-{item.get('item_code', 'GEN')}"
            item["matched_task_name"] = desig
            item["wbs_discipline"] = "06_TUYAUTERIE_MONTAGE_SITE"
            item["wbs_discipline_nom"] = "TUYAUTERIE MONTAGE SITE"
            item["rendement_valeur"] = 10.0
            item["rendement_unite"] = f"{unite}/j"
            item["duree_estimee_jours"] = max(0.5, round(qty / 10.0, 1))
            item["equipe_type"] = ["1 Chef d'équipe", "2 Ouvriers qualifiés"]
            item["ressources_materielles"] = ["Outillage standard"]
            item["confidence_score"] = 75.0
            item["sources"] = ["Estimation Standard EPC"]

        return item

    @staticmethod
    def enrich_items_with_knowledge(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrichit une liste entière d'articles BPU avec l'analyse WBS et rendements."""
        enriched = []
        for it in items:
            enriched.append(BPUExtractor.enrich_item_with_knowledge(it))
        return enriched


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONVERTISSEUR BPU ➔ PLANNING INDUSTRIEL EXPERT (RAG + CPM + PC&C)
# ══════════════════════════════════════════════════════════════════════════════

class BPUPlanningConverter:
    """
    Transforme la liste des articles métrés du BPU en un planning CPM rigoureux

    avec rendements de chantier, équipes types, matériels et phases de Précom/Comm.
    """

    # Ordre technologique des disciplines pour le chaînage automatique
    DISCIPLINE_EXECUTION_ORDER = [
        "01_INGENIERIE_ETUDES",
        "02_PROCUREMENT_LOGISTIQUE",
        "03_GENIE_CIVIL_TERRASSEMENT",
        "04_STRUCTURE_CHARPENTE",
        "05_TUYAUTERIE_PREFABRICATION",
        "06_TUYAUTERIE_MONTAGE_SITE",
        "07_EQUIPEMENTS_STATIQUES",
        "08_EQUIPEMENTS_DYNAMIQUES",
        "09_ELECTRICITE_HT_BT",
        "10_INSTRUMENTATION_AUTOMATISME",
        "11_ISOLATION_CALORIFUGE_PEINTURE",
        "12_PRECOMMISSIONING_TESTS",
        "13_COMMISSIONING_STARTUP",
        "13_COMMISSIONING_DEMARRAGE"
    ]

    @classmethod
    def convert_bpu_to_planning(
        cls,
        bpu_items: List[Dict[str, Any]],
        project_name: str = "PROJET_BPU_EXTRAIT",
        include_pcc: bool = True
    ) -> PlanningResponse:
        """
        Convertit la liste des articles BPU en un modèle complet PlanningResponse.
        """
        if not bpu_items:
            raise ValueError("Aucun article BPU valide fourni pour la conversion.")

        raw_tasks: List[TachePlanning] = []
        detected_equipment_set = set()
        previous_task_id = None

        # ── 1. Appariement RAG & Calcul de chaque tâche BPU ──
        for idx, item in enumerate(bpu_items, 1):
            desig = item.get("designation", "").strip()
            unite = item.get("unite", "u")
            qty = max(0.1, float(item.get("quantite", 1.0)))
            item_code = item.get("item_code") or f"BPU-{idx:03d}"

            # Recherche RAG de la tâche type la plus proche
            rag_matches = planning_rag.search_similar_tasks(desig, top_k=1, unite=unite)
            if rag_matches:
                match = rag_matches[0]
                discipline = match.get("discipline", "06_TUYAUTERIE_MONTAGE_SITE")
                rend_val = max(0.01, float(match.get("rendement_valeur", 10.0)))
                rend_unite = match.get("rendement_unite", f"{unite}/jour/équipe")
                equipe_raw = json.loads(match.get("composition_json", "[]")) if isinstance(match.get("composition_json"), str) else match.get("composition_json", [])
                mat_raw = json.loads(match.get("ressources_json", "[]")) if isinstance(match.get("ressources_json"), str) else match.get("ressources_json", ["Outillage standard"])
                sources = [match.get("source", "Référentiel EPC")] + [match.get("normes_associees", "")]
                confiance = match.get("niveau_confiance", "Haute")
            else:
                # Heuristique si aucun match direct
                discipline = cls._infer_discipline_from_text(desig)
                rend_val, rend_unite = cls._infer_yield_from_discipline_and_unit(discipline, unite)
                equipe_raw = [{"role": "Chef d'équipe spécialiste", "effectif": 1}, {"role": "Opérateurs qualifiés", "effectif": 2}]
                mat_raw = ["Engins et outillage de chantier"]
                sources = ["Estimation Métier ARKAN (BPU Extrait)"]
                confiance = "Moyenne"

            # Application des Guardrails & Calcul de durée
            val_ajustee, duree_calc, conf_eval, _ = planning_guardrails.audit_and_clamp_yield(
                tache_nom=desig,
                quantite=qty,
                rendement_propose=rend_val,
                unite=rend_unite,
                rag_match=rag_matches[0] if rag_matches else None
            )

            # Détection d'équipements pour le Commissioning
            desig_lower = desig.lower()
            if any(w in desig_lower for w in ["séparateur", "separateur", "ballon", "vessel"]):
                detected_equipment_set.add("PRESSURE_VESSEL_SEPARATOR")
            if any(w in desig_lower for w in ["compresseur", "compression", "turbine"]):
                detected_equipment_set.add("CENTRIFUGAL_COMPRESSOR_TRAIN")
            if any(w in desig_lower for w in ["bac", "stockage", "tank"]):
                detected_equipment_set.add("STORAGE_TANK_API650")
            if any(w in desig_lower for w in ["pompe", "pompage", "pump"]):
                detected_equipment_set.add("CENTRIFUGAL_PUMP_PACKAGE")
            if any(w in desig_lower for w in ["pipeline", "gazoduc", "oléoduc", "canalisation"]):
                detected_equipment_set.add("CROSS_COUNTRY_PIPELINE")
            if any(w in desig_lower for w in ["sous-station", "switchgear", "transformateur", "tgbt", "cellule"]):
                detected_equipment_set.add("ELECTRICAL_SUBSTATION_SWITCHGEAR")
            if any(w in desig_lower for w in ["dcs", "sis", "esd", "automate", "transmetteur", "boucle", "f&g"]):
                detected_equipment_set.add("INSTRUMENTATION_DCS_SIS")

            equipe_roles = [EquipeRole(role=r.get("role", "Spécialiste"), effectif=int(r.get("effectif", 1))) for r in equipe_raw]

            t_id = f"T-{idx:03d}"
            preds = [previous_task_id] if previous_task_id else []

            tache = TachePlanning(
                id_tache=t_id,
                nom=f"[{item_code}] {desig}",
                description=f"Exécution de l'article BPU '{item_code} - {desig}' pour une quantité métrée de {qty} {unite}.",
                phase=cls._get_phase_from_discipline(discipline),
                discipline=discipline,
                unite_oeuvre=unite,
                quantite_estimee=qty,
                rendement=RendementDetail(valeur=val_ajustee, unite=rend_unite),
                duree_jours=duree_calc,
                equipe_type=equipe_roles,
                ressources_materielles=mat_raw,
                predecesseurs=preds,
                successeurs=[],
                jalon=False,
                niveau_confiance=confiance,
                sources=sources
            )
            raw_tasks.append(tache)
            previous_task_id = t_id

        # ── 2. Injection Automatique du Pré-Commissioning & Commissioning ICAPS ──
        if include_pcc:
            if not detected_equipment_set:
                detected_equipment_set = {"PRESSURE_VESSEL_SEPARATOR", "INSTRUMENTATION_DCS_SIS"}

            pcc_activities = commissioning_engine.generate_commissioning_activities(
                equipment_types=list(detected_equipment_set),
                project_name=project_name
            )

            if pcc_activities:
                # Chaîner la première tâche de précom au dernier article de construction
                last_const_id = raw_tasks[-1].id_tache if raw_tasks else "T-001"
                pcc_activities[0]["predecesseurs"] = [last_const_id]

                for pcc_raw in pcc_activities:
                    eq_roles = [EquipeRole(role=r.get("role", "Spécialiste"), effectif=int(r.get("effectif", 1))) for r in pcc_raw.get("equipe_type", [])]
                    rend_dict = pcc_raw.get("rendement", {"valeur": 1.0, "unite": "u/j"})
                    
                    t_pcc = TachePlanning(
                        id_tache=pcc_raw["id_tache"],
                        nom=pcc_raw["nom"],
                        description=pcc_raw["description"],
                        phase=pcc_raw["phase"],
                        discipline=pcc_raw["discipline"],
                        unite_oeuvre=pcc_raw["unite_oeuvre"],
                        quantite_estimee=pcc_raw["quantite_estimee"],
                        rendement=RendementDetail(valeur=rend_dict["valeur"], unite=rend_dict["unite"]),
                        duree_jours=pcc_raw["duree_jours"],
                        equipe_type=eq_roles,
                        ressources_materielles=pcc_raw.get("ressources_materielles", []),
                        predecesseurs=pcc_raw.get("predecesseurs", []),
                        successeurs=[],
                        jalon=pcc_raw.get("jalon", False),
                        niveau_confiance=pcc_raw.get("niveau_confiance", "Haute"),
                        sources=pcc_raw.get("sources", [])
                    )
                    raw_tasks.append(t_pcc)

        # ── 3. Ordonnancement & Calcul CPM NetworkX ──
        ordered_tasks, precedence_warnings = planning_guardrails.enforce_universal_precedence(raw_tasks)
        ordered_tasks, critical_path, total_duration, cpm_warnings = planning_cpm.calculate_cpm(ordered_tasks)

        # Calcul score de confiance moyen
        conf_scores = {"Haute": 95, "Moyenne": 85, "Faible": 65}
        avg_conf = round(sum(conf_scores.get(t.niveau_confiance, 80) for t in ordered_tasks) / max(1, len(ordered_tasks)), 1)

        return PlanningResponse(
            projet_contexte=f"Planning Automatique extrait du BPU / DQE : {project_name} ({len(bpu_items)} articles métrés)",
            taches=ordered_tasks,
            chemin_critique=critical_path,
            duree_totale_jours=total_duration,
            avertissements=cpm_warnings + precedence_warnings,
            confidence_score_moyen=avg_conf,
            generated_at=datetime.now().isoformat()
        )

    @staticmethod
    def _infer_discipline_from_text(desig: str) -> str:
        """Déduit la discipline EPC à partir des mots-clés du libellé de l'article."""
        d = desig.lower()
        if any(w in d for w in ["étude", "calcul", "p&id", "plan", "ingénierie", "feed", "isométrique"]):
            return "01_INGENIERIE_ETUDES"
        elif any(w in d for w in ["fourniture", "achat", "approvisionnement", "importation", "livraison"]):
            return "02_PROCUREMENT_LOGISTIQUE"
        elif any(w in d for w in ["fouille", "terrassement", "béton", "fondation", "radier", "caniveau", "décapage", "remblai", "piste", "clôture", "vrd"]):
            return "03_GENIE_CIVIL_TERRASSEMENT"
        elif any(w in d for w in ["charpente", "structure", "pipe-rack", "caillebotis", "échelle", "support", "ossature"]):
            return "04_STRUCTURE_CHARPENTE"
        elif any(w in d for w in ["préfabrication", "spool", "chanfrein", "coupe tube", "atelier tuyauterie"]):
            return "05_TUYAUTERIE_PREFABRICATION"
        elif any(w in d for w in ["pose tuyauterie", "montage tuyauterie", "boulonnage", "bride", "vanne", "robinetterie", "pipeline", "collecteur"]):
            return "06_TUYAUTERIE_MONTAGE_SITE"
        elif any(w in d for w in ["ballon", "séparateur", "colonne", "bac", "cuve", "échangeur", "four", "réacteur", "filtre", "torche"]):
            return "07_EQUIPEMENTS_STATIQUES"
        elif any(w in d for w in ["compresseur", "pompe", "turbine", "moteur", "générateur", "aéroréfrigérant"]):
            return "08_EQUIPEMENTS_DYNAMIQUES"
        elif any(w in d for w in ["câble", "tirage", "armoire", "transformateur", "tgbt", "switchgear", "mcc", "éclairage", "terre", "ups"]):
            return "09_ELECTRICITE_HT_BT"
        elif any(w in d for w in ["transmetteur", "capteur", "dcs", "automate", "instrument", "boucle", "loop", "fibre optique", "f&g"]):
            return "10_INSTRUMENTATION_AUTOMATISME"
        elif any(w in d for w in ["peinture", "sablage", "revêtement", "calorifuge", "isolation", "protection cathodique"]):
            return "11_ISOLATION_CALORIFUGE_PEINTURE"
        elif any(w in d for w in ["épreuve hydro", "test hydro", "rinçage", "flushing", "alignement", "solo run", "loop check", "précommissioning"]):
            return "12_PRECOMMISSIONING_TESTS"
        elif any(w in d for w in ["mise en service", "démarrage", "commissioning", "inertage", "gaz-in", "oil-in", "performance 72h"]):
            return "13_COMMISSIONING_STARTUP"
        return "06_TUYAUTERIE_MONTAGE_SITE"

    @staticmethod
    def _infer_yield_from_discipline_and_unit(discipline: str, unit: str) -> Tuple[float, str]:
        """Définit un rendement par défaut cohérent selon la discipline et l'unité."""
        u = unit.lower()
        if "03_" in discipline:  # Génie civil
            if "m³" in u: return 20.0, "m³/jour/équipe"
            if "ml" in u: return 150.0, "ml/jour/équipe"
            if "m²" in u: return 300.0, "m²/jour/équipe"
        elif "04_" in discipline:  # Charpente
            if "tonne" in u: return 2.5, "tonne/jour/équipe"
            if "m²" in u: return 35.0, "m²/jour/équipe"
        elif "05_" in discipline:  # Tuyauterie préfab
            if "di" in u: return 25.0, "DI/jour/équipe"
        elif "06_" in discipline:  # Montage tuyauterie
            if "ml" in u: return 25.0, "ml/jour/équipe"
            if "di" in u: return 20.0, "DI/jour/équipe"
            if "vanne" in u or "u" in u: return 3.0, "vannes/jour/équipe"
        elif "07_" in discipline or "08_" in discipline:  # Équipements
            return 0.5, "équipement/jour/équipe"
        elif "09_" in discipline:  # Électricité
            if "ml" in u: return 60.0, "ml/jour/équipe"
            return 2.0, "départ/jour/équipe"
        elif "10_" in discipline:  # Instrumentation
            return 4.0, "instruments/jour/équipe"
        elif "11_" in discipline:  # Peinture/Calorifuge
            return 50.0, "m²/jour/équipe"
        elif "12_" in discipline or "13_" in discipline:  # Essais & Commissioning
            return 1.0, "test/jour/équipe"
        return 10.0, f"{unit}/jour/équipe"

    @staticmethod
    def _get_phase_from_discipline(discipline: str) -> str:
        """Associe la phase de projet globale à la discipline."""
        phase_map = {
            "01_INGENIERIE_ETUDES": "Ingénierie & Études",
            "02_PROCUREMENT_LOGISTIQUE": "Approvisionnements & Achats",
            "03_GENIE_CIVIL_TERRASSEMENT": "Génie Civil & Fondations",
            "04_STRUCTURE_CHARPENTE": "Charpente & Structure",
            "05_TUYAUTERIE_PREFABRICATION": "Préfabrication Tuyauterie",
            "06_TUYAUTERIE_MONTAGE_SITE": "Montage Tuyauterie & Lignes",
            "07_EQUIPEMENTS_STATIQUES": "Équipements Statiques",
            "08_EQUIPEMENTS_DYNAMIQUES": "Machines Tournantes",
            "09_ELECTRICITE_HT_BT": "Électricité & Distribution",
            "10_INSTRUMENTATION_AUTOMATISME": "Instrumentation & Contrôle",
            "11_ISOLATION_CALORIFUGE_PEINTURE": "Peinture & Calorifuge",
            "12_PRECOMMISSIONING_TESTS": "Pré-Commissioning (Essais à froid)",
            "13_COMMISSIONING_STARTUP": "Commissioning & Mise en service",
            "13_COMMISSIONING_DEMARRAGE": "Commissioning & Démarrage"
        }
        return phase_map.get(discipline, "Construction & Travaux Site")


# Instance Singleton
bpu_extractor = BPUExtractor()
bpu_converter = BPUPlanningConverter()
