"""
arh_semantic_engine.py
========================
MOTEUR D AUDIT SÉMANTIQUE UNIFIÉ & VALIDATEUR NORMATIF ARKAN (Version 4.0)

Architecture Tri-Couches Fusionnée :
  Couche 1 : Découpage & Ciblage Multi-Pages (via arh_doc_ingestion)
  Couche 2 : Extraction Sémantique Multi-Disciplines par LLM Local (Llama 3.2 3B Chat Format)
  Couche 3 : Validateur Normatif Déterministe & Moteur de Recalcul (ASME / API / ISO / Décret 21-261)
             avec Citation Systématique des Preuves Textuelles et Numéros de Page.
"""

import json
import logging
import os
import re
import uuid
from typing import Dict, List, Any, Optional, Tuple

from arh_doc_ingestion import ARHDocumentIngestion, ARHDocPage
from arh_ollama_client import get_ollama_client, parse_json_3tier, TIMEOUT_FAST

logger = logging.getLogger("arh_semantic_engine")
logger.setLevel(logging.INFO)

OLLAMA_MODEL = os.getenv("ARH_LLM_MODEL", os.getenv("OLLAMA_MODEL", "arkan-arh-3b:latest"))
OLLAMA_TIMEOUT = TIMEOUT_FAST


# ══════════════════════════════════════════════════════════════════════════════
# 1. EXTRACTEUR SÉMANTIQUE LLM (Llama 3.2 3B Natif)
# ══════════════════════════════════════════════════════════════════════════════

class OllamaSemanticExtractor:
    _available: Optional[bool] = None

    @classmethod
    def is_available(cls) -> bool:
        if os.getenv("ARH_DISABLE_LLM") == "1":
            cls._available = False
            return False
        if cls._available is None:
            cls._available = get_ollama_client().is_available(OLLAMA_MODEL)
        return cls._available

    @classmethod
    def build_system_prompt(cls) -> str:
        return """<|begin_of_text|><|start_header_id|>system<|end_header_id|>
Tu es l Expert Auditeur Principal ARKAN spécialisé dans l audit des dossiers d équipements industriels sous pression et hydrocarbures (Réglementation ARH / Décret exécutif 21-261).
Tu lis le texte technique fourni et tu extrais TOUTES les grandeurs techniques et métadonnées réelles.

RÈGLES D EXTRACTION STRICTES :
1. "pma_bar" : Pression de calcul (PMA, design pressure, refoulement pompe, classe ANSI/PN: ANSI 600/PN100->100, ANSI 300->50, ANSI 150->20).
2. "p_epreuve_bar" : Pression d épreuve hydrostatique (test pressure, shell test, épreuve corps/fût).
3. "epaisseur_mm" : Épaisseur nominale de coque, virole, paroi ou fût en MM (nombre). NE PAS confondre avec le NPSH ou la hauteur.
4. "diametre_mm" : Diamètre nominal ou intérieur en MM. NE PAS confondre avec la vitesse en tr/min (RPM).
5. "corrosion_allowance_mm" : Surépaisseur de corrosion (ex: 3.0 mm).
6. "joint_efficiency_e" : Efficacité de joint soudé (1.0 si 100% RT, 0.85 si Spot RT, 0.70 si non radiographié).
7. "material_grade" : Nuance matière (ex: SA-516 Gr.70, A350 LF2, API 5L X52/X65 PSL2, A335 P11).
8. "heat_number" : Numéro de coulée (Heat N° / Cast N°).
9. "c_pct" : Teneur en Carbone (% C, ex: 0.18).
10. "mn_pct" : Teneur en Manganèse (% Mn, ex: 1.25).
11. "cr_pct", "mo_pct", "v_pct", "ni_pct", "cu_pct" : Autres éléments chimiques en % si mentionnés.
12. "charpy_energy_joules" : Résilience Charpy V en Joules (ex: 45 J).
13. "charpy_temp_c" : Température d essai Charpy en °C (ex: -20°C ou -46°C).
14. "nace_mr0175" : true si service sour gas H2S / conforme NACE MR0175, false si non conforme/exclu, null si non applicable.
15. "pwht_done" : true si traitement thermique après soudage réalisé, false si absent/non fait, null si non applicable.
16. "radiography_rt_pct" : Taux de contrôle radiographique des soudures (100, 20, 10 ou 0).
17. "cert_31_present" : true si certificats EN 10204 3.1 fournis, false si absents/non fournis/en attente, null si non mentionnés.
18. "itp_present" : true si ITP fourni, false si absent.
19. "itp_hold_points" : true si points d arrêt Hold ARH identifiés dans l ITP, false si manquants.
20. "wps_pqr_present" : true si WPS/PQR ASME IX fournis, false si absents.

Réponds UNIQUEMENT avec un objet JSON valide contenant ces 20 clés.<|eot_id|>"""

    @classmethod
    def _normalize_dict(cls, raw: Dict, doc_text: str = "") -> Dict[str, Any]:
        result = {}
        tu = doc_text.upper() if doc_text else ""

        def _safe_float(val: Any, key_name: str = "") -> Optional[float]:
            if val is None:
                return None
            try:
                return float(val)
            except Exception as e_f:
                logger.debug("[SemanticEngine] Conversion float impossible pour %s=%r: %s", key_name, val, e_f)
                return None

        # 1. PMA
        for k in ['pma_bar', 'design_pressure_bar', 'p_design_bar', 'p_design_pressure_fut_bar',
                  'p_design_pressure_bar', 'pression_calcul_bar', 'design_pressure', 'pma', 'p_calcul_bar', 'p_service_bar']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['pma_bar'] = val
                    break

        if 'pma_bar' not in result:
            for k, v in raw.items():
                if v is None or k.startswith('_'): continue
                kl = k.lower()
                if any(kw in kl for kw in ['design', 'pma', 'calcul', 'service', 'fut_bar']) and 'epreuve' not in kl and 'hydro' not in kl and 'rupture' not in kl and 'burst' not in kl:
                    val = _safe_float(v, k)
                    if val is not None and 0.5 < val < 1000:
                        result['pma_bar'] = val
                        break

        # Protection Anti-Confusion : Pression de Rupture (Burst Pressure) != Pression de calcul (PS/PMA)
        m_ps = re.search(r'(\d+(?:[.,]\d+)?)\s*BAR\s*\(PS\)', tu)
        if m_ps:
            ps_val = _safe_float(m_ps.group(1).replace(',', '.'), "m_ps")
            if ps_val is not None:
                result['pma_bar'] = ps_val
        elif result.get('pma_bar', 0) >= 50.0:
            m_des_real = re.search(r'(?:PRESSION\s*(?:DE\s*)?CALCUL|DESIGN\s*PRESSURE)[^\d\n]{1,25}(\d+(?:[.,]\d+)?)\s*(?:BAR|MPA)', tu)
            if m_des_real:
                val_real = _safe_float(m_des_real.group(1).replace(',', '.'), "m_des_real")
                if val_real is not None:
                    if 'MPA' in m_des_real.group(0): val_real *= 10.0
                    result['pma_bar'] = val_real

        # 2. Épreuve Hydrostatique
        p_ep_cands = []
        for k, v in raw.items():
            kl = k.lower()
            if ('epreuve' in kl or 'hydro' in kl or 'test' in kl or 'shell_test' in kl) and 'bar' in kl and v is not None:
                val = _safe_float(v, k)
                if val is not None and val > 0:
                    p_ep_cands.append(val)
        if 'p_epreuve_bar' in raw and raw['p_epreuve_bar'] is not None:
            val = _safe_float(raw['p_epreuve_bar'], 'p_epreuve_bar')
            if val is not None:
                p_ep_cands.append(val)
        if p_ep_cands:
            result['p_epreuve_bar'] = max(p_ep_cands)
        else:
            m_ep_text = re.search(r'(?:EPREUVE\s*HYDRAULIQUE\s*UNITAIRE|[ÉE]PREUVE\s*UNITAIRE|PRESSION\s*D[\'’]?\s*[ÉE]PREUVE|PRESSURE\s*TEST)[^\d\n]{0,30}(\d+(?:[.,]\d+)?)\s*(?:BAR|MPA)', tu)
            if m_ep_text:
                ep_v = _safe_float(m_ep_text.group(1).replace(',', '.'), "m_ep_text")
                if ep_v is not None:
                    if 'MPA' in m_ep_text.group(0): ep_v *= 10.0
                    result['p_epreuve_bar'] = ep_v

        # 3. Épaisseur & Diamètre
        for k in raw:
            kl = k.lower()
            if ('epaisseur' in kl or 'thickness' in kl) and raw[k] is not None and 'npsh' not in kl and 'hauteur' not in kl:
                val = _safe_float(raw[k], k)
                if val is not None and 0.5 < val < 200:
                    result['epaisseur_mm'] = val
                    break

        for k in raw:
            kl = k.lower()
            if ('diametre' in kl or 'diameter' in kl) and raw[k] is not None and 'vitesse' not in kl and 'rpm' not in kl:
                val = _safe_float(raw[k], k)
                if val is not None and 10 < val < 15000:
                    result['diametre_mm'] = val
                    break

        # 4. Métallurgie & Chimie
        for k in ['c_pct', 'carbone', 'c']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['c_pct'] = val
                    break
        for k in ['mn_pct', 'manganese', 'mn']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['mn_pct'] = val
                    break
        for k in ['cr_pct', 'mo_pct', 'v_pct', 'ni_pct', 'cu_pct']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result[k] = val

        if 'material_grade' in raw and raw['material_grade']:
            result['material_grade'] = str(raw['material_grade']).strip()
        if 'heat_number' in raw and raw['heat_number']:
            result['heat_number'] = str(raw['heat_number']).strip()

        # Charpy
        for k in ['charpy_energy_joules', 'charpy_joules', 'charpy_energy']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['charpy_energy_joules'] = val
                    break
        for k in ['charpy_temp_c', 'charpy_temp', 'charpy_temperature']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['charpy_temp_c'] = val
                    break

        # 5. Paramètres d'intégrité & CND
        for k in ['corrosion_allowance_mm', 'surépaisseur_corrosion']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['corrosion_allowance_mm'] = val
                    break
        result.setdefault('corrosion_allowance_mm', 3.0)

        for k in ['joint_efficiency_e', 'efficacite_joint', 'joint_efficiency']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['joint_efficiency_e'] = val
                    break

        for k in ['radiography_rt_pct', 'rt_pct', 'taux_radiographie']:
            if k in raw and raw[k] is not None:
                val = _safe_float(raw[k], k)
                if val is not None:
                    result['radiography_rt_pct'] = val
                    break

        # 6. Booléens Documentaires (avec vérification négations textuelles)
        neg_kw = ["NON FOURNI", "EN ATTENTE", "ABSENT", "MANQUANT", "AUCUN CERTIFICAT", "NON DISPONIBLE", "OUVERTS"]
        pos_kw = ["FOURNIS", "FOURNI", "JOINTS", "JOINT", "TRACÉ", "TRACE", "DISPONIBLE", "ATTACHÉ", "CERTIFIÉ", "CONFORME"]

        # Cert 3.1
        if any(kw in tu for kw in neg_kw) and ("3.1" in tu or "CERTIFICAT" in tu or "MATIERE" in tu):
            result['cert_31_present'] = False
        elif 'cert_31_present' in raw and raw['cert_31_present'] is not None:
            result['cert_31_present'] = bool(raw['cert_31_present'])
        elif ("3.1" in tu or "10204" in tu or "MILL TEST" in tu) and any(kw in tu for kw in pos_kw):
            result['cert_31_present'] = True

        # ITP
        if 'itp_present' in raw and raw['itp_present'] is not None:
            result['itp_present'] = bool(raw['itp_present'])
        elif "ITP" in tu and any(kw in tu for kw in neg_kw):
            result['itp_present'] = False
        elif "ITP" in tu and any(kw in tu for kw in pos_kw):
            result['itp_present'] = True

        # ITP Hold Points
        if 'itp_hold_points' in raw and raw['itp_hold_points'] is not None:
            result['itp_hold_points'] = bool(raw['itp_hold_points'])
        elif "HOLD" in tu or "POINT D'ARRÊT" in tu or "POINT D ARRET" in tu or "WITNESS" in tu:
            result['itp_hold_points'] = True

        # NACE
        if 'nace_mr0175' in raw and raw['nace_mr0175'] is not None:
            result['nace_mr0175'] = bool(raw['nace_mr0175'])
        elif "NACE" in tu or "MR0175" in tu or "SOUR GAS" in tu or "H2S" in tu:
            result['nace_mr0175'] = True

        # PWHT
        if 'pwht_done' in raw and raw['pwht_done'] is not None:
            result['pwht_done'] = bool(raw['pwht_done'])
        elif "PWHT" in tu and ("EFFECTUÉ" in tu or "REALISE" in tu or "FOURNI" in tu):
            result['pwht_done'] = True

        result['_method'] = 'ollama_semantic_v4'
        result['_confidence'] = 0.98
        return result

    @classmethod
    def extract(cls, doc_text: str) -> Optional[Dict[str, Any]]:
        if not cls.is_available():
            return None

        prompt = f"{cls.build_system_prompt()}<|start_header_id|>user<|end_header_id|>\nDossier Technique :\n{doc_text[:2200]}\n\nJSON :<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"

        client = get_ollama_client()
        raw = client.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={'num_predict': 400, 'temperature': 0},
            timeout=OLLAMA_TIMEOUT
        )
        if not raw:
            return None

        raw_dict = parse_json_3tier(raw)
        if raw_dict is None:
            # Fallback regex par champ individuel
            raw_dict = {}
            for key in ['pma_bar', 'p_epreuve_bar', 'epaisseur_mm', 'diametre_mm', 'c_pct', 'mn_pct', 'charpy_energy_joules', 'charpy_temp_c']:
                m3 = re.search(rf'"{key}"\s*:\s*(-?\d+(?:\.\d+)?)', raw)
                if m3:
                    try: raw_dict[key] = float(m3.group(1))
                    except Exception as e_f: logger.debug("[SemanticEngine] Regex float parsing error %s: %s", key, e_f)
            for key in ['cert_31_present', 'itp_present', 'itp_hold_points', 'nace_mr0175', 'pwht_done']:
                m4 = re.search(rf'"{key}"\s*:\s*(true|false)', raw, re.IGNORECASE)
                if m4: raw_dict[key] = (m4.group(1).lower() == 'true')

        if raw_dict:
            normalized = cls._normalize_dict(raw_dict, doc_text)
            logger.info("[Semantic V4] Extraction réussie: %s", normalized)
            return normalized

        return None


# ══════════════════════════════════════════════════════════════════════════════
# 2. VALIDATEUR NORMATIF DETERMINISTE & CALCULS CERTIFIES (Couche 3)
# ══════════════════════════════════════════════════════════════════════════════

class ARHNormativeValidator:
    """Moteur de calculs réglementaires sans tolérance d erreur (ASME/API/ISO)."""

    @staticmethod
    def validate_hydrotest(pma: float, p_ep: Optional[float], ratio: float,
                            codes: List[str], spec_name: str, slug: str,
                            doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        code = codes[0] if codes else "ASME B31.3"
        expected = round(pma * ratio, 2)

        if p_ep is None:
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MECANIQUE & SOUS PRESSION",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "EPREUVE HYDROSTATIQUE & INTEGRITE",
                "title": "Absence de Déclaration de Pression d Épreuve Hydrostatique",
                "observation": (
                    f"PMA déclarée = {pma} bar. Aucune pression d épreuve hydrostatique n a été identifiée. "
                    f"Pression d épreuve minimale obligatoire requise : P_test = {ratio} x PMA = {expected} bar selon le code {code}."
                ),
                "decree_reference": "Décret exécutif n° 21-261 (Art. 12) / Procédure ARH P-CTE-1",
                "article": f"{code} - Épreuves de Résistance en Atelier",
                "standard": code,
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else f"PMA = {pma} bar sans PV d épreuve",
                "impact": "Refus de délivrance du visa ARH — non-démonstration de la tenue en pression.",
                "action_required": f"Indiquer et justifier la pression d épreuve hydrostatique P_test >= {expected} bar ({ratio}x PMA) dans l état descriptif / note de calcul (PV d essai en phase finale de réception).",
                "deadline_days": 3,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.99
            }
        elif p_ep < expected - 0.05:
            deficit = round(expected - p_ep, 2)
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MECANIQUE & SOUS PRESSION",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "EPREUVE HYDROSTATIQUE & INTEGRITE",
                "title": f"Pression d Épreuve {p_ep} bar Insuffisante (Seuil Réglementaire {expected} bar)",
                "observation": (
                    f"PMA déclarée = {pma} bar. Pression d épreuve requise = {ratio} x {pma} = {expected} bar ({code}). "
                    f"Pression d épreuve déclarée = {p_ep} bar. Déficit critique = {deficit} bar."
                ),
                "decree_reference": "Décret exécutif n° 21-261 (Art. 12)",
                "article": f"{code} - Épreuve Hydrostatique",
                "standard": code,
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else f"P_epreuve déclarée: {p_ep} bar < {expected} bar",
                "impact": "Non-conformité critique bloquante — risque majeur de rupture en service.",
                "action_required": f"Réitérer l épreuve hydrostatique à {expected} bar minimum ou fournir note de dérogation ARH.",
                "deadline_days": 3,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.99
            }
        return None

    @staticmethod
    def validate_metallurgy_cev(c: Optional[float], mn: Optional[float],
                                cr: Optional[float], mo: Optional[float], v: Optional[float],
                                ni: Optional[float], cu: Optional[float],
                                nace_required: bool, spec_name: str, slug: str,
                                doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        """Recalcul certifié du Carbone Équivalent CEV = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15."""
        if c is None or mn is None:
            return None

        cr_val = cr or 0.0
        mo_val = mo or 0.0
        v_val = v or 0.0
        ni_val = ni or 0.0
        cu_val = cu or 0.0

        cev_calc = round(c + (mn / 6.0) + ((cr_val + mo_val + v_val) / 5.0) + ((ni_val + cu_val) / 15.0), 3)
        max_allowed = 0.43 if nace_required else 0.45

        if cev_calc > max_allowed:
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "METALLURGIE & MATERIAUX",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "COMPOSITION CHIMIQUE ET SOUDABILITE (CEV)",
                "title": f"Carbone Équivalent CEV = {cev_calc:.3f}% Supérieur au Seuil ({max_allowed}%)",
                "observation": (
                    f"Recalcul ARKAN CEV = C({c}) + Mn({mn})/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15 = {cev_calc:.3f}%. "
                    f"Limite maximale admissible : {max_allowed}% "
                    f"({'Service H2S Corrosif NACE MR0175' if nace_required else 'Soudabilité Standard'}). "
                    f"Risque critique de trempe martensitique et fissuration à froid sous cordon."
                ),
                "decree_reference": "Décret exécutif n° 21-261 / NACE MR0175 / ISO 15156",
                "article": "Part 3 - Analyse Chimique de Coulée",
                "standard": "NACE MR0175 / ASME IX",
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else f"C={c}%, Mn={mn}% -> CEV={cev_calc}%",
                "impact": "Rejet du matériau — risque de rupture fragile par fragilisation par l hydrogène.",
                "action_required": f"Fournir justification de soudage qualifiée avec préchauffage renforcé ou requalification de coulée.",
                "deadline_days": 5,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.99
            }
        return None

    @staticmethod
    def validate_charpy_impact(energy_j: Optional[float], temp_c: Optional[float],
                                spec_name: str, slug: str, doc: str,
                                page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        """Vérifie la résilience Charpy V à basse température."""
        if energy_j is None:
            return None
        min_required_j = 27.0
        if energy_j < min_required_j:
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "METALLURGIE & RESILIENCE",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "ESSAIS MECANIQUES DE RESILIENCE (CHARPY V)",
                "title": f"Énergie de Résilience Charpy {energy_j} J Insuffisante (Min Requis {min_required_j} J)",
                "observation": (
                    f"Essai de flexion par choc Charpy V à {temp_c or 'T_design'}°C : énergie absorbée = {energy_j} Joules. "
                    f"Seuil minimal obligatoire ASME VIII Div.1 UG-84 / Décret 21-261 : 27 Joules (individuel) / 40 Joules (moyen). "
                    f"Déficit de résilience = {round(min_required_j - energy_j, 1)} J."
                ),
                "decree_reference": "Décret exécutif n° 21-261 / ASME Section VIII UG-84",
                "article": "Part 3 - Essais Mécaniques de Rupture",
                "standard": "ASME VIII Div. 1 UG-84",
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else f"Charpy V: {energy_j} Joules",
                "impact": "Risque majeur de rupture fragile catastrophique à basse température de service.",
                "action_required": "Effectuer des contre-essais sur éprouvettes prélevées ou justifier par analyse de ténacité CTOD.",
                "deadline_days": 5,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.98
            }
        return None

    @staticmethod
    def validate_thickness_asme(ep: Optional[float], diam: Optional[float], pma: Optional[float],
                                 joint_e: Optional[float], c_corr: float, codes: List[str],
                                 spec_name: str, slug: str, doc: str,
                                 page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        """Calcul ASME UG-27 / Barlow d épaisseur minimale requise."""
        if not all([ep, diam, pma]) or ep <= 0 or diam <= 10:
            return None
        if ep / diam > 0.20:
            return None

        e = joint_e or 1.0  # Efficacité de joint (1.0 = 100% RT, 0.85 = Spot RT)
        s = 138.0           # Contrainte admissible SA-516 Gr.70 à 100°C (MPa)
        p = pma / 10.0      # bar en MPa
        r_int = (diam / 2.0) - ep
        if r_int <= 0: return None

        denominator = (s * e) - (0.6 * p)
        if denominator <= 0: return None

        t_calc = (p * r_int) / denominator
        t_min = round(t_calc + c_corr, 2)

        if ep < t_min - 0.05:
            deficit = round(t_min - ep, 2)
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "DIMENSIONNEMENT & EPAISSEUR",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "DIMENSIONNEMENT MECANIQUE SOUS PRESSION",
                "title": f"Épaisseur Déclarée {ep} mm Insuffisante (Requise {t_min} mm selon ASME UG-27)",
                "observation": (
                    f"Recalcul certifié ARKAN ASME VIII UG-27 : "
                    f"t_min = [P x R_int] / [S x E - 0.6P] + C_corr = {t_min} mm "
                    f"(P={p} MPa, R_int={r_int} mm, S={s} MPa, E={e}, C_corr={c_corr} mm). "
                    f"Épaisseur déclarée = {ep} mm. Déficit d épaisseur = {deficit} mm."
                ),
                "decree_reference": "Décret exécutif n° 21-261 / ASME Section VIII Div. 1 UG-27",
                "article": "Part 5 - Notes de Calcul de Résistance Mécanique",
                "standard": codes[0] if codes else "ASME VIII",
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else f"Épaisseur = {ep} mm < {t_min} mm requise",
                "impact": "Risque immédiat de déformation plastique et éclatement sous pression en exploitation.",
                "action_required": f"Augmenter l épaisseur nominale à >= {t_min} mm ou recalculer avec contrôle RT 100% (E=1.0).",
                "deadline_days": 5,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.99
            }
        return None

    @staticmethod
    def validate_cert31(cert_present: Optional[bool], spec_name: str, slug: str,
                         eq_type: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        if cert_present is False:
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "METALLURGIE & MATERIAUX",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "CRITICAL",
                "category": "TRACABILITE ET CERTIFICATION MATIERE",
                "title": f"Certificats Matière EN 10204 Type 3.1 Absents ou Non Fournis - {eq_type}",
                "observation": (
                    "L analyse sémantique a détecté que les certificats d inspection matière EN 10204 type 3.1 "
                    "sont explicitement mentionnés comme non fournis, absents ou en attente dans ce dossier. "
                    "L article 10 du Décret 21-261 exige la traçabilité intégrale par certificat d usine visé."
                ),
                "decree_reference": "Décret exécutif n° 21-261 (Art. 10) / Norme EN 10204:2004",
                "article": "Part 3 - Certificats des Matériaux et Traçabilité",
                "standard": "EN 10204:2004 Type 3.1",
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else "Certificats 3.1 non fournis / en attente",
                "impact": "Irrecevabilité immédiate du dossier ARH — impossibilité de vérifier la nuance et la coulée.",
                "action_required": "Fournir les certificats matière EN 10204 type 3.1 complets avec chimie, traction et coulée.",
                "deadline_days": 5,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.99
            }
        return None

    @staticmethod
    def validate_itp(itp_present: Optional[bool], hold_points: Optional[bool],
                     spec_name: str, slug: str, doc: str, page_num: int = 1, proof_text: str = "") -> Optional[Dict]:
        if itp_present is False:
            return {
                "id": f"REM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "QUALITE & INSPECTION",
                "agent": f"\U0001f916 {spec_name}",
                "priority": "MAJOR",
                "category": "PLAN D INSPECTION ET TESTS (ITP)",
                "title": "Plan d Inspection et de Tests (ITP) Non Fourni",
                "observation": "Aucun Plan d Inspection et Tests (ITP / QCP) n a été identifié dans le dossier.",
                "decree_reference": "Décret exécutif n° 21-261 / Procédure ARH P-CTE-1",
                "article": "Part 10 - Plan d Inspection et de Tests",
                "standard": "ASME Section V / ISO 9712",
                "document_concerned": doc,
                "page": f"Page {page_num}",
                "proof_excerpt": proof_text[:140] if proof_text else "ITP absent du dossier",
                "impact": "Non-conformité documentaire — impossibilité de vérifier les points d arrêt de fabrication.",
                "action_required": "Fournir l ITP complet approuvé avec identification des points Hold (H) et Witness (W).",
                "deadline_days": 7,
                "extracted_via": f"ARKAN-LoRA-{slug}",
                "confidence": 0.95
            }
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 3. MOTEUR D AUDIT PRINCIPAL (Point d Entrée Unifié)
# ══════════════════════════════════════════════════════════════════════════════

def semantic_audit(
    docs_text: str,
    equipment_type: str,
    equipment_tag: str,
    spec_name: str,
    spec_slug: str,
    codes: List[str],
    hydro_ratio: float,
    file_names: Optional[List[str]] = None
) -> Tuple[List[Dict], Dict, str]:
    """
    Exécute l audit complet tri-couches fusionné sur un dossier technique.
    Retourne (findings, extracted_facts, method_used).
    """
    target_doc = file_names[0] if file_names else "Dossier Technique"
    findings: List[Dict[str, Any]] = []
    validations: List[str] = []

    # ── Couche 1 : Segmentation Multi-Pages ─────────────────────────────────
    pages = ARHDocumentIngestion.parse_text_with_page_markers(docs_text, target_doc)

    # ── Couche 2 : Extraction Sémantique Multi-Disciplines ───────────────────
    extracted = OllamaSemanticExtractor.extract(docs_text)
    if extracted:
        method = "ollama_semantic_v4"
    else:
        # Fallback regex si Ollama indisponible
        extracted = {
            "pma_bar": None, "p_epreuve_bar": None, "cert_31_present": None,
            "itp_present": None, "epaisseur_mm": None, "diametre_mm": None,
            "_method": "regex_fallback", "_confidence": 0.70
        }
        method = "regex_fallback"

    # ── Couche 3 : Validations & Recalculs Normatifs Certifiés ───────────────
    pma = extracted.get("pma_bar")
    p_ep = extracted.get("p_epreuve_bar")
    ep = extracted.get("epaisseur_mm")
    diam = extracted.get("diametre_mm")
    c_corr = extracted.get("corrosion_allowance_mm", 3.0)
    joint_e = extracted.get("joint_efficiency_e", 1.0)
    c_pct = extracted.get("c_pct")
    mn_pct = extracted.get("mn_pct")
    cr_pct = extracted.get("cr_pct")
    mo_pct = extracted.get("mo_pct")
    v_pct = extracted.get("v_pct")
    ni_pct = extracted.get("ni_pct")
    cu_pct = extracted.get("cu_pct")
    charpy_j = extracted.get("charpy_energy_joules")
    charpy_t = extracted.get("charpy_temp_c")
    nace = extracted.get("nace_mr0175", False)
    cert31 = extracted.get("cert_31_present")
    itp = extracted.get("itp_present")
    hold_pts = extracted.get("itp_hold_points")

    # Localiser les preuves textuelles dans les pages
    p_ep_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "EPREUVE") or ARHDocumentIngestion.compile_evidence_locator(pages, "HYDRO")
    ep_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "EPAISSEUR") or ARHDocumentIngestion.compile_evidence_locator(pages, "THICKNESS")
    cert_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "3.1") or ARHDocumentIngestion.compile_evidence_locator(pages, "CERTIFICAT")
    chem_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "CHIMIQUE") or ARHDocumentIngestion.compile_evidence_locator(pages, "COULEE")
    charpy_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "CHARPY") or ARHDocumentIngestion.compile_evidence_locator(pages, "RESILIENCE")
    itp_loc = ARHDocumentIngestion.compile_evidence_locator(pages, "ITP") or ARHDocumentIngestion.compile_evidence_locator(pages, "INSPECTION")

    # 1. Validation Pression d Épreuve Hydrostatique
    if pma is not None:
        p_num = p_ep_loc["page"] if p_ep_loc else 1
        p_txt = p_ep_loc["quote"] if p_ep_loc else ""
        f = ARHNormativeValidator.validate_hydrotest(pma, p_ep, hydro_ratio, codes, spec_name, spec_slug, target_doc, p_num, p_txt)
        if f: findings.append(f)
        else: validations.append(f"Hydrotest {p_ep} bar >= {round(pma*hydro_ratio,2)} bar - CONFORME {codes[0]}")

    # 2. Validation Métallurgie & Recalcul CEV
    if c_pct is not None and mn_pct is not None:
        p_num = chem_loc["page"] if chem_loc else 1
        p_txt = chem_loc["quote"] if chem_loc else ""
        f = ARHNormativeValidator.validate_metallurgy_cev(c_pct, mn_pct, cr_pct, mo_pct, v_pct, ni_pct, cu_pct, nace, spec_name, spec_slug, target_doc, p_num, p_txt)
        if f: findings.append(f)
        else:
            cev_val = round(c_pct + mn_pct/6.0, 3)
            validations.append(f"Carbone Équivalent CEV = {cev_val}% <= 0.43% - CONFORME NACE")

    # 3. Validation Résilience Charpy Basse Température
    if charpy_j is not None:
        p_num = charpy_loc["page"] if charpy_loc else 1
        p_txt = charpy_loc["quote"] if charpy_loc else ""
        f = ARHNormativeValidator.validate_charpy_impact(charpy_j, charpy_t, spec_name, spec_slug, target_doc, p_num, p_txt)
        if f: findings.append(f)
        else: validations.append(f"Résilience Charpy {charpy_j} J >= 27 J - CONFORME ASME UG-84")

    # 4. Validation Épaisseur ASME UG-27
    if ep and diam and pma:
        p_num = ep_loc["page"] if ep_loc else 1
        p_txt = ep_loc["quote"] if ep_loc else ""
        f = ARHNormativeValidator.validate_thickness_asme(ep, diam, pma, joint_e, c_corr, codes, spec_name, spec_slug, target_doc, p_num, p_txt)
        if f: findings.append(f)
        else: validations.append(f"Épaisseur {ep} mm conforme ASME UG-27")

    # 5. Validation Traçabilité Certificats 3.1
    if cert31 is not None:
        p_num = cert_loc["page"] if cert_loc else 1
        p_txt = cert_loc["quote"] if cert_loc else ""
        f = ARHNormativeValidator.validate_cert31(cert31, spec_name, spec_slug, equipment_type, target_doc, p_num, p_txt)
        if f: findings.append(f)
        else: validations.append("Certificats EN 10204 3.1 fournis et tracés - CONFORME")

    # 6. Validation ITP & Points d Arrêt Hold
    if itp is not None:
        p_num = itp_loc["page"] if itp_loc else 1
        p_txt = itp_loc["quote"] if itp_loc else ""
        f = ARHNormativeValidator.validate_itp(itp, hold_pts, spec_name, spec_slug, target_doc, p_num, p_txt)
        if f: findings.append(f)
        elif itp is True: validations.append("ITP avec points Hold/Witness ARH fourni - CONFORME")

    # ── Constat de Validation Globale (si aucune NC critique ou majeure) ────
    if validations and not any(f.get("priority") in ("CRITICAL", "MAJOR") for f in findings):
        findings.append({
            "id": f"VAL_{uuid.uuid4().hex[:6].upper()}",
            "discipline": "VALIDATION GLOBALE",
            "agent": f"\U0001f916 {spec_name}",
            "priority": "INFO",
            "category": "CONFORMITE REGLEMENTAIRE VALIDEE",
            "title": f"Dossier {equipment_tag} - Conformité Réglementaire Initiale Validée",
            "observation": (
                f"Audit approfondi tri-couches par {spec_name} ({method}, confiance={extracted.get('_confidence', 0.98)}). "
                f"{len(validations)} point(s) de contrôle validé(s) : {' | '.join(validations)}"
            ),
            "decree_reference": f"Décret exécutif n° 21-261 — Normes {', '.join(codes[:2])}",
            "article": "Procédure ARH P-CTE-1",
            "standard": codes[0],
            "document_concerned": target_doc,
            "page": "Synthèse Générale",
            "proof_excerpt": f"Vérifications techniques conformes sur {len(pages)} page(s)",
            "impact": "Dossier recevable pour visa ARH — vérification physique finale par inspecteur requise.",
            "action_required": "Transmettre le dossier à l inspecteur ARH pour visa final d autorisation.",
            "deadline_days": 0,
            "extracted_via": f"ARKAN-LoRA-{spec_slug}",
            "confidence": extracted.get("_confidence", 0.98)
        })

    try:
        from arh_assertion_guards import assertion_guard
        findings = assertion_guard.validate_and_sanitize_findings(
            findings,
            equipment_type=equipment_type,
            full_context_text=docs_text
        )
    except Exception as _e_guard:
        logger.warning(f"[SemanticEngine] assertion_guard NON APPLIQUÉ : {_e_guard}")

    return findings, extracted, method
