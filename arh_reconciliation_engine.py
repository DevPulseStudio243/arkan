"""
arh_reconciliation_engine.py
============================
Moteur de Réconciliation Inter-Documents pour ARH Management.

Résout LE problème fondamental des dossiers ARH multi-pièces :
  Une pression de 74 bar sur la Fiche Descriptive et 70 bar sur la Note de Calcul
  = contradiction implicite → non-conformité critique INVISIBLE pour un agent mono-document.

Ce moteur :
  1. Extrait les paramètres clés de CHAQUE document du dossier.
  2. Construit une MATRICE DE RÉCONCILIATION par paramètre (qui dit quoi dans quel doc).
  3. Détecte les contradictions et les omissions critiques.
  4. Génère des remarques normalisées précisant les DEUX documents contradictoires.
  5. Vérifie la TRAÇABILITÉ des Numéros de Coulée (Heat Numbers) entre tous les docs.

Paramètres réconciliés :
  - Pression de Design (PMA) [bar]
  - Pression d'Épreuve Hydrostatique [bar]
  - Température de Design Min/Max [°C]
  - Matériau / Nuance d'Acier
  - Diamètre Nominal [mm ou pouces]
  - Épaisseur nominale [mm]
  - Surépaisseur de Corrosion [mm]
  - Numéro de Coulée (Heat Number)
  - Fluide de service
"""

from __future__ import annotations

import re
import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("ARHReconciliation")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION DES PARAMÈTRES À RÉCONCILIER
# ══════════════════════════════════════════════════════════════════════════════

# Tolérance de ±5% pour les valeurs numériques (ex: arrondis de conversion MPa ↔ bar)
NUMERIC_TOLERANCE_PCT = 0.05

# Champs obligatoires selon le type d'équipement
MANDATORY_FIELDS_BY_TYPE: Dict[str, List[str]] = {
    "PRESSURE_VESSEL":  ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "nominal_thickness_mm", "design_temp_max_c"],
    "SEPARATOR":        ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "nominal_thickness_mm", "design_temp_max_c"],
    "HEAT_EXCHANGER":   ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "nominal_thickness_mm"],
    "LINEPIPE":         ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "nominal_thickness_mm", "diameter_mm"],
    "PIPELINE":         ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "nominal_thickness_mm", "diameter_mm"],
    "BARRED_TEE":       ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec", "material_bars"],
    "VALVE":            ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec"],
    "TANK":             ["design_pressure_bar", "material_spec", "nominal_thickness_mm"],
    "SKID":             ["design_pressure_bar", "hydrotest_pressure_bar", "material_spec"],
    "ELECTRICAL":       [],   # Pas de paramètres mécaniques obligatoires
    "INSTRUMENTATION":  [],
}

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTEUR DE PARAMÈTRES PAR DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════

class ARHDocumentParameterExtractor:
    """
    Extrait les paramètres clés d'un document individuel sous forme de dictionnaire
    normalisé, prêt pour la réconciliation inter-documents.
    """

    def extract(self, text: str, file_name: str) -> Dict[str, Any]:
        """Retourne un dict {param: value} pour ce document."""
        tu = text.upper()
        params: Dict[str, Any] = {"_source_file": file_name}

        # ── Pression de Design ──
        params["design_pressure_bar"] = self._extract_pressure(tu, [
            "DESIGN PRESSURE", "PRESSION DE CALCUL", "PRESSION DE DESIGN",
            r"\bPMA\b", r"\bPMS\b"
        ])

        # ── Pression d'Épreuve ──
        params["hydrotest_pressure_bar"] = self._extract_pressure(tu, [
            "TEST PRESSURE", "PRESSION D'EPREUVE", "PRESSION D'ESSAI",
            "HYDROTEST PRESSURE", "HYDROSTATIC", "PRESSION HYDRAULIQUE"
        ])

        # ── Températures ──
        params["design_temp_max_c"] = self._extract_temp(tu, [
            "DESIGN TEMPERATURE", "TEMPERATURE DE CALCUL", "TEMPERATURE DE DESIGN",
            "MAX TEMP", "TEMPERATURE MAXI"
        ])
        params["design_temp_min_c"] = self._extract_temp(tu, [
            "MINIMUM DESIGN METAL TEMPERATURE", "MDMT", "TEMPERATURE MINIMALE",
            "MINIMUM TEMPERATURE", "TEMPERATURE MINI", "DESIGN TEMP MIN"
        ])

        # ── Matériau / Nuance ──
        params["material_spec"] = self._extract_material(tu)

        # ── Matériau des Barreaux (Barred Tee) ──
        params["material_bars"] = self._extract_bars_material(tu)

        # ── Diamètre ──
        params["diameter_mm"] = self._extract_diameter(tu)

        # ── Épaisseur Nominale ──
        params["nominal_thickness_mm"] = self._extract_thickness(tu, [
            "NOMINAL THICKNESS", "EPAISSEUR NOMINALE", "WT", "WALL THICKNESS",
            "THICKNESS"
        ])

        # ── Surépaisseur de Corrosion ──
        params["corrosion_allowance_mm"] = self._extract_thickness(tu, [
            "CORROSION ALLOWANCE", "SUREPAISSEUR DE CORROSION", r"\bC\.A\.\b"
        ])

        # ── Heat Numbers (Numéros de Coulée) ──
        params["heat_numbers"] = self._extract_heat_numbers(tu)

        # ── Fluide de Service ──
        params["service_fluid"] = self._extract_fluid(tu)

        # ── Classe de Bride ──
        params["flange_class"] = self._extract_flange_class(tu)

        return {k: v for k, v in params.items() if v is not None}

    # ─── Helpers d'extraction ────────────────────────────────────────────────

    def _extract_pressure(self, tu: str, keywords: List[str]) -> Optional[float]:
        for kw in keywords:
            pat = rf'(?:{kw})[^0-9\n]{{0,40}}?([\d]+(?:[\.,]\d+)?)\s*(MPA|BAR|BARS|KG/CM2)?'
            m = re.search(pat, tu)
            if m:
                try:
                    val = float(m.group(1).replace(",", "."))
                    unit = (m.group(2) or "BAR").strip()
                    if "MPA" in unit:
                        val *= 10.0
                    elif "KG/CM2" in unit:
                        val *= 0.981
                    if 0.1 <= val <= 1000:  # Sanity check
                        return round(val, 2)
                except ValueError:
                    pass
        return None

    def _extract_temp(self, tu: str, keywords: List[str]) -> Optional[float]:
        for kw in keywords:
            pat = rf'(?:{kw})[^0-9\-\n]{{0,40}}?(-?\s*[\d]+(?:[.,]\d+)?)\s*(?:°C|C\b|DEG C|°F|F\b)?'
            m = re.search(pat, tu)
            if m:
                try:
                    val_str = m.group(1).replace(" ", "").replace(",", ".")
                    val = float(val_str)
                    if -200 <= val <= 800:  # Plage physiquement plausible
                        return round(val, 1)
                except ValueError:
                    pass
        return None

    def _extract_material(self, tu: str) -> Optional[str]:
        # Ordre de spécificité décroissant
        material_patterns = [
            r'\bAPI\s*5L\s*(?:GR[.])?\s*[BX]\d+\b',  # API 5L X65, API 5L Gr B
            r'\bASTM\s*A\d+(?:\s+(?:GR[. ])?\w+)?\b',  # ASTM A350 LF2, ASTM A516 Gr 70
            r'\bSA[-–]\d+\b',                            # SA-516 Gr 70
            r'\bEN\s*10210\b',                           # EN 10210
            r'\bP265GH\b', r'\bS355J2H\b',              # Nuances EN
        ]
        for pat in material_patterns:
            m = re.search(pat, tu)
            if m:
                # Nettoyer et normaliser
                raw = m.group(0).strip()
                return " ".join(raw.split())  # Normaliser les espaces multiples
        return None

    def _extract_bars_material(self, tu: str) -> Optional[str]:
        """Matériau spécifique des barreaux dans un Barred Tee."""
        if "BARREAU" not in tu and "BAR MATERIAL" not in tu and "BARS MATERIAL" not in tu:
            return None
        m = re.search(r'(?:BARREAU[X]?|BARS?)\s*(?:MATERIAL|MATÉRIAU|MATIERE)\s*[:/]?\s*([A-Z0-9\s\-]+?)(?:\n|,|\.|;)', tu)
        if m:
            return m.group(1).strip()
        return None

    def _extract_diameter(self, tu: str) -> Optional[float]:
        """Extrait le diamètre en mm ou pouces (converti en mm)."""
        # Format DN en mm
        m_dn = re.search(r'\bDN\s*(\d+)\b', tu)
        if m_dn:
            return float(m_dn.group(1))

        # Format NPS en pouces → convertir en mm
        m_nps = re.search(r'\bNPS\s*(\d+(?:[.,]\d+)?)"?\b', tu)
        if m_nps:
            return round(float(m_nps.group(1).replace(",", ".")) * 25.4, 1)

        # Format " (pouces) direct → convertir en mm
        m_inch = re.search(r'\b(\d+(?:[.,]\d+)?)\s*(?:INCH|INCHES|")\b', tu)
        if m_inch:
            val = float(m_inch.group(1).replace(",", "."))
            if 1 <= val <= 72:  # Taille plausible d'une tuyauterie Oil & Gas
                return round(val * 25.4, 1)

        # Diamètre extérieur OD en mm
        m_od = re.search(r'\bO\.?D\.?\s*[=:]\s*(\d+(?:[.,]\d+)?)\s*MM\b', tu)
        if m_od:
            return float(m_od.group(1).replace(",", "."))

        return None

    def _extract_thickness(self, tu: str, keywords: List[str]) -> Optional[float]:
        for kw in keywords:
            pat = rf'(?:{kw})[^0-9\n]{{0,30}}?([\d]+(?:[.,]\d+)?)\s*MM\b'
            m = re.search(pat, tu)
            if m:
                try:
                    val = float(m.group(1).replace(",", "."))
                    if 0.5 <= val <= 150:  # Plage physiquement plausible
                        return round(val, 2)
                except ValueError:
                    pass
        return None

    def _extract_heat_numbers(self, tu: str) -> List[str]:
        """Extrait tous les numéros de coulée présents dans le document."""
        heat_numbers: List[str] = []
        patterns = [
            r'HEAT\s*N[O°\.]?\s*[:\-]?\s*([A-Z0-9]{3,20})',
            r'HEAT\s*NUMBER\s*[:\-]?\s*([A-Z0-9]{3,20})',
            r'COULÉE\s*N[O°\.]?\s*[:\-]?\s*([A-Z0-9]{3,20})',
            r'N[O°\.]\s*DE\s*COULÉE\s*[:\-]?\s*([A-Z0-9]{3,20})',
            r'\bHEAT\s*:\s*([A-Z0-9]{4,20})\b',
        ]
        for pat in patterns:
            for m in re.finditer(pat, tu):
                hn = m.group(1).strip()
                # Filtre anti-faux-positifs : exclure les mots réservés
                if hn not in ("THE", "AND", "FOR", "DES", "LES", "LE", "LA", "UN", "UNE"):
                    heat_numbers.append(hn)
        return list(set(heat_numbers))  # Dédupliquer

    def _extract_fluid(self, tu: str) -> Optional[str]:
        fluid_map = {
            "H2S": "SOUR GAS (H2S)",
            "SOUR GAS": "SOUR GAS (H2S)",
            "GAZ NATUREL": "GAZ NATUREL",
            "NATURAL GAS": "GAZ NATUREL",
            "CRUDE OIL": "PÉTROLE BRUT",
            "BRUT": "PÉTROLE BRUT",
            "CONDENSAT": "CONDENSAT",
            "GPL": "GPL",
            "LPG": "GPL",
            "EAU": "EAU",
            "WATER": "EAU",
            "FUEL GAS": "FUEL GAS",
        }
        for kw, label in fluid_map.items():
            if kw in tu:
                return label
        return None

    def _extract_flange_class(self, tu: str) -> Optional[int]:
        m = re.search(r'\b(?:CLASS|CL\.?|RATING)\s*(150|300|600|900|1500|2500)\b', tu)
        if m:
            return int(m.group(1))
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE RÉCONCILIATION PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class ARHReconciliationEngine:
    """
    Compare les paramètres extraits de tous les documents d'un dossier
    et détecte les contradictions et les omissions critiques.
    """

    def __init__(self):
        self.name = "Moteur de Réconciliation Inter-Documents"
        self.discipline = "RÉCONCILIATION"
        self.extractor = ARHDocumentParameterExtractor()

    def run_reconciliation(
        self,
        docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Exécute la réconciliation complète du dossier.

        Returns:
            (findings, reconciliation_matrix)
            - findings: Liste de non-conformités détectées
            - reconciliation_matrix: Matrice complète des paramètres par document
        """
        findings: List[Dict[str, Any]] = []

        # Étape 1 : Extraire les paramètres de chaque document
        doc_params: List[Dict[str, Any]] = []
        for doc in docs:
            text = doc.get("text", "")
            fname = doc.get("file_name", "DOCUMENT INCONNU")
            if len(text.strip()) < 10:
                continue
            params = self.extractor.extract(text, fname)
            if len(params) > 1:  # Plus que juste le _source_file
                doc_params.append(params)


        if len(doc_params) < 2:
            logger.info("[ARH-Recon] Moins de 2 documents avec paramètres — réconciliation ignorée.")
            return [], {}

        # Étape 2 : Construire la matrice de réconciliation
        matrix: Dict[str, Dict[str, Any]] = {}
        for params in doc_params:
            fname = params["_source_file"]
            for key, val in params.items():
                if key.startswith("_") or val is None:
                    continue
                if key not in matrix:
                    matrix[key] = {}
                matrix[key][fname] = val

        logger.info(f"[ARH-Recon] Matrice construite : {len(matrix)} paramètres, {len(doc_params)} documents.")

        # Étape 3 : Détection des contradictions numériques
        numeric_params = [
            "design_pressure_bar", "hydrotest_pressure_bar",
            "design_temp_max_c", "design_temp_min_c",
            "nominal_thickness_mm", "corrosion_allowance_mm",
            "diameter_mm", "flange_class"
        ]
        for param in numeric_params:
            if param in matrix and len(matrix[param]) >= 2:
                contradiction = self._detect_numeric_contradiction(matrix[param], param)
                if contradiction:
                    findings.append(contradiction)

        # Étape 4 : Détection des contradictions sur les matériaux
        if "material_spec" in matrix and len(matrix["material_spec"]) >= 2:
            mat_contradiction = self._detect_material_contradiction(matrix["material_spec"])
            if mat_contradiction:
                findings.append(mat_contradiction)

        # Étape 5 : Vérification traçabilité Heat Numbers
        if "heat_numbers" in matrix:
            hn_findings = self._check_heat_number_traceability(matrix["heat_numbers"])
            findings.extend(hn_findings)

        # Étape 6 : Champs obligatoires manquants
        mandatory_findings = self._check_mandatory_fields_missing(
            matrix, equipment_type, doc_params
        )
        findings.extend(mandatory_findings)

        # Étape 7 : Vérification "NON APPLICABLE" contextuel
        na_findings = self._check_na_validity(docs, equipment_type)
        findings.extend(na_findings)

        return findings, matrix

    # ─── Détection de contradictions numériques ──────────────────────────────

    def _detect_numeric_contradiction(
        self, param_values: Dict[str, float], param_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Détecte si deux documents déclarent des valeurs numériques incompatibles
        pour le même paramètre (au-delà de la tolérance de ±5%).
        """
        values = [(fname, val) for fname, val in param_values.items() if val is not None]
        if len(values) < 2:
            return None

        min_val = min(v for _, v in values)
        max_val = max(v for _, v in values)

        if min_val <= 0:
            return None

        deviation = (max_val - min_val) / min_val
        if deviation <= NUMERIC_TOLERANCE_PCT:
            return None  # Tolérance acceptable (arrondis)

        # Contradiction détectée
        details = "\n".join([
            f"  • '{fname}' : {val}"
            for fname, val in sorted(values, key=lambda x: x[1])
        ])
        param_labels = {
            "design_pressure_bar": "Pression de Design (PMA) [bar]",
            "hydrotest_pressure_bar": "Pression d'Épreuve Hydrostatique [bar]",
            "design_temp_max_c": "Température de Design Max [°C]",
            "design_temp_min_c": "Température de Design Min / MDMT [°C]",
            "nominal_thickness_mm": "Épaisseur Nominale [mm]",
            "corrosion_allowance_mm": "Surépaisseur de Corrosion [mm]",
            "diameter_mm": "Diamètre [mm]",
            "flange_class": "Classe de Bride (ASME Rating)",
        }
        label = param_labels.get(param_name, param_name)
        min_fname = min(values, key=lambda x: x[1])[0]
        max_fname = max(values, key=lambda x: x[1])[0]

        return {
            "id": f"REM_RECON_{uuid.uuid4().hex[:6].upper()}",
            "discipline": self.discipline,
            "agent": self.name,
            "priority": "CRITICAL",
            "category": "CONTRADICTION INTER-DOCUMENTS — PARAMÈTRE CRITIQUE",
            "title": f"Valeur Contradictoire de '{label}' entre {len(values)} Documents du Dossier",
            "observation": (
                f"Le paramètre '{label}' présente des valeurs incompatibles "
                f"(écart de {deviation*100:.1f}%, seuil de tolérance : {NUMERIC_TOLERANCE_PCT*100:.0f}%) "
                f"entre les documents suivants du dossier :\n{details}\n"
                f"La valeur minimale est dans '{min_fname}' et la valeur maximale dans '{max_fname}'."
            ),
            "decree_reference": "Décret exécutif n° 21-261 Art. 6 / Procédure P-CTE-1",
            "article": "Art. 6 (Cohérence des données de conception)",
            "standard": "ISO 9001:2015 Clause 7.5 / P-CTE-1",
            "document_concerned": f"{min_fname} ↔ {max_fname}",
            "page": "Paramètres de Conception",
            "impact": (
                f"Incohérence critique dans les données de conception. "
                f"Risque de sous-dimensionnement si la valeur minimale est appliquée à tort "
                f"pour le calcul réglementaire."
            ),
            "action_required": (
                f"Harmoniser le paramètre '{label}' dans tous les documents du dossier. "
                f"La valeur de référence doit être celle de la Fiche Descriptive (Annexe E) "
                f"approuvée par Sonatrach/GCB, reportée identiquement dans la note de calcul et le plan GA."
            ),
            "deadline_days": 3,
            "extracted_via": "ARHReconciliationEngine",
            "reconciliation_metadata": {
                "param": param_name,
                "values_by_doc": {fname: val for fname, val in values},
                "deviation_pct": round(deviation * 100, 2),
            }
        }

    # ─── Détection de contradictions matériaux ────────────────────────────────

    def _detect_material_contradiction(
        self, material_values: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """
        Détecte si deux documents déclarent des matériaux différents pour le même équipement.
        Distingue les vraies contradictions des mentions contextuelles normales.
        """
        # Normaliser les matériaux pour comparer apples to apples
        normalized: Dict[str, str] = {}
        for fname, mat in material_values.items():
            normalized[fname] = self._normalize_material(mat)

        unique_materials = set(normalized.values())
        if len(unique_materials) <= 1:
            return None  # Cohérent

        # Vérifier s'il s'agit de matériaux équivalents (ex: SA-516 Gr 70 ≈ ASTM A516 Gr 70)
        if self._are_materials_equivalent(unique_materials):
            return None

        details = "\n".join([f"  • '{fname}' : {mat}" for fname, mat in material_values.items()])

        return {
            "id": f"REM_RECON_MAT_{uuid.uuid4().hex[:6].upper()}",
            "discipline": self.discipline,
            "agent": self.name,
            "priority": "CRITICAL",
            "category": "CONTRADICTION INTER-DOCUMENTS — NUANCE D'ACIER",
            "title": f"Nuances d'Acier Contradictoires entre {len(material_values)} Documents",
            "observation": (
                f"Des nuances de matériau différentes et non équivalentes ont été trouvées "
                f"pour le même équipement dans les documents suivants :\n{details}\n"
                f"Cette incohérence peut conduire à une application de contraintes admissibles "
                f"ou de limites de température incorrectes dans la note de calcul."
            ),
            "decree_reference": "Décret exécutif n° 21-261 Art. 6 & Art. 12 / ASME Section II Part D",
            "article": "Art. 6 & Art. 12",
            "standard": "ASME Section II Part D / ASTM / API 5L",
            "document_concerned": " ↔ ".join(material_values.keys()),
            "page": "Fiche Descriptive / Note de Calcul / Plan GA Drawing",
            "impact": (
                "Risque de calcul d'épaisseur basé sur de mauvaises propriétés mécaniques "
                "(S, E) si le matériau utilisé dans la note de calcul diffère de celui commandé."
            ),
            "action_required": (
                "Harmoniser la désignation du matériau dans tous les documents. "
                "La nuance de référence est celle de la spécification de commande (MR) approuvée par GCB. "
                "Revoir la note de calcul si la nuance a changé."
            ),
            "deadline_days": 3,
            "extracted_via": "ARHReconciliationEngine",
        }

    def _normalize_material(self, mat: str) -> str:
        """Normalise les désignations de matériaux pour comparaison."""
        mat = mat.upper().strip()
        # SA-516 Gr 70 ≡ ASTM A516 Gr 70
        mat = mat.replace("SA-", "ASTM A").replace("SA ", "ASTM A")
        # Normaliser espaces
        mat = " ".join(mat.split())
        return mat

    def _are_materials_equivalent(self, materials: set) -> bool:
        """
        Vérifie si des matériaux différents en apparence sont réglementairement équivalents.
        """
        # Groupes d'équivalence connus
        equivalence_groups = [
            {"ASTM A516 GR 70", "ASTM A516 GR.70", "ASTM A516-70", "A516-70", "SA-516 GR 70"},
            {"ASTM A350 LF2", "A350 LF2", "ASTM A350 LF2 CL.1", "LF2"},
            {"API 5L X65", "API 5L GR X65", "API 5L GRADE X65", "L450"},
            {"API 5L X52", "API 5L GR X52", "API 5L GRADE X52", "L360"},
            {"ASTM A105", "A105", "A105N"},
        ]
        for group in equivalence_groups:
            if materials.issubset(group):
                return True
        return False

    # ─── Traçabilité Heat Numbers ─────────────────────────────────────────────

    def _check_heat_number_traceability(
        self, heat_number_values: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """
        Vérifie que les numéros de coulée sont cohérents entre tous les documents.
        Si le certificat 3.1 ou le plan GA mentionne H-85527 mais le carnet de soudage mentionne H-85528 →
        non-conformité critique.
        """
        findings = []

        # Identifier les documents sources certifiés / plans
        cert_docs = {fname: hns for fname, hns in heat_number_values.items()
                     if any(k in fname.upper() for k in ["CERT", "3.1", "MILL", "TEST REPORT", "MATERIAL", "PLAN", "GA", "DRAWING", "SPEC"])}
        welding_docs = {fname: hns for fname, hns in heat_number_values.items()
                        if any(k in fname.upper() for k in ["WELD", "SOUDAGE", "WPS", "CND", "NDT", "RADIO", "CARNET", "RAPPORT"])}

        if not cert_docs or not welding_docs:
            # Comparaison de secours si 2 documents quelconques déclarent des Heat Numbers disjoints
            doc_items = [(f, set(h)) for f, h in heat_number_values.items() if h]
            if len(doc_items) >= 2:
                doc1_name, hns1 = doc_items[0]
                doc2_name, hns2 = doc_items[1]
                if hns1 and hns2 and not hns1.intersection(hns2):
                    findings.append({
                        "id": f"REM_RECON_HN_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "TRAÇABILITÉ — NUMÉROS DE COULÉE (HEAT NUMBERS)",
                        "title": f"Incohérence des Numéros de Coulée entre '{doc1_name}' et '{doc2_name}'",
                        "observation": (
                            f"Les numéros de coulée déclarés dans '{doc1_name}' ({', '.join(sorted(hns1))}) "
                            f"ne correspondent pas à ceux trouvés dans '{doc2_name}' ({', '.join(sorted(hns2))}). "
                            f"Rupture de la chaîne de traçabilité matière."
                        ),
                        "decree_reference": "Décret exécutif n° 21-261 Art. 12 / Décret 21-315 Art. 14",
                        "article": "Art. 12 & Art. 14",
                        "standard": "EN 10204 3.1 / ASME Section IX / P-CTE-1",
                        "document_concerned": f"{doc1_name} ↔ {doc2_name}",
                        "page": "Plans / Carnet de Soudage / Certificats",
                        "impact": "Rupture de traçabilité matière — risque de mise en œuvre d'aciers non certifiés.",
                        "action_required": "Réconcilier les numéros de coulée entre le plan de fabrication, les certificats 3.1 et le carnet de soudage.",
                        "deadline_days": 3,
                        "extracted_via": "ARHReconciliationEngine",
                    })
            return findings

        # Construire le set de Heat Numbers de référence (certificats / plans)
        all_cert_hns = set()
        for hns in cert_docs.values():
            all_cert_hns.update(hns)

        all_weld_hns = set()
        for hns in welding_docs.values():
            all_weld_hns.update(hns)

        # Trouver les Heat Numbers dans le carnet de soudage sans certificat 3.1 / plan correspondant
        orphan_weld_hns = all_weld_hns - all_cert_hns
        if orphan_weld_hns:
            findings.append({
                "id": f"REM_RECON_HN_{uuid.uuid4().hex[:6].upper()}",
                "discipline": self.discipline,
                "agent": self.name,
                "priority": "CRITICAL",
                "category": "TRAÇABILITÉ — NUMÉROS DE COULÉE (HEAT NUMBERS)",
                "title": f"Numéros de Coulée dans le Carnet de Soudage Sans Certificat 3.1 Correspondant",
                "observation": (
                    f"Les numéros de coulée suivants sont référencés dans les documents de soudage/CND "
                    f"mais n'ont PAS de certificat matière EN 10204 3.1 correspondant dans le dossier :\n"
                    + "\n".join([f"  • Heat N° : {hn}" for hn in sorted(orphan_weld_hns)])
                ),
                "decree_reference": "Décret exécutif n° 21-261 Art. 12 / Décret 21-315 Art. 14",
                "article": "Art. 12 & Art. 14",
                "standard": "EN 10204 3.1 / ASME Section IX / P-CTE-1",
                "document_concerned": " + ".join(list(welding_docs.keys())[:2]),
                "page": "Carnet de Soudage / Rapport CND",
                "impact": (
                    "Impossibilité de vérifier les propriétés métallurgiques réelles "
                    "des matériaux soudés sur site. Risque de soudage de matériaux non certifiés."
                ),
                "action_required": (
                    f"Fournir les certificats matière EN 10204 3.1 pour les numéros de coulée manquants : "
                    + ", ".join(sorted(orphan_weld_hns))
                    + ". Ces certificats doivent être émis par le fabricant avec analyses chimiques et essais mécaniques."
                ),
                "deadline_days": 4,
                "extracted_via": "ARHReconciliationEngine",
            })

        return findings


    # ─── Champs obligatoires manquants ────────────────────────────────────────

    def _check_mandatory_fields_missing(
        self,
        matrix: Dict[str, Dict[str, Any]],
        equipment_type: str,
        doc_params: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Vérifie que tous les champs obligatoires pour ce type d'équipement
        sont renseignés dans AU MOINS un document du dossier.
        """
        findings = []
        mandatory = MANDATORY_FIELDS_BY_TYPE.get(equipment_type, MANDATORY_FIELDS_BY_TYPE.get("PRESSURE_VESSEL", []))

        field_labels = {
            "design_pressure_bar": "Pression de Design PMA [bar]",
            "hydrotest_pressure_bar": "Pression d'Épreuve Hydrostatique [bar]",
            "material_spec": "Nuance de Matériau",
            "nominal_thickness_mm": "Épaisseur Nominale [mm]",
            "design_temp_max_c": "Température de Design Max [°C]",
            "diameter_mm": "Diamètre Nominal [mm ou pouces]",
            "material_bars": "Matériau des Barreaux (Barred Tee)",
            "corrosion_allowance_mm": "Surépaisseur de Corrosion [mm]",
        }

        for field in mandatory:
            if field not in matrix or not matrix[field]:
                label = field_labels.get(field, field)
                findings.append({
                    "id": f"REM_RECON_MISS_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": self.discipline,
                    "agent": self.name,
                    "priority": "MAJOR",
                    "category": "PARAMÈTRE OBLIGATOIRE MANQUANT",
                    "title": f"Paramètre '{label}' Non Renseigné dans Aucun Document du Dossier",
                    "observation": (
                        f"Après analyse de {len(doc_params)} document(s) du dossier pour un équipement "
                        f"de type '{equipment_type}', le paramètre obligatoire '{label}' n'a pu "
                        f"être extrait d'aucun document. Ce paramètre est requis par la procédure "
                        f"ARH P-CTE-1 pour ce type d'équipement."
                    ),
                    "decree_reference": "Procédure ARH P-CTE-1 / Décret exécutif n° 21-261",
                    "article": "P-CTE-1 — Fiche Descriptive Obligatoire",
                    "standard": "P-CTE-1",
                    "document_concerned": "Fiche Descriptive (Annexe E) / Note de Calcul",
                    "page": "Fiche Descriptive",
                    "impact": "Dossier incomplet — paramètre de conception critique non vérifiable.",
                    "action_required": (
                        f"Renseigner explicitement le paramètre '{label}' dans la Fiche Descriptive "
                        f"(Annexe E / Etat Descriptif) et dans la Note de Calcul."
                    ),
                    "deadline_days": 5,
                    "extracted_via": "ARHReconciliationEngine",
                })

        return findings

    # ─── Validation contextuelle du "NON APPLICABLE" ─────────────────────────

    def _check_na_validity(
        self, docs: List[Dict[str, Any]], equipment_type: str
    ) -> List[Dict[str, Any]]:
        """
        Vérifie si les champs marqués 'NA' ou 'N/A' sont légitimement non applicables
        ou constituent une erreur (champ obligatoire non renseigné déguisé en NA).
        """
        findings = []

        # Types d'équipements sous pression qui DOIVENT avoir une PMA et une épaisseur
        ESP_TYPES = {
            "PRESSURE_VESSEL", "SEPARATOR", "HEAT_EXCHANGER", "COLUMN",
            "SPHERE", "SKID", "LINEPIPE", "PIPELINE", "COMPRESSOR"
        }
        # Types qui PEUVENT avoir NA pour les paramètres mécaniques
        NON_ESP_TYPES = {"ELECTRICAL", "INSTRUMENTATION", "BATTERY"}

        if equipment_type in NON_ESP_TYPES:
            return findings  # NA est normal pour les équipements non-mécaniques

        if equipment_type not in ESP_TYPES:
            return findings  # Type inconnu, on ne génère pas de faux positif

        # Champs critiques pour ESP
        CRITICAL_ESP_FIELDS = [
            ("PRESSION DE CALCUL", "Pression de Design (PMA)"),
            ("PRESSION D'ESSAI", "Pression d'Épreuve Hydrostatique"),
            ("MATERIAUX UTILISES", "Matériaux Utilisés"),
            ("EPAISSEUR", "Épaisseur des Parois"),
        ]

        for doc in docs:
            text = doc.get("text", "")
            fname = doc.get("file_name", "")
            tu = text.upper()

            # Chercher uniquement dans les fiches descriptives / Annexe E
            is_descriptive_sheet = any(k in tu for k in [
                "ETAT DESCRIPTIF", "FICHE DESCRIPTIVE", "DESCRIPTIVE SHEET",
                "ANNEXE E", "ANNEX E", "DATA SHEET"
            ])
            if not is_descriptive_sheet:
                continue

            for field_pattern, field_label in CRITICAL_ESP_FIELDS:
                # Chercher le pattern "Champ : NA" ou "Champ = N/A"
                na_pattern = rf'{re.escape(field_pattern)}\s*[:/=]?\s*(?:N/?A|NA|N\.A\.|–|—|\-)\b'
                if re.search(na_pattern, tu):
                    findings.append({
                        "id": f"REM_RECON_NA_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "CHAMP OBLIGATOIRE INCORRECTEMENT MARQUÉ 'NON APPLICABLE'",
                        "title": f"Champ Obligatoire '{field_label}' Marqué 'NA' sur une Fiche Descriptive ESP",
                        "observation": (
                            f"Dans la fiche descriptive (Annexe E) du document '{fname}', "
                            f"le champ '{field_label}' est renseigné comme 'NA' ou 'N/A'. "
                            f"Pour un équipement de type '{equipment_type}', ce paramètre est "
                            f"OBLIGATOIRE selon la procédure P-CTE-1. Un 'NA' ne peut être "
                            f"accepté que pour les équipements électriques (batteries, panneaux) "
                            f"qui n'ont pas de paramètres mécaniques sous pression."
                        ),
                        "decree_reference": "Procédure ARH P-CTE-1 / Décret exécutif n° 21-261 Art. 15",
                        "article": "P-CTE-1 Fiche Descriptive",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": "Fiche Descriptive / Annexe E",
                        "impact": (
                            "Paramètre de calcul manquant — impossible de vérifier le dimensionnement "
                            "réglementaire de l'équipement selon le Décret 21-261."
                        ),
                        "action_required": (
                            f"Renseigner la valeur réelle de '{field_label}' dans la fiche descriptive. "
                            f"'NA' est interdit pour ce paramètre sur un équipement ESP."
                        ),
                        "deadline_days": 3,
                        "extracted_via": "ARHReconciliationEngine",
                    })

        return findings


# Instance singleton réutilisable
arh_reconciliation_engine = ARHReconciliationEngine()
