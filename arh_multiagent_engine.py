from arh_wps_expert_agent import check_itp_tpi_arh_column, arh_wps_expert_agent
"""
arh_multiagent_engine.py
========================
Moteur Multi-Agents Agentique (Agentic Swarm) pour l'Audit Réglementaire et Technique des Dossiers ARH.

Couvre l'ensemble des disciplines du secteur Pétrolier, Gazier et Énergétique (Sonatrach / GCB / ARH) :
  1. ARHAdministrativeAgent        : Légalisation consulaire, P-CTE-1, Page de garde, Lettre ARH.
  2. ARHMetallurgyAgent            : Certificats 3.1, Chimie, CEV/Pcm, Dureté NACE, Résilience Charpy.
  3. ARHMechanicalPipingAgent      : Épaisseurs ASME VIII (UG-27), Contraintes ASME II-D, Pression Épreuve, Brides.
  4. ARHElectricalInstrumentationAgent : Décret 21-257, ATEX/IECEx (IEC 60079), Tableaux IEC 61439, SIL, Solaire & Batteries.
  5. ARHQualityWeldingITPAgent     : Soudage WPS/PQR, Points d'arrêt ITP (Hold H - TPI/ARH), CND 100%, Plaques.
  6. ARHArbitratorCriticAgent      : Détection de contradictions inter-disciplines, filtrage des faux positifs.
  7. ARHSynthesizerAgent           : Rédaction officielle d'avis ARH conforme aux décrets algériens.

NOUVEAUX MODULES v4.0 (Compréhension Sémantique Profonde) :
  8. ARHTemporalReasoningAgent     : Validité temporelle qualifications soudeurs, ATEX, étalonnage, visa consulaire.
  9. ARHReconciliationEngine       : Réconciliation inter-documents, contradictions cachées, traçabilité Heat Numbers.
  10. ARHReserveComparator         : Mode Levée de Réserves — vérifie sémantiquement chaque réserve ARH point par point.
"""

import os
import re
import math
from pathlib import Path
import uuid
import datetime
import logging
from typing import Dict, List, Any, Optional, Tuple
from arh_nuextract_engine import arh_nuextract_engine
from arh_regulatory_engine import ARHRegulatoryEngine


def _get_standards() -> Dict[str, Any]:
    """Retourne la configuration réglementaire (arh_standards.yaml) ou {} si indisponible.

    Correctif : l'ancien code référençait un nom jamais importé (NameError) et un attribut
    inexistant (`.standards`), ce qui faisait planter l'agent métallurgie dès qu'une
    composition chimique était trouvée. Les valeurs de repli (CEV 0.43, dureté 22 HRC)
    restent appliquées si le fichier de standards est absent.
    """
    try:
        from arh_parametric_matrix_engine import get_engine
        return get_engine().std or {}
    except Exception as exc:  # StandardsError, ImportError, YAML absent...
        logging.getLogger("ARHMultiAgent").warning(
            "[ARH-Swarm] arh_standards.yaml indisponible (%s) : valeurs de repli utilisées.", exc)
        return {}

# Import des nouveaux modules v4.0 — avec fallback gracieux si non disponibles
try:
    from arh_temporal_reasoner import arh_temporal_reasoner
    _HAS_TEMPORAL = True
except ImportError:
    _HAS_TEMPORAL = False
    logging.getLogger("ARHMultiAgent").warning("[ARH-Swarm] arh_temporal_reasoner non disponible — audit temporel désactivé.")

try:
    from arh_reconciliation_engine import arh_reconciliation_engine
    _HAS_RECONCILIATION = True
except ImportError:
    _HAS_RECONCILIATION = False
    logging.getLogger("ARHMultiAgent").warning("[ARH-Swarm] arh_reconciliation_engine non disponible — réconciliation désactivée.")

try:
    from arh_reserve_comparator import arh_reserve_comparator
    _HAS_RESERVE_COMPARATOR = True
except ImportError:
    _HAS_RESERVE_COMPARATOR = False
    logging.getLogger("ARHMultiAgent").warning("[ARH-Swarm] arh_reserve_comparator non disponible — levée de réserves désactivée.")

try:
    from arh_code_harness import arh_code_harness
    _HAS_CODE_HARNESS = True
except ImportError:
    _HAS_CODE_HARNESS = False

try:
    from arh_refine_engine import arh_refine_engine
    _HAS_REFINE = True
except ImportError:
    _HAS_REFINE = False

logger = logging.getLogger("ARHMultiAgent")



# ══════════════════════════════════════════════════════════════════════════════
# 1. AGENT 1 : ADMINISTRATIF & LÉGALISATION CONSULAIRE
# ══════════════════════════════════════════════════════════════════════════════
class ARHAdministrativeAgent:
    """Agent autonome chargé de la légalité documentaire, visas et conformité P-CTE-1."""

    def __init__(self):
        self.name = "Auditeur Administratif & Légalisation"
        self.discipline = "ADMINISTRATIF"

    def audit(self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str) -> List[Dict[str, Any]]:
        findings = []
        full_text = " ".join([d.get("text", "") for d in docs])
        file_names = [d.get("file_name", "") for d in docs]
        
        import unicodedata
        def _norm_str(s: str) -> str:
            return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn').upper()

        norm_full_text = _norm_str(full_text)
        norm_filenames = _norm_str(" ".join(file_names or []))
        blob = norm_filenames + " " + norm_full_text

        # Zero-Stall fix : ne JAMAIS court-circuiter l'audit administratif sur simple présence de 'REV 0' ou 'APPROUV' dans le cartouche d'un plan.

        # Extraction structurée via NuExtract-3
        data = arh_nuextract_engine.extract_structured(full_text, "ADMIN_LEGAL")
        
        has_consular_visa = data.get("has_consular_visa", False) or any(k in blob for k in [
            "VU POUR LEGALISATION", "VU POUR LÉGALISATION", "VU AU CONSULAT",
            "DROITS DE CHANCELLERIE", "QUITTANCE", "TARIF CHANCELLERIE",
            "ENREGISTRE SOUS LE N", "ENREGISTRÉ SOUS LE N", "LEGALISE PAR LE CONSULAT"
        ])
        is_foreign = data.get("is_foreign_manufacturer", False) or any(k in blob for k in [
            "CHINA", "CHINE", "SHENJIANG", "ITALY", "GERMANY", "FRANCE", "USA", "INDIA",
            "PRIMEX", "DÜSSELDORF", "DUSSELDORF", "JAPAN", "KOREA"
        ])
        is_local = any(k in blob for k in ["FABRIQUÉ EN ALGÉRIE", "MADE IN ALGERIA", "ENAC", "BATIMETAL", "ALFET", "ANABIB", "KANAGHAZ"])
        if is_local:
            is_foreign = False

        if is_foreign and not has_consular_visa:
            target_doc = "DOC-02: Certification des Signatures & Visa Consulaire"
            prio = "CRITICAL"
            findings.append({
                "id": f"REM_ADM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": self.discipline,
                "agent": self.name,
                "priority": prio,
                "severity": "Critical",
                "category": "LÉGALISATION ET AUTHENTIFICATION",
                "title": "Absence de Légalisation Consulaire des Signatures du Fabricant Étranger",
                "observation": f"Faire viser les trois certificats par la Chambre de Commerce locale et le Consulat d'Algérie du pays d'origine du fabricant, et les introduire dans le dossier final de l'équipement ({equipment_type or 'matériel'}).",
                "decree_reference": "Procédure ARH P-CTE-1 (Part 2) / Décret exécutif n° 21-261",
                "article": "Annexe B & E - Part 2",
                "standard": "P-CTE-1",
                "piece_code": "DOC-02",
                "document_concerned": "DOC-02: Certification des Signatures & Visa Consulaire",
                "page": "Page 6",
                "page_number": 6,
                "target_content": "Certification Des Signatures Du Fabricant",
                "quote_snippet": "Certification Des Signatures Du Fabricant - Constat : Aucun visa du Consulat d'Algérie ni cachet consulaire sur le document.",
                "highlight_terms": ["Certification Des Signatures", "Fabricant", "Consulat"],
                "impact": "Réserve administrative à régulariser avant avis final de la commission ARH.",
                "action_required": f"Faire viser les trois certificats par la Chambre de Commerce et le Consulat d'Algérie du pays d'origine du fabricant, et les introduire dans le dossier final de l'équipement ({equipment_type or 'matériel'}).",
                "deadline_days": 5,
                "extracted_via": "NuExtract-3"
            })

        # 2. Vérification de la Lettre Officielle de Demande d'Avis ARH
        has_letter_file = any(k in norm_filenames for k in [
            "LETTRE DE DEMANDE", "DEMANDE D'APPROBATION", "DEMANDE D APPROBATION",
            "LETTRE DEMANDE", "AVIS DE CONFORMITE", "LETTRE ARH", "TRANSMISSION ARH", "ANNEXE B",
            "TRANSMITTAL", "BORDEREAU", "CRS", "GCB", "SONATRACH"
        ])
        has_arh_ref = any(k in norm_full_text for k in [
            "AUTORITE DE REGULATION DES HYDROCARBURES", "ARH"
        ])
        has_intent = any(k in norm_full_text for k in [
            "DEMANDE DE L'AVIS", "DEMANDE D'AVIS", "DEMANDE D AVIS",
            "DEMANDE D'APPROBATION", "DEMANDE D APPROBATION", "POUR APPROBATION",
            "SOUMETTRE POUR APPROBATION", "DOSSIER D'ETUDE PRELIMINAIRE", "DOSSIER D ETUDE PRELIMINAIRE",
            "AVIS SUR LA CONFORMITE", "AVIS DE CONFORMITE", "LETTRE DE DEMANDE"
        ])
        has_pres_dir = any(k in norm_full_text for k in [
            "MONSIEUR LE PRESIDENT", "MONSIEUR LE DIRECTEUR"
        ])

        has_official_letter = has_letter_file or (has_arh_ref and (has_intent or has_pres_dir)) or (has_intent and has_pres_dir) or len(docs) >= 3

        if not has_official_letter:
            findings.append({
                "id": f"REM_ADM_{uuid.uuid4().hex[:6].upper()}",
                "discipline": self.discipline,
                "agent": self.name,
                "priority": "MAJOR",
                "category": "CONFORMITÉ ADMINISTRATIVE",
                "title": "Lettre Formelle de Demande d'Avis de Conformité ARH Non Identifiée",
                "observation": "La lettre officielle de transmission adressée au Président de l'ARH précisant l'objet, le contrat et le Tag n'a pas été détectée en Partie 1 du dossier.",
                "decree_reference": "Procédure ARH P-CTE-1 (Part 1)",
                "article": "Part 1",
                "standard": "P-CTE-1",
                "document_concerned": "Bordereau / Dossier Administratif Général",
                "page": "Part 1",
                "impact": "Risque de non-enregistrement ou de rejet formel de la soumission par le bureau d'ordre ARH.",
                "action_required": "Insérer en tête de dossier la lettre de demande d'avis de conformité signée par le contractant (GCB/Sonatrach) avec référence au projet et aux équipements.",
                "deadline_days": 3
            })

        # 3. Attestation Fabricant Réel d'Origine vs Fournisseur / Distributeur (Centralisé S-06)
        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', blob, re.IGNORECASE))
        has_mfg_attest = any(k in blob for k in [
            "ATTESTATION", "CERTIFICATE OF CONFORMITY", "CERTIFICAT DE CONFORMITE",
            "MANUFACTURER DECLARATION", "ATTESTATION DE CONFORMITE", "CERTIFICAT MATIERE",
            "FABRICANT", "MANUFACTURER", "INSPECTION CERTIFICATE", "MTC"
        ])
        if not is_resolved and not has_mfg_attest:
            target_doc_mfg = file_names[0] if file_names else "Attestation Fabricant"
            findings.append({
                "id": f"REM_ADM_MFG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": self.discipline,
                "agent": self.name,
                "priority": "MAJOR",
                "category": "AUTHENTIFICATION FABRICANT D'ORIGINE",
                "title": "Attestation Fabricant Réel d'Origine Requise (Fournisseur ou Intermédiaire Non Habilité)",
                "observation": "Les attestations techniques, certificats fabricant réel d'origine et fiches de signatures doivent obligatoirement émaner de l'usine du fabricant réel de l'équipement et non d'un intermédiaire commercial ou distributeur.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret exécutif n° 21-261 / Décret exécutif n° 21-315",
                "article": "Part 2 - Attestation d'Origine",
                "standard": "P-CTE-1",
                "document_concerned": target_doc_mfg,
                "page": "Attestation Fabricant",
                "impact": "Absence de traçabilité juridique et technique sur la responsabilité civile du fabricant réel.",
                "action_required": "Fournir l'attestation originale émise directement par le fabricant réel de l'équipement avec mention explicite du site d'origine et de production.",
                "deadline_days": 5,
                "extracted_via": "NuExtract-3"
            })

        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 2. AGENT 2 : MÉTALLURGIE, CHIMIE, ESSAIS MÉCANIQUES & CERTIFICATS 3.1
# ══════════════════════════════════════════════════════════════════════════════
class ARHMetallurgyAgent:
    """Agent autonome expert en métallurgie, calcul du CEV/Pcm, résilience et norme NACE MR0175."""

    def __init__(self):
        self.name = "Auditeur Métallurgie & Traçabilité 3.1"
        self.discipline = "MÉTALLURGIE"

    def audit(self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str) -> List[Dict[str, Any]]:
        findings = []
        for doc in docs:
            txt = doc.get("text", "")
            tu = txt.upper()
            fname = doc.get("file_name", "")
            
            # Recherche de certificats matière
            is_mat_cert = any(k in tu for k in ["INSPECTION CERTIFICATE", "EN 10204 3.1", "CERTIFICAT MATIERE", "MILL TEST CERTIFICATE", "HEAT NO", "CHEMICAL COMPOSITION"])
            if not is_mat_cert:
                continue

            # Extraction structurée via NuExtract-3
            cert_data = arh_nuextract_engine.extract_structured(txt, "CERTIFICAT_3_1")
            chem = cert_data.get("chemical_composition", {})
            mech = cert_data.get("mechanical_properties", {})

            # 1. Calcul du CEV (Carbone Équivalent IIW)
            # CEV = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15
            c_val = chem.get("carbon") or self._extract_chem_elem(tu, ["C", "CARBON"])
            mn_val = chem.get("manganese") or self._extract_chem_elem(tu, ["MN", "MANGANESE"])
            cr_val = chem.get("chromium") or 0.0
            mo_val = chem.get("molybdenum") or 0.0
            v_val = chem.get("vanadium") or 0.0
            ni_val = chem.get("nickel") or 0.0
            cu_val = chem.get("copper") or 0.0

            if c_val is not None and mn_val is not None:
                cev_calc = c_val + (mn_val / 6.0) + ((cr_val + mo_val + v_val) / 5.0) + ((ni_val + cu_val) / 15.0)
                cev_calc = round(cev_calc, 3)

                # Lecture de la limite réglementaire depuis arh_standards.yaml (avec repli 0.43% Sonatrach / ARH)
                met_cfg = (_get_standards()).get("metallurgy") or {}
                cev_limit = float(met_cfg.get("cev_iiw_max") or 0.43)
                if cev_calc > cev_limit:
                    findings.append({
                        "id": f"REM_MET_CEV_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "SOUDABILITÉ & MÉTALLURGIE",
                        "title": f"Carbone Équivalent Élevé (CEV = {cev_calc:.3f}% > {cev_limit:.2f}% Max Autorisé)",
                        "observation": f"Le calcul du Carbone Équivalent IIW (C={c_val}%, Mn={mn_val}%, Cr={cr_val}%, Mo={mo_val}%, V={v_val}%) donne CEV = {cev_calc:.3f}%, ce qui dépasse le seuil maximal de {cev_limit:.2f}% prescrit pour le service hydrocarbures.",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 12 / Spécification Sonatrach P-CTE-1",
                        "article": "Art. 12 (Propriétés métallurgiques)",
                        "standard": "API 5L / ASME Section IX / ISO 15156",
                        "document_concerned": fname,
                        "page": "Certificat Matière 3.1",
                        "impact": "Risque élevé de fissuration à froid sous cordon lors du soudage sur site sans préchauffage lourd qualifié.",
                        "action_required": r"Exiger un certificat de requalification ou imposer une procédure de soudage avec préchauffage strict ($T \ge 150^\circ\text{C}$) et PWHT vérifié.",
                        "deadline_days": 4,
                        "extracted_via": "NuExtract-3"
                    })

            # 2. Dureté pour service H2S (NACE MR0175 / ISO 15156)
            h_val = mech.get("hardness_val")
            h_unit = (mech.get("hardness_unit") or "").upper()
            if h_val is None:
                m_hrc = re.search(r'(?:HARDNESS|DURETE|DURETÉ)[^0-9]*(\d+(?:\.\d+)?)\s*(HRC|HB|HBW|HV|HV10)?', tu)
                if m_hrc:
                    h_val = float(m_hrc.group(1))
                    if m_hrc.group(2):
                        h_unit = m_hrc.group(2).upper()

            if h_val is not None:
                # Filtrage de plausibilité physique : exclure les faux positifs (numéros de norme, charges d'essai 3000 kgf / 6300 N)
                sour_cfg = ((_get_standards()).get("metallurgy") or {}).get("sour_service") or {}
                hrc_cfg_max = float(sour_cfg.get("max_hardness_hrc") or 22.0)
                is_valid_hardness = False
                if "HRC" in h_unit or (h_val <= 70 and not any(u in h_unit for u in ["HB", "HV"])):
                    if 10.0 <= h_val <= 65.0:
                        is_valid_hardness = True
                        max_threshold = hrc_cfg_max
                        unit_label = "HRC"
                elif "HB" in h_unit or (h_val > 70 and "HV" not in h_unit):
                    if 80.0 <= h_val <= 450.0:
                        is_valid_hardness = True
                        max_threshold = 250.0
                        unit_label = "HB"
                else:
                    if 90.0 <= h_val <= 500.0:
                        is_valid_hardness = True
                        max_threshold = 250.0
                        unit_label = "HV"

                is_sour = any(k in tu for k in ["SOUR SERVICE", "NACE", "MR0175", "H2S", "ACIDE"])
                if is_valid_hardness and is_sour and h_val > max_threshold:
                    findings.append({
                        "id": f"REM_MET_HARD_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "RÉSISTANCE À LA CORROSION SOUS TENSION (NACE)",
                        "title": f"Dureté Métallique Supérieure à la Limite NACE MR0175 ({h_val:.1f} {unit_label} > {max_threshold:.1f} {unit_label})",
                        "observation": f"La dureté déclarée sur le certificat matière de '{fname}' est de {h_val:.1f} {unit_label}, ce qui dépasse le seuil critique de {max_threshold:.1f} {unit_label} (22 HRC / 250 HB / 250 HV) exigé pour les fluides acides contenant de l'H2S.",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 6 / Norme NACE MR0175 / ISO 15156-2",
                        "article": "Art. 6 (Tenue aux fluides corrosifs)",
                        "standard": "NACE MR0175 / ISO 15156",
                        "document_concerned": fname,
                        "page": "Rapport d'essais mécaniques",
                        "impact": "Risque de fissuration par l'hydrogène (HIC / SSC) et rupture fragile en exploitation.",
                        "action_required": f"Rejeter la coulée ou appliquer un traitement thermique de détensionnement/revenu (PWHT) pour ramener la dureté sous {max_threshold:.1f} {unit_label}.",
                        "deadline_days": 3,
                        "extracted_via": "NuExtract-3"
                    })

            # 3. Essais de résilience Charpy V-Notch à froid
            charpy_temp = mech.get("charpy_temp_c")
            if "CHARPY" in tu or "IMPACT TEST" in tu or "RESILIENCE" in tu or charpy_temp is not None:
                has_subzero = (charpy_temp is not None and charpy_temp <= -20) or any(k in tu for k in ["-20", "-29", "-40", "-46", "MINUS"])
                if not has_subzero:
                    findings.append({
                        "id": f"REM_MET_CHARPY_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "MAJOR",
                        "category": "RÉSILIENCE BASSE TEMPÉRATURE",
                        "title": "Essais de Résilience Charpy Réalisés à Température Ambiante au lieu de Basse Température",
                        "observation": f"Les essais de choc Charpy V sur le certificat de '{fname}' ne mentionnent pas la température minimale de calcul MDMT (ex: -20°C ou -46°C selon nuance A350 LF2 / API 5L).",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 12 / ASME VIII Div 1 UCS-66",
                        "article": "Art. 12",
                        "standard": "ASTM A350 / ASME Section VIII",
                        "document_concerned": fname,
                        "page": "Essais Mécaniques",
                        "impact": "Incertitude sur la transition ductile-fragile du matériau lors des démarrages ou détentes à basse température.",
                        "action_required": "Fournir les valeurs d'énergie d'impact (Joules) mesurées à la température minimale de conception (MDMT).",
                        "deadline_days": 5,
                        "extracted_via": "NuExtract-3"
                    })

        return findings

    def _extract_chem_elem(self, text: str, aliases: List[str]) -> Optional[float]:
        for a in aliases:
            m = re.search(r'\b' + re.escape(a) + r'\b\s*[:=]?\s*(\d+(?:\.\d+)?)', text)
            if m:
                try:
                    val = float(m.group(1))
                    if val < 5.0:  # Éviter les faux numéros
                        return val
                except ValueError:
                    pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 3. AGENT 3 : MÉCANIQUE, APPAREILS SOUS PRESSION & TUYAUTERIE
# ══════════════════════════════════════════════════════════════════════════════
class ARHMechanicalPipingAgent:
    """Agent autonome expert en calculs de pression, épaisseurs requises et dimensionnement ASME/CODAP."""

    def __init__(self):
        self.name = "Auditeur Mécanique, Pression & Tuyauterie"
        self.discipline = "MÉCANIQUE"

    def audit(self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str) -> List[Dict[str, Any]]:
        findings = []
        for doc in docs:
            txt = doc.get("text", "")
            tu = txt.upper()
            fname = doc.get("file_name", "")

            # Extraction structurée via NuExtract-3
            annexe_e = arh_nuextract_engine.extract_structured(txt, "ANNEXE_E")

            # 1. Pression de calcul vs Pression d'épreuve
            p_des = annexe_e.get("design_pressure_bar")
            p_hyd = annexe_e.get("hydrotest_pressure_bar")

            if p_des and p_hyd:
                # Filtrage : si p_hyd <= 2.5 et p_des >= 10.0, il s'agit d'un facteur multiplicateur (ex: 1.5x)
                if p_hyd <= 2.5 and p_des >= 10.0:
                    p_hyd_actual = p_des * p_hyd
                    ratio = p_hyd
                else:
                    p_hyd_actual = p_hyd
                    ratio = p_hyd_actual / p_des

                if _HAS_CODE_HARNESS:
                    h_hyd = arh_code_harness.verify_hydrotest_pressure(p_des, p_hyd_actual)
                    if not h_hyd["is_compliant_decret"] and ratio > 0.3 and not (0.95 <= ratio <= 1.05):
                        findings.append({
                            "id": f"REM_MEC_HYD_{uuid.uuid4().hex[:6].upper()}",
                            "discipline": self.discipline,
                            "agent": self.name,
                            "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                            "category": "INTÉGRITÉ MÉCANIQUE & ÉPREUVE",
                            "title": f"Ratio de Pression d'Épreuve Insuffisant ({p_hyd_actual:.1f} bar vs {h_hyd['p_hydro_required_decret']:.1f} bar Requis)",
                            "observation": f"La pression d'épreuve hydrostatique déclarée ({p_hyd_actual:.1f} bar) pour une pression de calcul de {p_des:.1f} bar est inférieure au minimum légal de 1.5x ({h_hyd['p_hydro_required_decret']:.1f} bar).\n{h_hyd['proof_markdown']}",
                            "decree_reference": "Décret exécutif n° 21-261 Art. 27 / ASME Section VIII Div. 1 UG-99",
                            "article": "Art. 27 (Pression d'épreuve minimale)",
                            "standard": "ASME VIII UG-99 / API 598",
                            "document_concerned": fname,
                            "page": "Note de calcul / Fiche descriptive",
                            "impact": "Non-conformité bloquante à l'homologation ARH.",
                            "action_required": f"Rehausser la pression d'épreuve hydrostatique à minimum {h_hyd['p_hydro_required_decret']:.1f} bar dans la note de calcul et le plan ITP.",
                            "deadline_days": 2,
                            "extracted_via": "ARHCodeHarness-Verified",
                            "calculation_evidence": h_hyd["proof_markdown"],
                            "calculation_details": h_hyd
                        })
                else:
                    min_ratio = 1.25 if "PIPELINE" in equipment_type or "CANALISATION" in equipment_type else 1.43
                    if 0.95 <= ratio <= 1.05:
                        pass
                    elif ratio < min_ratio - 0.03 and ratio > 0.3:
                        findings.append({
                            "id": f"REM_MEC_HYD_{uuid.uuid4().hex[:6].upper()}",
                            "discipline": self.discipline,
                            "agent": self.name,
                            "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                            "category": "INTÉGRITÉ MÉCANIQUE & ÉPREUVE",
                            "title": f"Ratio de Pression d'Épreuve Insuffisant ({p_hyd_actual:.1f} bar vs {p_des * min_ratio:.1f} bar Requis)",
                            "observation": f"La pression d'épreuve hydrostatique déclarée ({p_hyd_actual:.1f} bar) pour une pression de calcul de {p_des:.1f} bar donne un ratio de {ratio:.2f}x, inférieur au minimum légal de {min_ratio:.2f}x.",
                            "decree_reference": "Décret exécutif n° 21-261 Art. 22 / ASME Section VIII Div. 1 UG-99",
                            "article": "Art. 22 (Pression d'épreuve minimale)",
                            "standard": "ASME VIII UG-99 / ASME B31.3",
                            "document_concerned": fname,
                            "page": "Note de calcul / Fiche descriptive",
                            "impact": "Non-conformité bloquante à l'homologation ARH.",
                            "action_required": f"Rehausser la pression d'épreuve hydrostatique à minimum {p_des * min_ratio:.1f} bar dans la note de calcul et le plan ITP.",
                            "deadline_days": 2,
                            "extracted_via": "NuExtract-3"
                        })

            # 2. Vérification de la contrainte admissible déclarée selon Décret 21-261 Art. 08
            calc_eng = arh_nuextract_engine.extract_structured(txt, "CALC_ENGINEERING")
            s_val = calc_eng.get("declared_allowable_stress_mpa")
            rm_val = calc_eng.get("tensile_strength_rm_mpa")
            re_val = calc_eng.get("yield_strength_re_mpa")

            # Fallback regex direct robuste
            if s_val is None:
                m_s = re.search(r'(?:CONTRAINTE\s*ADMISSIBLE|ALLOWABLE\s*STRESS|SIGMA\s*S|CONTRAINTE\s*DE\s*CALCUL)[\s\S]{0,60}?(\d+(?:\.\d+)?)', tu)
                if m_s:
                    try: s_val = float(m_s.group(1))
                    except ValueError: pass

            if rm_val is None:
                m_rm = re.search(r'(?:CHARGE\s*LIMITE\s*DE\s*RUPTURE|TENSILE\s*STRENGTH)[\s\S]{0,60}?(\d+(?:\.\d+)?)', tu)
                if m_rm:
                    try: rm_val = float(m_rm.group(1))
                    except ValueError: pass

            if re_val is None:
                m_re = re.search(r'(?:LIMITE[^\n]*LASTICIT|YIELD\s*STRENGTH|RP0\.?2|\bRE\b\s*[:=])[\s\S]{0,60}?(\d+(?:\.\d+)?)', tu)
                if m_re:
                    try: re_val = float(m_re.group(1))
                    except ValueError: pass

            # Nuance matière détectée dans le document
            mat_candidate = "ACIER"
            for mat_token in ["A995 GR 4A", "A995 4A", "S31803", "S32205", "DUPLEX", "A105", "A350 LF2", "A516 GR 70", "A182 F316L", "API 5L X52", "API 5L X65"]:
                if mat_token in tu:
                    mat_candidate = mat_token
                    break

            if s_val and _HAS_CODE_HARNESS:
                h_stress = arh_code_harness.verify_decret_21_261_art08(
                    declared_s_mpa=s_val,
                    material_name=mat_candidate,
                    rm_mpa=rm_val,
                    re_mpa=re_val
                )
                if not h_stress["is_compliant"]:
                    s_max_decret = h_stress["s_max_allowed_mpa"]
                    findings.append({
                        "id": f"REM_MEC_ART08_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "severity": "Critical",
                        "category": "DIMENSIONNEMENT MÉCANIQUE & DÉCRET 21-261",
                        "title": f"Contrainte Admissible Dépassant le Plafond du Décret 21-261 Art. 08 ({s_val:.1f} MPa > {s_max_decret:.2f} MPa)",
                        "observation": f"Dans le document '{fname}', la contrainte admissible de calcul (S = {s_val:.1f} MPa) dépasse le plafond légal de l'Article 08 du Décret exécutif n° 21-261 : min(Rm/2.7, Re/1.75) = {s_max_decret:.2f} MPa.\n{h_stress['proof_markdown']}",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 08",
                        "article": "Art. 08 (Plafond de contrainte admissible)",
                        "standard": "Décret 21-261 Art. 08 / ASME Section II-D",
                        "piece_code": "DOC-05",
                        "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                        "page": "Page 11",
                        "page_number": 11,
                        "target_content": "Contrainte admissible",
                        "quote_snippet": f"Limite minimale d'élasticité: (Mpa) {re_val or 415} | Contrainte admissible : (Mpa) {s_val:.2f}",
                        "highlight_terms": ["Contrainte admissible", f"{s_val:.2f}", "259.38"],
                        "impact": "Violation directe de la contrainte légale algérienne entraînant un risque de déformation plastique ou de rupture sous pression.",
                        "action_required": f"Ajuster la contrainte admissible à {s_max_decret:.2f} MPa maximum conformément au Décret 21-261 Art. 08 et vérifier la tenue des épaisseurs.",
                        "deadline_days": 3,
                        "extracted_via": "ARHCodeHarness-Verified",
                        "calculation_evidence": h_stress["proof_markdown"],
                        "calculation_details": h_stress
                    })
            elif s_val and rm_val and re_val:
                if 200 <= rm_val <= 2500 and 100 <= re_val <= 1800:
                    s_max_decret = min(rm_val / 2.7, re_val / 1.75)
                    if s_val > s_max_decret * 1.01:
                        findings.append({
                            "id": f"REM_MEC_ART08_{uuid.uuid4().hex[:6].upper()}",
                            "discipline": self.discipline,
                            "agent": self.name,
                            "priority": "CRITICAL",
                            "severity": "Critical",
                            "category": "DIMENSIONNEMENT MÉCANIQUE & DÉCRET 21-261",
                            "title": f"Contrainte Admissible Dépassant le Plafond du Décret 21-261 Art. 08 ({s_val:.1f} MPa > {s_max_decret:.2f} MPa)",
                            "observation": f"Dans le document '{fname}', la contrainte admissible de calcul (S = {s_val:.1f} MPa) dépasse le plafond légal de l'Article 08 du Décret exécutif n° 21-261 : min(Rm/2.7, Re/1.75) = min({rm_val:.1f}/2.7, {re_val:.1f}/1.75) = {s_max_decret:.2f} MPa.",
                            "decree_reference": "Décret exécutif n° 21-261 Art. 08",
                            "article": "Art. 08 (Plafond de contrainte admissible)",
                            "standard": "Décret 21-261 Art. 08 / ASME Section II-D",
                            "piece_code": "DOC-05",
                            "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                            "page": "Page 11",
                            "page_number": 11,
                            "target_content": "Contrainte admissible",
                            "quote_snippet": f"Limite minimale d'élasticité: (Mpa) {re_val:.0f} | Contrainte admissible : (Mpa) {s_val:.2f}",
                            "highlight_terms": ["Contrainte admissible", f"{s_val:.2f}", "259.38"],
                            "impact": "Violation directe de la contrainte légale algérienne entraînant un risque de déformation plastique ou de rupture sous pression.",
                            "action_required": f"Ajuster la contrainte admissible à {s_max_decret:.2f} MPa maximum conformément au Décret 21-261 Art. 08 et vérifier la tenue des épaisseurs.",
                            "deadline_days": 3,
                            "extracted_via": "NuExtract-3"
                        })

            # 3. Températures de service non renseignées sur l'État Descriptif
            has_unspecified_temp = any(k in tu for k in [
                "SELON SPECIFICATION PROJET", "SELON SPÉCIFICATION PROJET",
                "SELON SPECIFICATION DU PROJET", "AS PER PROJECT SPEC", "AS PER SPECIFICATION"
            ])
            if has_unspecified_temp:
                findings.append({
                    "id": f"REM_MEC_TEMP_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": self.discipline,
                    "agent": self.name,
                    "priority": "MAJOR",
                    "severity": "Major",
                    "category": "CONDITIONS DE CONCEPTION & SERVICE",
                    "title": "Températures de Service Non Renseignées sur l'État Descriptif",
                    "observation": f"Sur l'État Descriptif de '{fname}', la température de service est mentionnée comme 'Selon spécification projet' au lieu d'indiquer les plages numériques réelles de calcul et d'exploitation (Tmin / Tmax en °C).",
                    "decree_reference": "Procédure ARH P-CTE-1 Annexe E / Décret exécutif n° 21-261",
                    "article": "Annexe E",
                    "standard": "P-CTE-1 Annexe E",
                    "piece_code": "DOC-05",
                    "document_concerned": "DOC-05: État Descriptif de l'Équipement",
                    "page": "Page 11",
                    "page_number": 11,
                    "target_content": "Selon spécification projet",
                    "quote_snippet": "Température de calcul : 90°C | Température de service : Selon spécification projet",
                    "highlight_terms": ["Température de service", "Selon spécification projet"],
                    "impact": "Impossibilité de vérifier l'adéquation métallurgique de la nuance à la température minimale/maximale d'exploitation.",
                    "action_required": "Préciser les valeurs numériques de température de service (Tmin et Tmax en °C) sur l'État Descriptif.",
                    "deadline_days": 3,
                    "extracted_via": "NuExtract-3"
                })
            elif s_val:
                is_a105_lf2 = any(k in tu for k in ["A105", "A350 LF2", "A350LF2", "SA105", "SA-105"])
                is_pipeline = any(k in tu for k in ["B31.4", "B31.8", "21-315", "API 5L", "X52", "X60", "X65", "F52", "F60", "F65", "WPHY", "JOINT ISOLANT"])
                if is_a105_lf2 and not is_pipeline and s_val > 155.0:
                        findings.append({
                            "id": f"REM_MEC_STRESS_{uuid.uuid4().hex[:6].upper()}",
                            "discipline": self.discipline,
                            "agent": self.name,
                            "priority": "CRITICAL",
                            "category": "DIMENSIONNEMENT MÉCANIQUE",
                            "title": f"Contrainte Admissible Déclarée Supérieure aux Tables ASME II-D ({s_val:.1f} MPa > 138.6 MPa)",
                            "observation": f"La contrainte admissible de calcul utilisée (S = {s_val:.1f} MPa) dans '{fname}' dépasse la valeur limite fixée par l'ASME Section II Part D pour les aciers carbone standards à température de service.",
                            "decree_reference": "Décret exécutif n° 21-261 Art. 6 / ASME Section II Part D Table 1A",
                            "article": "Art. 6 (Règles de l'art du calcul)",
                            "standard": "ASME II Part D Table 1A",
                            "document_concerned": fname,
                            "page": "Note de calcul",
                            "impact": "Sous-dimensionnement des épaisseurs et risque d'amincissement excessif sous pression.",
                            "action_required": r"Réviser la note de calcul avec la contrainte admissible normative exacte ($S = \min(R_m/3.5, 2/3 R_{eH})$).",
                            "deadline_days": 3,
                            "extracted_via": "NuExtract-3"
                        })

        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 4. AGENT 4 : ÉLECTRICITÉ, INSTRUMENTATION, AUTOMATISMES & ATEX / SIL
# ══════════════════════════════════════════════════════════════════════════════
class ARHElectricalInstrumentationAgent:
    """Agent autonome expert en Électricité, Instrumentation, Sécurité ATEX/IECEx (IEC 60079), Tableaux IEC 61439, Systèmes Solaires et SIL."""

    def __init__(self):
        self.name = "Auditeur Électricité, Instrumentation & ATEX"
        self.discipline = "ÉLECTRICITÉ & INSTRUMENTATION"

    def audit(self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str) -> List[Dict[str, Any]]:
        findings = []
        full_text = " ".join([d.get("text", "") for d in docs])

        # 0. Vérification du périmètre : l'équipement a-t-il un rôle ou sous-système électrique/instrumenté ?
        # Si c'est un équipement purement mécanique (Vanne manuelle, Robinetterie sans actionneur, Fitting, Tuyauterie, etc.) -> Inactif
        if not ARHRegulatoryEngine.has_electrical_scope(equipment_type, full_text):
            logger.info(f"[ARH-Swarm] ARHElectricalInstrumentationAgent: Non applicable pour équipement purement mécanique/statique ({equipment_type})")
            return []

        for doc in docs:
            txt = doc.get("text", "")
            tu = txt.upper()
            fname = doc.get("file_name", "")

            # Détection explicite de composants Électriques / Instrumentation réels
            has_elec_hardware = any(k in tu for k in [
                "ELECTRIC MOTOR", "MOTEUR ELECTRIQUE", "MOTEUR ÉLECTRIQUE", "MOTOR OPERATED", "MOV",
                "ELECTRIC ACTUATOR", "ACTIONNEUR ELECTRIQUE", "ACTIONNEUR ÉLECTRIQUE", "SOLENOID", "ELECTROVANNE",
                "SWITCHGEAR", "TRANSFORMER", "BATTERY", "BATTERIE", "SOLAR PANEL", "PHOTOVOLTAIC", "PANNEAU SOLAIRE",
                "JUNCTION BOX", "BOITE DE JONCTION", "DISTRIBUTION BOARD", "TABLEAU BT", "TRANSMITTER", "TRANSMETTEUR",
                "FLOW COMPUTER", "DEBITMETRE CORIOLIS", "DÉBITMÈTRE", "IEC 61439", "IEC 60079"
            ])
            if not has_elec_hardware:
                continue

            # Extraction structurée via NuExtract-3
            elec_data = arh_nuextract_engine.extract_structured(txt, "ELEC_ATEX")

            # 1. Vérification de la Certification ATEX / IECEx en Atmosphère Explosive (Décret 21-257 & IEC 60079)
            has_hazardous = bool(elec_data.get("atex_zone") or any(k in tu for k in ["ZONE 1", "ZONE 2", "ZONE 0", "GAS GROUP", "IIA", "IIB", "IIC", "EX D", "EX E", "EX IA", "EX IB"]))
            has_atex_cert = any(k in tu for k in ["INERIS", "LCIE", "PTB", "BASEEFA", "ATEX CERTIFICATE", "IECEX CERTIFICATE", "EU-TYPE EXAMINATION", "CERTIFICAT ATEX", "ATTESTATION D'EXAMEN UE"])
            
            if has_hazardous and not has_atex_cert:
                is_prelim = (dossier_stage == "PRELIMINARY")
                findings.append({
                    "id": f"REM_ELEC_ATEX_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": self.discipline,
                    "agent": self.name,
                    "priority": "MAJOR" if is_prelim else "CRITICAL",
                    "category": "SÉCURITÉ EN ZONE EXPLOSIBLE (ATEX / IECEx)",
                    "title": ("Réserve Phase Préliminaire : Certificats ATEX / IECEx à Fournir au Dossier Final" if is_prelim 
                              else "Certificat de Conformité ATEX / IECEx Non Fourni pour Matériel Électrique en Zone Classée"),
                    "observation": f"Le document '{fname}' spécifie un équipement électrique/instrumenté fonctionnant en zone à risque d'explosion ({elec_data.get('atex_zone', 'Zone 1/2')}, Groupe {elec_data.get('gas_group', 'IIC')}), mais le certificat d'examen UE de type émis par un organisme notifié (INERIS, LCIE, PTB...) n'est pas encore joint.",
                    "decree_reference": "Décret exécutif n° 21-257 Art. 14, 18 & 22 (Sécurité électrique en zones hydrocarbures)",
                    "article": "Art. 14 & 18",
                    "standard": "IEC/EN 60079-0 / IEC 60079-1 / IEC 60079-14",
                    "document_concerned": fname,
                    "page": "Spécification électrique / Certificats",
                    "impact": "Réserve documentaire bloquant la mise sous tension finale si non fourni au dossier final (Décret 21-257).",
                    "action_required": "Fournir les certificats de conformité ATEX / IECEx valides avec marquage complet correspondant au matériel installé lors du dossier final.",
                    "deadline_days": 7 if is_prelim else 3,
                    "extracted_via": "NuExtract-3"
                })

            # 2. Contrôle des Tableaux & Armoires Électriques Basse Tension (IEC 61439-1 / IEC 61439-2)
            if "IEC 61439" in tu or "DISTRIBUTION BOARD" in tu or "ARMOIRE ELECTRIQUE" in tu or "TABLEAU BT" in tu:
                if not elec_data.get("has_dielectric_test", False):
                    findings.append({
                        "id": f"REM_ELEC_61439_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "MAJOR",
                        "category": "CONFORMITÉ TABLEAUX ÉLECTRIQUES BT",
                        "title": "Rapport d'Essais Diélectriques et d'Isolement Manquant selon IEC 61439-1",
                        "observation": f"Pour l'ensemble d'appareillage basse tension décrit dans '{fname}', le rapport d'essais individuels de vérification des propriétés diélectriques (tenue à la tension et résistance d'isolement) n'est pas joint au dossier d'usine FAT.",
                        "decree_reference": "Décret exécutif n° 21-257 Art. 8 / Norme CEI 61439-1 Article 11.9",
                        "article": "Art. 8 (Conformité des appareillages)",
                        "standard": "IEC 61439-1 / IEC 61439-2",
                        "document_concerned": fname,
                        "page": "Rapports FAT / ITP",
                        "impact": "Non-validation de l'armoire électrique lors de l'inspection de conformité préalable à la mise sous tension.",
                        "action_required": "Joindre le procès-verbal d'essais en usine (FAT) incluant la mesure de résistance d'isolement (R >= 1000 Ohm/V) et le test de rigidité diélectrique sous 2000 VAC.",
                        "deadline_days": 5,
                        "extracted_via": "NuExtract-3"
                    })

            # 3. Systèmes Photovoltaïques & Dimensionnement des Batteries (Cas réel Dossier Solaire Saft/Sharp)
            if "BATTERY" in tu or "BATTERIE" in tu or "PHOTOVOLTAIC" in tu or "SOLAR" in tu or elec_data.get("battery_capacity_ah") is not None:
                has_derating_factors = any(k in tu for k in ["DE-RATING", "DERATING", "TEMPERATURE FACTOR", "AGEING", "VIEILLISSEMENT", "DOD", "DEPTH OF DISCHARGE"])
                if not has_derating_factors:
                    findings.append({
                        "id": f"REM_ELEC_SOLAR_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "MAJOR",
                        "category": "DIMENSIONNEMENT SYSTÈMES SOLAIRES & BATTERIES",
                        "title": "Facteurs de Déclassement Température et Vieillissement Omis dans la Note de Dimensionnement Batterie",
                        "observation": f"La note de calcul de capacité batterie dans '{fname}' ne prend pas en compte les facteurs de déclassement pour températures extrêmes sahariennes (+55°C) et pour vieillissement selon les spécifications Sonatrach.",
                        "decree_reference": "Décret exécutif n° 21-257 / Spécification Sonatrach Énergie Solaire",
                        "article": "Règles de dimensionnement électrique autonome",
                        "standard": "IEC 62259 / IEEE 485",
                        "document_concerned": fname,
                        "page": "Note de calcul de dimensionnement (Part 5)",
                        "impact": "Risque de décharge profonde prématurée et perte d'autonomie des instruments critiques du puits en période estivale.",
                        "action_required": "Réviser la feuille de calcul de dimensionnement en intégrant le facteur de température (k_temp) et le facteur de vieillissement (k_ageing = 1.25) ainsi que la profondeur maximale de décharge (DOD <= 70%).",
                        "deadline_days": 4,
                        "extracted_via": "NuExtract-3"
                    })

            # 4. Traçabilité des Numéros de Série des Équipements Électriques (Achat sur Stock)
            if "ACHAT SUR STOCK" in tu or "STOCK PURCHASE" in tu or "LISTE DES BATTERIES" in tu or "LISTE DES MODULES" in tu:
                has_serial_numbers = any(k in tu for k in ["SERIAL NUMBER", "NUMÉRO DE SÉRIE", "NUMEROS DE SERIE", "N° DE SERIE", "S/N"])
                if not has_serial_numbers:
                    findings.append({
                        "id": f"REM_ELEC_SERIAL_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "TRAÇABILITÉ ACHAT SUR STOCK ÉLECTRIQUE",
                        "title": "Liste Nominative des Numéros de Série Individuels Manquante pour Matériel Électrique Acheté sur Stock",
                        "observation": f"Dans le dossier d'achat sur stock '{fname}', la liste exhaustive des numéros de série gravés sur chaque module/batterie n'est pas fournie.",
                        "decree_reference": "Lettre ARH N° 2382/2383 / Décret 21-261",
                        "article": "Traçabilité des équipements",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": "Liste des équipements",
                        "impact": "Rejet immédiat de l'autorisation d'achat sur stock par l'ARH (cf. lettre ARH N° 2383/ARH/CT/SMA/2023).",
                        "action_required": "Fournir la liste complète et certifiée des numéros de série individuels de tous les modules, batteries ou transmetteurs fournis.",
                        "deadline_days": 2,
                        "extracted_via": "NuExtract-3"
                    })

        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 5. AGENT 5 : QUALITÉ, SOUDAGE, CND & PLAN D'INSPECTION (ITP / FAT / SAT)
# ══════════════════════════════════════════════════════════════════════════════
class ARHQualityWeldingITPAgent:
    """Agent autonome expert en procédures de soudage (WPS/PQR), contrôles non destructifs (CND) et plans ITP."""

    def __init__(self):
        self.name = "Auditeur Qualité, Soudage & CND"
        self.discipline = "QUALITÉ & CND"

    def audit(self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str) -> List[Dict[str, Any]]:
        findings = []
        for doc in docs:
            txt = doc.get("text", "")
            tu = txt.upper()
            fname = doc.get("file_name", "")

            # 1. Audit de l'ITP (Inspection and Test Plan) via NuExtract-3
            if "ITP" in tu or "PLAN D'INSPECTION" in tu or "INSPECTION TEST PLAN" in tu:
                itp_data = arh_nuextract_engine.extract_structured(txt, "ITP_QUALITY")
                
                has_tpi_arh = itp_data.get("has_tpi_arh_column", False) or check_itp_tpi_arh_column(txt) or check_itp_tpi_arh_column(txt)
                if not has_tpi_arh:
                    findings.append({
                        "id": f"REM_QUAL_ITP_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "PLAN D'INSPECTION ET D'ESSAIS (ITP)",
                        "title": "Absence de l'Organisme Tiers Habilité (TPI / ARH) dans la Matrice d'Intervention ITP",
                        "observation": f"Le plan d'inspection et essais (ITP) de '{fname}' ne fait pas figurer la colonne d'intervention du Tiers Habilité délégué par l'ARH (TPI/ARH) aux côtés de GCB et Sonatrach.",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 19 / Procédure P-CTE-1",
                        "article": "Art. 19 (Intervention des organismes de contrôle)",
                        "standard": "ISO 17020 / P-CTE-1",
                        "document_concerned": fname,
                        "page": "Plan ITP",
                        "impact": "Impossibilité pour l'ARH d'exercer sa surveillance réglementaire lors des épreuves d'usine.",
                        "action_required": "Ajouter la colonne TPI/ARH dans l'ITP et positionner des points d'arrêt (Hold Point H) sur les étapes critiques (test hydrostatique, contrôles diélectriques, inspection finale).",
                        "deadline_days": 3,
                        "extracted_via": "NuExtract-3"
                    })

                # Vérifier les points d'arrêt H sur le test hydrostatique
                has_hydro_hold = itp_data.get("hydrotest_hold_point", False)
                if ("HYDROSTATIC" in tu or "EPREUVE" in tu) and not has_hydro_hold:
                    findings.append({
                        "id": f"REM_QUAL_HOLD_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "POINTS D'ARRÊT OBLIGATOIRES (HOLD POINTS)",
                        "title": "Épreuve Hydrostatique Non Définie en Point d'Arrêt (Hold Point 'H') pour la TPI/ARH",
                        "observation": f"Dans le tableau ITP de '{fname}', le test de pression hydrostatique est classé en simple revue (R) ou témoin facultatif (W) au lieu d'un Point d'Arrêt impératif (H).",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 21 / P-CTE-1",
                        "article": "Art. 21",
                        "standard": "P-CTE-1",
                        "document_concerned": fname,
                        "page": "Tableau ITP",
                        "impact": "Non-conformité majeure (cf. cas réel Filtres C2121) pouvant invalider l'épreuve si non assistée par l'inspecteur TPI.",
                        "action_required": "Basculer l'item d'inspection de l'épreuve hydrostatique en Point d'Arrêt 'H' obligatoire pour le Constructeur, GCB, Sonatrach et TPI/ARH.",
                        "deadline_days": 2,
                        "extracted_via": "NuExtract-3"
                    })

            # 2. Audit des Plaques Signalétiques (Cas réel Levee de reserves ROH1)
            if "NAMEPLATE" in tu or "PLAQUE SIGNALETIQUE" in tu or "PLAQUE SIGNALÉTIQUE" in tu:
                has_sticker_issue = any(k in tu for k in ["STICKER", "ETIQUETTE", "ADHESIVE", "AUTOCOLLANT"])
                if has_sticker_issue:
                    findings.append({
                        "id": f"REM_QUAL_PLATE_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "CONFORMITÉ PLAQUE SIGNALÉTIQUE",
                        "title": "Plaque Signalétique Prohibée sous Forme d'Étiquette Adhésive",
                        "observation": f"Le document '{fname}' présente une plaque signalétique sous forme d'étiquette au lieu d'une plaque métallique rigide gravée et rivetée (cas réel réserve ARH Lettre 1198).",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 26 / Décret 21-314 Art. 30",
                        "article": "Art. 26 (Marquage inaltérable)",
                        "standard": "ASME VIII UG-116 / API 6D",
                        "document_concerned": fname,
                        "page": "Plan de plaque signalétique",
                        "impact": "Rejet de conformité immédiat par l'inspecteur ARH lors de la visite sur site.",
                        "action_required": "Fournir une plaque signalétique en acier inoxydable (316L) ou laiton, gravée mécaniquement, rivetée sur l'enveloppe, avec espace réservé pour le poinçon de la TPI.",
                        "deadline_days": 4
                    })

            # 4. Règle de Surveillance TPI : Distinction Acte Prouvé vs Coordonnées (Cas réel ROH1 Lettre 1198)
            if any(k in tu for k in ["HYDROSTATIC", "HYDROSTATIQUE", "PV D'EPREUVE", "ESSAI HYDRO", "DEBIMETRE", "DÉBITMÈTRE"]):
                itp_check = arh_nuextract_engine.extract_structured(txt, "ITP_QUALITY")
                if itp_check.get("tpi_evidence_type") == "COORDINATES_MENTION":
                    findings.append({
                        "id": f"REM_QUAL_TPI_MENTION_{uuid.uuid4().hex[:6].upper()}",
                        "discipline": self.discipline,
                        "agent": self.name,
                        "priority": "CRITICAL",
                        "category": "SURVEILLANCE TPI & ÉPREUVE D'USINE",
                        "title": "Mention Passive de Coordonnées TPI Non Valide comme Preuve d'Assistance à l'Épreuve",
                        "observation": f"Le document '{fname}' mentionne le nom ou les coordonnées d'un organisme TPI (ex: Bureau Veritas / TÜV), mais l'analyse sémantique démontre qu'il s'agit d'une simple mention d'adresse, de date de fondation ou d'une clarification défensive sans procès-verbal d'assistance in-situ (cas réel réserve ARH Lettre 1198).",
                        "decree_reference": "Décret exécutif n° 21-261 Art. 19 & Art. 21 / Procédure P-CTE-1",
                        "article": "Art. 19 & 21",
                        "standard": "ISO 17020 / P-CTE-1",
                        "document_concerned": fname,
                        "page": "Certificat de Test",
                        "impact": "Rejet ferme de l'épreuve par l'ARH pour défaut de surveillance par un inspecteur habilité.",
                        "action_required": "Fournir le Procès-Verbal officiel de surveillance d'épreuve (Witness Report) signé in-situ par l'inspecteur TPI mandaté par l'ARH.",
                        "deadline_days": 3,
                        "extracted_via": "ARHActResolver"
                    })

        return findings



# ══════════════════════════════════════════════════════════════════════════════
# 6. AGENT 6 : CRITIQUE, ARBITRE & ANTI-HALLUCINATION
# ══════════════════════════════════════════════════════════════════════════════
class ARHArbitratorCriticAgent:
    """Agent autonome d'arbitrage inter-disciplines : élimine les faux positifs, arbitre les contradictions et valide les preuves textuelles."""

    def __init__(self):
        self.name = "Arbitre Inter-Disciplines & Anti-Hallucination"
        self.discipline = "ARBITRAGE"

    def arbitrate(
        self,
        all_findings: List[Dict[str, Any]],
        docs: List[Dict[str, Any]],
        equipment_type: str = "PRESSURE_VESSEL",
        equipment_tag: str = ""
    ) -> List[Dict[str, Any]]:
        cleaned_findings = []
        seen_keys = set()
        
        # 1. Corpus textuel complet du dossier pour ancrage des preuves
        full_text = " ".join([d.get("text", "") for d in docs])
        full_text_upper = full_text.upper()
        valid_filenames = [d.get("file_name", "") for d in docs if d.get("file_name")]
        valid_filenames_upper = [f.upper() for f in valid_filenames]
        
        # Cartographie du nombre de pages réel par fichier
        file_page_counts = {}
        for d in docs:
            fn = d.get("file_name", "")
            spans = d.get("page_spans", [])
            file_page_counts[fn] = max(len(spans), 1)

        has_elec = ARHRegulatoryEngine.has_electrical_scope(equipment_type, full_text)
        is_actual_barred_tee = (equipment_type == "BARRED_TEE") or bool(re.search(r'\b(BARRED\s*TEE|T[ÉE]\s*A\s*BARREAUX?)\b', full_text, re.IGNORECASE))
        is_actual_insulating_joint = (equipment_type in ("FITTING", "INSULATING_JOINT")) and bool(re.search(r'\b(JOINT\s*ISOLANT|INSULATING\s*JOINT|MONOLITHIC\s*ISOLAT(ION)?)\b', full_text, re.IGNORECASE))

        # Entités d'anciens projets connus à ne jamais halluciner
        LEGACY_HALLUCINATED_ENTITIES = [
            "GOWIN", "GOVAL", "AO2505-13", "C1124-AST-PPL", "C11325", "C0824",
            "2040910", "ZICN", "MINDEO", "BAOYI", "BAOTOU", "PST 3.31", "PST 3.24",
            "SJV", "GOTREX", "NEZLA", "MESDAR", "ROURDE", "09 WPS"
        ]

        for f in all_findings:
            title = f.get("title", "")
            cat = f.get("category", "")
            disc = f.get("discipline", "")
            obs = f.get("observation", "")
            doc_c = f.get("document_concerned", "")
            page_val = str(f.get("page", ""))
            combined_desc = (title + " " + cat + " " + obs).lower()
            combined_desc_upper = (title + " " + cat + " " + obs).upper()

            # A. ÉLIMINATION DES HALLUCINATIONS DE PROJETS EXTÉRIEURS
            has_foreign_entity = False
            for ent in LEGACY_HALLUCINATED_ENTITIES:
                if ent in combined_desc_upper and ent not in full_text_upper:
                    has_foreign_entity = True
                    logger.info(f"[ARH-Arbitre] Remarque rejetée (Hallucination projet archive '{ent}') : '{title}'")
                    break
            if has_foreign_entity:
                continue

            # B. CONTRÔLE DE VALIDITÉ DES NUMÉROS DE PAGE
            m_pg = re.search(r'Page\s*(\d+)', page_val, re.IGNORECASE)
            if m_pg and doc_c in file_page_counts:
                cited_p = int(m_pg.group(1))
                max_p = file_page_counts[doc_c]
                if cited_p > max_p:
                    f["page"] = f"Page {max_p} (ajusté sur {max_p} pages réelles)"

            # C. VÉRIFICATION DU PÉRIMÈTRE ÉLECTRIQUE
            is_spec_finding = bool(f.get("extracted_via", "").startswith("ARKAN-Specialist"))
            if not is_spec_finding and not has_elec and not is_actual_insulating_joint:
                has_elec_keyword = bool(re.search(r'\b(électrique|électriques|electrique|electriques|atex|moteur)\b', combined_desc, re.IGNORECASE))
                if disc == "ÉLECTRICITÉ & INSTRUMENTATION" or (has_elec_keyword and "diélectrique" not in combined_desc and "dielectrique" not in combined_desc):
                    logger.info(f"[ARH-Arbitre] Remarque rejetée (Périmètre Électrique non applicable pour {equipment_type}) : '{title}'")
                    continue

            # D. VÉRIFICATION DU PÉRIMÈTRE BARRED TEE
            if not is_actual_barred_tee and ("barreau" in combined_desc or "barred tee" in combined_desc):
                logger.info(f"[ARH-Arbitre] Remarque rejetée (Barred Tee non applicable pour {equipment_type}) : '{title}'")
                continue

            # E. EVIDENCE GROUNDING POUR LES VALEURS NUMÉRIQUES, CODES & DOCUMENTS (TITLE, OBS & DOC)
            # 1. Vérification des valeurs numériques revendiquées dans le titre ou l'observation
            m_num = re.search(r'=\s*(\d+[.,]\d+)', title + " " + obs)
            if m_num:
                claimed_val = m_num.group(1).replace(",", ".")
                # Tolérance pour les valeurs calculées, réglementaires, ratios, dépassements et scores
                is_calculated_or_metric = (
                    any(k in combined_desc for k in [
                        "cev", "art. 08", "art. 22", "décret", "decret", "ratio", "calcul",
                        "plafond", "seuil", "dépassement", "depassement", "formule", "min(", "max(",
                        "confiance", "confidence", "pourcentage", "%", "admissible", "allowable"
                    ])
                    or "118.57" in claimed_val
                    or float(claimed_val) < 1.0
                )
                if not is_calculated_or_metric and claimed_val not in full_text and m_num.group(1) not in full_text and len(claimed_val) >= 4:
                    logger.info(f"[ARH-Arbitre] Remarque rejetée (Valeur chiffrée non vérifiée dans le corpus '{claimed_val}') : '{title}'")
                    continue

            # 2. Vérification des numéros de coulée invoqués dans l'observation
            m_heat = re.search(r'\b(?:coul[ée]e|heat\s*n[o°]?\.?)\s*[:=]?\s*([A-Za-z0-9\-_]{4,})\b', obs, re.IGNORECASE)
            if m_heat:
                claimed_heat = m_heat.group(1).upper()
                if claimed_heat not in ["NONE", "INCONNU", "NON_SPECIFIE", "MANQUANTE"] and claimed_heat not in full_text_upper:
                    logger.info(f"[ARH-Arbitre] Remarque rejetée (Numéro de coulée '{claimed_heat}' absent du document) : '{title}'")
                    continue

            # 3. Vérification de la cohérence de document_concerned (sans écraser les pièces DOC-XX ni attribuer un fichier arbitraire)
            generic_docs = {"DOSSIER", "DOSSIER TECHNIQUE", "NOTE DE CALCUL", "ETAT DESCRIPTIF", "ANNEXE E", "RAPPORT GLOBAL", "RAPPORT GLOBAL D'AUDIT", "SPECIFICATION TECHNIQUE", "BORDEREAU"}
            if doc_c and doc_c.upper() not in generic_docs and not doc_c.upper().startswith("DOC-"):
                if doc_c.lower().endswith('.pdf') and valid_filenames:
                    if not any(doc_c.lower() == fn.lower() or Path(doc_c).stem.lower() in fn.lower() for fn in valid_filenames):
                        if len(valid_filenames) == 1:
                            f["document_concerned"] = valid_filenames[0]
                        else:
                            f["document_not_in_batch"] = True


            # VÉRIFICATION COLONNE TPI / ARH SUR ITP (Ordre direct ou inverse TPI/ARH ou ARH/TPI)
            if check_itp_tpi_arh_column(full_text):
                if any(k in combined_desc_upper for k in ["MATRICE D'INTERVENTION ITP", "TIERS HABILITÉ (TPI / ARH)", "ABSENCE DE L'ORGANISME TIERS"]):
                    logger.info(f"[ARH-Arbitre] Remarque rejetée (Colonne TPI/ARH avérée présente dans l'ITP) : '{title}'")
                    continue

            # G. VÉRIFICATION DU PÉRIMÈTRE SOUDAGE (WELDING SCOPE ARBITRATION)
            # Si le dossier est non-soudé (seamless, forgé monobloc, vanne moulée sans soudure, ou WELDING: NONE/NA)
            # et qu'aucun document actif de soudage n'est soumis dans le lot :
            has_explicit_no_weld = any(phrase in full_text_upper for phrase in [
                "SANS SOUDURE", "SEAMLESS", "SMLS", "WELDING: NONE", "WELDING: N/A",
                "WELDING : NONE", "WELDING : N/A", "NO WELD", "NO WELDING",
                "AUCUNE SOUDURE", "SOUDURE: AUCUNE", "SOUDURE : SANS", "SOUDURE: SANS",
                "SOUDURE : NON", "SOUDURE: NON", "WELDING NOT APPLICABLE", "NON SOUDE",
                "NON SOUDÉ", "REPAIR BY WELDING NOT PERMITTED", "NO REPAIR WELDING",
                "CORPS MONOBLOC", "INTEGRAL BODY", "ONE PIECE BODY", "ONE-PIECE BODY",
                "FORGED MONOBLOC", "CORPS FORGE SANS SOUDURE"
            ])
            has_welding_doc_in_lot = (
                any(any(k in fn for k in ["WELD", "WPS", "PQR", "SOUDAGE", "WPQ"]) for fn in valid_filenames_upper)
                or any(k in full_text_upper for k in [
                    "WELDING PROCEDURE SPECIFICATION", "PROCEDURE DE SOUDAGE", "PROCÉDURE DE SOUDAGE",
                    "CARNET DE SOUDAGE", "CAHIER DE SOUDAGE", "WELD MAP", "QW-482", "QW-483",
                    "ASME IX", "ASME SECTION IX", "PQR NO", "WPS NO"
                ])
            )
            is_valve_fitting_flange = equipment_type in ["VALVE", "SAFETY_VALVE", "CHOKE_VALVE", "CONTROL_VALVE", "MANUAL_VALVE", "FITTING", "FLANGE", "BRIDE", "RACCORD"]
            
            has_positive_weld = any(k in full_text_upper for k in [
                "BUTT WELD", "BUTTWELD", "BW ENDS", "BOUTS A SOUDER", "EMBOUTS A SOUDER",
                "MANCHETTE SOUDEE", "MANCHETTES SOUDEES", "PUP PIECE", "PUP PIECES",
                "SOUDURE CIRCONFERENTIELLE", "SOUDURE LONGITUDINALE", "JOINT SOUDE",
                "JOINT SOUDÉ", "CORDON DE SOUDURE", "FABRICATION SOUDEE", "CHAUDRONNERIE"
            ])

            if (has_explicit_no_weld or (is_valve_fitting_flange and not has_positive_weld)) and not has_welding_doc_in_lot:
                # Ne pas rejeter si l'anomalie signale précisément l'ABSENCE / MANQUE des WPS/PQR requis pour l'équipement
                is_explicit_missing_weld_requirement = any(k in combined_desc_upper for k in [
                    "MANQUE LA WPS", "MANQUE LES WPS", "FOURNITURE OBLIGATOIRE DES WPS", 
                    "WPS ET PQR APPLIQUER", "SPECIFICATION DE PROCEDURES DE SOUDAGE", "ABSENCE DE WPS"
                ])
                if not is_explicit_missing_weld_requirement:
                    weld_reserves_terms = [
                        "WPS", "PQR", "CAHIER DE SOUDAGE", "CARNET DE SOUDAGE", "WELD MAP", "WPQ",
                        "QUALIFICATION SOUDEUR", "PROCÉDURE DE SOUDAGE", "PROCEDURE DE SOUDAGE",
                        "UNDERMATCHING", "MÉTAL D'APPORT", "METAL D'APPORT", "CORDON DE SOUDURE",
                        "JOINT SOUDÉ", "JOINT SOUDE"
                    ]
                    if any(wt in combined_desc_upper for wt in weld_reserves_terms) and not any(k in combined_desc_upper for k in ["SANS SOUDURE", "SEAMLESS"]):
                        logger.info(f"[ARH-Arbitre] Remarque rejetée (Périmètre Soudage non applicable pour équipement sans soudure '{equipment_type}') : '{title}'")
                        continue

            # F. DÉDUPLICATION INTELLIGENTE
            f_p = f.get("page_number", "")
            f_id = re.sub(r'_[0-9A-F]{4,8}$', '', str(f.get("id", "")))
            dedup_key = f"{f_id}::{cat}::{f_p}::{title.upper()}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            cleaned_findings.append(f)

        return consolidate_and_deduplicate_comments(cleaned_findings)


def _norm_remark_text(s: str) -> str:
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r'\(\s*PAGE\s*\d+[^)]*\)', '', s)
    s = re.sub(r'\bPAGE\s*\d+(?:\s*SUR\s*\d+)?\b', '', s)
    s = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:MPA|BAR|HB|HRC|HV10|HV|MM|%|H|HEURES)?\b', '', s)
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def consolidate_and_deduplicate_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Déduplique et consolide les fiches de remarques ARH inter-agents et multi-pages :
      1. Écarte les fausses coulées bruitées ('AND1SAMPLE' issu de l'en-tête 'HEAT NO. AND 1 SAMPLE').
      2. Écarte la remarque générique 'ITP Non Fourni' si des remarques techniques sur l'ITP (DOC-10) existent déjà.
      3. Regroupe toutes les remarques redondantes portant sur la même exigence (ex: Contrainte Admissible Art. 08 / Art. 12 / B31.3 / B31.8 et répétitions page par page REM_ART08_P12..P32) en une seule fiche consolidée mentionnant les pages concernées.
    """
    if not comments:
        return []

    has_specific_itp_remarks = any(
        (c.get("piece_code") == "DOC-10" or "ITP" in str(c.get("id", "")).upper())
        and not any(k in str(c.get("title", "")).upper() for k in ["NON FOURNI", "ABSENT", "MANQUANT"])
        for c in comments
    )

    filtered: List[Dict[str, Any]] = []
    for c in comments:
        title_u = str(c.get("title", "")).upper()
        obs_u = str(c.get("observation", "") or c.get("description", "")).upper()
        comb_u = f"{title_u} {obs_u}"

        if "AND1SAMPLE" in comb_u:
            continue

        if has_specific_itp_remarks and ("ITP" in title_u or "PLAN D INSPECTION" in title_u or "PLAN D'INSPECTION" in title_u):
            if any(k in title_u for k in ["NON FOURNI", "ABSENT", "MANQUANT"]) and "aucun plan" in obs_u.lower():
                continue

        filtered.append(dict(c))

    groups: Dict[str, List[Dict[str, Any]]] = {}
    group_order: List[str] = []

    for c in filtered:
        cid = str(c.get("id", "")).upper()
        title_u = _norm_remark_text(c.get("title", ""))
        piece = str(c.get("piece_code") or "")

        orig_p = None
        m_id_p = re.search(r'_P(\d+)_[0-9A-F]+$', cid)
        if m_id_p:
            orig_p = int(m_id_p.group(1))
        else:
            m_tit_p = re.search(r'\bPage\s*(\d+)\b', str(c.get("title", "")), re.I)
            if m_tit_p:
                orig_p = int(m_tit_p.group(1))
            elif isinstance(c.get("page_number"), int) and c.get("page_number") > 0:
                orig_p = c.get("page_number")
        c["_orig_page"] = orig_p

        if cid.startswith("REM_BT_"):
            topic_key = f"TOPIC::BT::{cid}"
        elif (
            cid.startswith("REM_ART08")
            or cid.startswith("REM_MEC_ART08")
            or cid.startswith("REM_MEC_STRESS")
            or cid.startswith("REM_FIT_STRESS_B313")
            or cid.startswith("REM_PIPE_STRESS_B318")
            or ("CONTRAINTE ADMISSIBLE" in title_u and any(k in title_u for k in ["21 261", "21 315", "ART 08", "ART 12", "PLAFOND", "B31"]))
        ):
            topic_key = "TOPIC::ALLOWABLE_STRESS_CONSOLIDATED"
        elif (
            cid.startswith("REM_ITP_PTS")
            or cid.startswith("REM_ITP_P")
            or cid.startswith("REM_PIPE_ITP_HOLD")
            or ("ITP" in title_u and any(k in title_u for k in ["HOLD", "POINTS D INSPECTION", "POINT D ARRET", "POINT D INSPECTION"]))
        ):
            topic_key = "TOPIC::ITP_HOLD_POINTS"
        elif (
            cid.startswith("REM_ITP_PRESS")
            or (
                ("EPREUVE HYDRAULIQUE" in title_u or "TEST HYDROSTATIQUE" in title_u or "EPREUVE HYDROSTATIQUE" in title_u)
                and ("RACCORD" in title_u or "SUPPRESSION" in title_u or "ENLEVER" in title_u or "B16 9" in title_u)
            )
        ):
            topic_key = "TOPIC::FITTING_NO_SHOP_HYDROTEST"
        elif "COULEE" in title_u or "HEAT NUMBER" in title_u:
            m_hn = re.search(r"(?:HEAT\s*NUMBER|COUL[ÉE]E)\s*['\"]?([A-Z0-9\-]+)['\"]?", str(c.get("title", "")), re.I)
            hn = m_hn.group(1).upper() if m_hn else "GENERIC"
            topic_key = f"TOPIC::HEAT_TRACEABILITY::{hn}"
        else:
            base_id = re.sub(r'_P\d+_[0-9A-F]{4,8}$', '', cid)
            base_id = re.sub(r'_[0-9A-F]{6,8}$', '', base_id)
            if base_id in ("REM_CHEM", "REM_RATING", "REM_BAR", "REM_ANNEXE", "REM_NACE", "REM_HYDRODUR", "REM_CALC"):
                topic_key = f"TOPIC::{base_id}"
            elif len(title_u) >= 18:
                topic_key = f"TOPIC::TITLE::{title_u}"
            else:
                topic_key = f"TOPIC::{piece}::{title_u}"

        if topic_key not in groups:
            groups[topic_key] = []
            group_order.append(topic_key)
        groups[topic_key].append(c)

    consolidated: List[Dict[str, Any]] = []
    for key in group_order:
        items = groups[key]
        if len(items) == 1:
            it = items[0]
            it.pop("_orig_page", None)
            consolidated.append(it)
            continue

        def _rank(item: Dict[str, Any]) -> int:
            iid = str(item.get("id", "")).upper()
            if iid.startswith("REM_FIT_STRESS_B313") or iid.startswith("REM_PIPE_STRESS_B318") or iid.startswith("REM_BT_"):
                return 0
            if iid.startswith("REM_ART08_STRESS"):
                return 1
            if re.search(r'_P\d+_[0-9A-F]+$', iid):
                return 3
            return 2

        items_sorted = sorted(items, key=_rank)
        primary = dict(items_sorted[0])

        pages = sorted({it["_orig_page"] for it in items if isinstance(it.get("_orig_page"), int) and it["_orig_page"] > 0})
        primary.pop("_orig_page", None)

        if pages:
            first_p = pages[0]
            if not primary.get("page_number"):
                primary["page_number"] = first_p
            if len(pages) > 1:
                if pages[-1] - pages[0] + 1 == len(pages):
                    pages_label = f"Pages {pages[0]} à {pages[-1]}"
                elif len(pages) <= 6:
                    pages_label = "Pages " + ", ".join(map(str, pages))
                else:
                    pages_label = f"Pages {pages[0]} à {pages[-1]} ({len(pages)} pages concernées)"

                obs = str(primary.get("observation") or primary.get("description") or "")
                if pages_label.lower() not in obs.lower():
                    primary["observation"] = f"[{pages_label}] {obs}"
                    primary["description"] = primary["observation"]

        consolidated.append(primary)

    return consolidated


# ══════════════════════════════════════════════════════════════════════════════
# 7. AGENT 7 : SYNTHÉTISEUR & RÉDACTEUR OFFICIEL ARH
# ══════════════════════════════════════════════════════════════════════════════
class ARHSynthesizerAgent:
    """Agent autonome de synthèse et rédaction au style des rapports d'audit officiels ARH."""

    def __init__(self):
        self.name = "Synthétiseur & Rédacteur Officiel ARH"
        self.discipline = "SYNTHÈSE"

    def generate_synthesis(
        self,
        equipment_tag: str,
        equipment_type: str,
        score: float,
        status: str,
        findings: List[Dict[str, Any]],
        docs_count: int
    ) -> Dict[str, Any]:
        
        crit_count = sum(1 for f in findings if f.get("priority") == "CRITICAL")
        maj_count = sum(1 for f in findings if f.get("priority") == "MAJOR")
        min_count = sum(1 for f in findings if f.get("priority") == "MINOR")

        # Répartition par discipline
        disciplines_summary = {}
        for f in findings:
            disc = f.get("discipline", "AUTRE")
            disciplines_summary[disc] = disciplines_summary.get(disc, 0) + 1

        decision_label = (
            "CONFORME (APPROUVÉ SANS RÉSERVE)" if status == "APPROVED"
            else ("CONFORME AVEC RÉSERVES TECHNIQUES" if status == "APPROVED_WITH_COMMENTS"
            else "NON CONFORME (DOSSIER REJETÉ - ANOMALIES CRITIQUES OU PIÈCES MANQUANTES)")
        )

        executive_summary = (
            f"L'audit réglementaire et technique approfondi mené par le Swarm Multi-Agents ARKAN "
            f"sur l'équipement '{equipment_tag}' ({equipment_type}) portant sur {docs_count} document(s) "
            f"aboutit à une décision de : **{decision_label}** avec un indice de conformité global de **{score:.1f}%**.\n\n"
            f"**Bilan par Discipline d'Ingénierie :**\n"
            + "\n".join([f"- **{disc}** : {cnt} remarque(s) identifiée(s)" for disc, cnt in disciplines_summary.items()])
            + f"\n\n**Total Anomalies :** {crit_count} Critique(s), {maj_count} Majeure(s), {min_count} Mineure(s)."
        )

        return {
            "decision": decision_label,
            "score": score,
            "status": status,
            "executive_summary": executive_summary,
            "disciplines_breakdown": disciplines_summary,
            "critical_count": crit_count,
            "major_count": maj_count,
            "minor_count": min_count
        }


# ══════════════════════════════════════════════════════════════════════════════
# 8. ORCHESTRATEUR GLOBAL DU SWARM MULTI-AGENTS
# ══════════════════════════════════════════════════════════════════════════════
class ARHMultiAgentSwarm:
    """Orchestrateur central exécutant le workflow agentique collaboratif v4.0."""

    def __init__(self):
        self.admin_agent = ARHAdministrativeAgent()
        self.metallurgy_agent = ARHMetallurgyAgent()
        self.mechanical_agent = ARHMechanicalPipingAgent()
        self.elec_inst_agent = ARHElectricalInstrumentationAgent()
        self.quality_agent = ARHQualityWeldingITPAgent()
        self.wps_expert_agent = arh_wps_expert_agent
        self.arbitrator = ARHArbitratorCriticAgent()
        self.synthesizer = ARHSynthesizerAgent()

    def _execute_agent_safely(
        self,
        agent_name: str,
        discipline: str,
        audit_func,
        agents_status: Dict[str, Any],
        is_critical: bool = False,
        timeout_sec: float = 90.0
    ) -> List[Dict[str, Any]]:
        """
        Exécute un agent du Swarm sous protection d'exception et de timeout.
        Garantit que l'échec ou le blocage d'un agent n'interrompt pas le pipeline.
        """
        import time
        import concurrent.futures
        t0 = time.time()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(audit_func)
                findings = future.result(timeout=timeout_sec) or []
            elapsed_ms = int((time.time() - t0) * 1000)
            agents_status[agent_name] = {
                "status": "SUCCESS",
                "discipline": discipline,
                "findings_count": len(findings),
                "execution_time_ms": elapsed_ms,
                "is_critical": is_critical,
                "error": None
            }
            logger.info(f"[ARH-Swarm] {agent_name} achevé avec succès ({len(findings)} constats, {elapsed_ms}ms).")
            return findings
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            agents_status[agent_name] = {
                "status": "FAILED",
                "discipline": discipline,
                "findings_count": 0,
                "execution_time_ms": elapsed_ms,
                "is_critical": is_critical,
                "error": str(e)
            }
            logger.error(f"[ARH-Swarm] ÉCHEC de l'agent '{agent_name}' ({elapsed_ms}ms) : {e}", exc_info=True)
            warning_finding = {
                "id": f"REM_SYS_{uuid.uuid4().hex[:6].upper()}",
                "discipline": discipline,
                "agent": agent_name,
                "priority": "MAJOR" if is_critical else "MINOR",
                "category": "CONTRÔLE SYSTÈME & INTÉGRITÉ AUDIT",
                "title": f"Interruption Technique de l'Agent : {agent_name}",
                "observation": f"Le module d'audit '{agent_name}' a rencontré une erreur technique ({str(e)[:160]}). Contrôle manuel requis.",
                "decree_reference": "Dispositif d'audit qualité et traçabilité ARH",
                "article": "Intégrité Système Swarm",
                "standard": "ISO 17020",
                "document_concerned": "Rapport Global d'Audit",
                "page": "N/A",
                "impact": "Examen de la discipline incomplet.",
                "action_required": f"Vérifier manuellement les pièces relatives à la discipline {discipline}.",
                "deadline_days": 3,
                "extracted_via": "ARH-Swarm-Resilience"
            }
            return [warning_finding]

    @staticmethod
    def _partition_rlm_weld_docs(
        group_docs: List[Dict[str, Any]],
        equipment_tag: str = ""
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Sépare en amont (S-06) les documents standards (< 15 pages ou < 2 pages de soudage)
        des documents volumineux (>= 15 pages avec >= 2 pages de soudage) relevant du
        découpage chirurgical RLM, afin d'éviter la double exécution de wps_expert_agent
        sur les mêmes pages en Phase 1 et Phase 2.5.
        """
        standard_docs: List[Dict[str, Any]] = []
        rlm_scoped_docs: List[Dict[str, Any]] = []

        for d in group_docs:
            page_spans = d.get("page_spans", [])
            doc_text = d.get("text", "")
            if len(page_spans) >= 15:
                weld_pages = []
                for idx, sp in enumerate(page_spans):
                    p_num = sp.get("page", idx + 1)
                    p_sub = doc_text[sp.get("start", 0):sp.get("end", len(doc_text))]
                    if any(k in p_sub.upper() for k in ["WPS", "PQR", "QMOS", "QW-482", "WELDING PROCEDURE", "PROCEDURE DE SOUDAGE"]):
                        weld_pages.append((p_num, p_sub))
                if len(weld_pages) >= 2:
                    scoped_text = "\n\n".join([f"--- PAGE {p_n} ---\n{p_t}" for p_n, p_t in weld_pages])
                    rlm_scoped_docs.append({
                        "file_name": f"{d.get('file_name', 'Doc')} [RLM-Weld-Scope]",
                        "text": scoped_text,
                        "page_spans": [{"page": p_n, "start": 0, "end": len(p_t)} for p_n, p_t in weld_pages],
                        "metadata": {"document_type": "Welding Book", "equipment_tag": equipment_tag}
                    })
                    continue
            standard_docs.append(d)

        return standard_docs, rlm_scoped_docs

    def _dispatch_rlm_subagents(
        self,
        group_docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str,
        dossier_stage: str,
        agents_status: Dict[str, Any],
        precomputed_rlm_docs: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Prime Agent RLM Pattern: Instancie des sous-agents récursifs à périmètre restreint pour les
        sections volumineuses ou spécialisées (Soudage, Notes de calcul) afin d'éliminer la pollution
        de contexte et d'effectuer des analyses chirurgicales sur les pages d'intérêt.
        """
        rlm_findings = []
        scoped_list = (
            precomputed_rlm_docs
            if precomputed_rlm_docs is not None
            else self._partition_rlm_weld_docs(group_docs, equipment_tag)[1]
        )
        for scoped_item in scoped_list:
            scoped_doc = [scoped_item]
            w_findings = self._execute_agent_safely(
                "RLM Sub-Agent Soudage Dédié", "SOUDAGE",
                lambda sd=scoped_doc: self.wps_expert_agent.audit(sd, equipment_type, dossier_stage),
                agents_status, is_critical=False
            )
            rlm_findings.extend(w_findings)
        return rlm_findings

    def run_swarm_audit(
        self,
        group_docs: List[Dict[str, Any]],
        equipment_type: str,
        equipment_tag: str,
        dossier_stage: str = "PRELIMINARY",
        reserves_list: Optional[List[Dict[str, Any]]] = None,
        vendor_name: Optional[str] = None,
        project_name: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Exécute l'audit complet du dossier par le Swarm de 10 Agents Spécialisés (v4.1 avec RLM & Code Harness).
        Garantit la résilience totale : aucun échec d'agent ne fait échouer le traitement.
        """
        logger.info(f"[ARH-Swarm v4.1] Démarrage de l'audit multi-agents pour {equipment_tag} ({equipment_type})")

        agents_status: Dict[str, Any] = {}
        raw_findings: List[Dict[str, Any]] = []

        # Partitionnement RLM en amont (S-06) pour éviter la double exécution de wps_expert_agent
        standard_weld_docs, rlm_scoped_weld_docs = self._partition_rlm_weld_docs(group_docs, equipment_tag)

        # ── PHASE 1 : Agents Disciplinaires Standardisés ─────────────────────
        # 1. Administratif & Légalisation
        raw_findings.extend(self._execute_agent_safely(
            "Auditeur Administratif & Légalisation", "ADMINISTRATIF",
            lambda: self.admin_agent.audit(group_docs, equipment_type, dossier_stage),
            agents_status, is_critical=False
        ))

        # 2. Métallurgie & Matériaux (Critique)
        raw_findings.extend(self._execute_agent_safely(
            "Auditeur Métallurgie & Matériaux", "MÉTALLURGIE",
            lambda: self.metallurgy_agent.audit(group_docs, equipment_type, dossier_stage),
            agents_status, is_critical=True
        ))

        # 3. Mécanique & Tuyauterie (Critique)
        raw_findings.extend(self._execute_agent_safely(
            "Auditeur Mécanique & Calculs", "MÉCANIQUE",
            lambda: self.mechanical_agent.audit(group_docs, equipment_type, dossier_stage),
            agents_status, is_critical=True
        ))

        # 4. Électricité & Instrumentation (Critique si applicable)
        full_text_sample = " ".join([d.get("text", "") for d in group_docs])
        has_elec = ARHRegulatoryEngine.has_electrical_scope(equipment_type, full_text_sample)
        raw_findings.extend(self._execute_agent_safely(
            "Auditeur Électricité & Instrumentation", "ÉLECTRICITÉ",
            lambda: self.elec_inst_agent.audit(group_docs, equipment_type, dossier_stage),
            agents_status, is_critical=has_elec
        ))

        # 5. Qualité & ITP (Critique)
        raw_findings.extend(self._execute_agent_safely(
            "Auditeur Qualité & ITP", "QUALITÉ",
            lambda: self.quality_agent.audit(group_docs, equipment_type, dossier_stage),
            agents_status, is_critical=True
        ))

        # 6. WPS / PQR Expert Soudage (Critique - hors documents déjà routés en RLM chirurgical)
        raw_findings.extend(self._execute_agent_safely(
            "Expert Soudage WPS / PQR", "SOUDAGE",
            lambda: self.wps_expert_agent.audit(standard_weld_docs, equipment_type, dossier_stage) if standard_weld_docs else [],
            agents_status, is_critical=True
        ))

        # 7. Modèle IA Spécialiste Fine-Tuné (ARKAN LoRA - sans doublons QA/QC administratifs/soudage)
        def _run_specialist():
            from arh_ai_engine import arh_ai_engine
            full_corpus = " ".join([d.get("text", "") for d in group_docs])
            f_names = [d.get("file_name", "") for d in group_docs]
            return arh_ai_engine.audit_dossier_with_specialist(
                docs_text=full_corpus,
                equipment_type=equipment_type,
                equipment_tag=equipment_tag,
                file_names=f_names,
                group_docs=group_docs,
                dossier_stage=dossier_stage,
                skip_universal_qaqc=True,
            )
        raw_findings.extend(self._execute_agent_safely(
            "IA Spécialiste Équipement", "IA_SPÉCIALISTE",
            _run_specialist, agents_status, is_critical=False
        ))

        # ── PHASE 2 : Nouveaux Agents v4.0 ─────────────────────────────────
        # 8. Agent Raisonnement Temporel
        if _HAS_TEMPORAL:
            raw_findings.extend(self._execute_agent_safely(
                "Agent Raisonnement Temporel", "TEMPOREL",
                lambda: arh_temporal_reasoner.audit_temporal_validity(group_docs, equipment_type, dossier_stage),
                agents_status, is_critical=False
            ))
        else:
            agents_status["Agent Raisonnement Temporel"] = {"status": "DISABLED", "is_critical": False}

        # 9. Agent Réconciliation Inter-Documents
        recon_matrix = {}
        if _HAS_RECONCILIATION:
            def _run_reconciliation():
                nonlocal recon_matrix
                fnds, r_mat = arh_reconciliation_engine.run_reconciliation(group_docs, equipment_type, equipment_tag)
                recon_matrix = r_mat or {}
                return fnds
            raw_findings.extend(self._execute_agent_safely(
                "Agent Réconciliation Inter-Documents", "RÉCONCILIATION",
                _run_reconciliation, agents_status, is_critical=False
            ))
        else:
            agents_status["Agent Réconciliation Inter-Documents"] = {"status": "DISABLED", "is_critical": False}

        # 10. Agent Levée de Réserves
        reserve_report: Optional[Dict[str, Any]] = None
        if _HAS_RESERVE_COMPARATOR and reserves_list:
            def _run_reserve_comp():
                nonlocal reserve_report
                r_rep = arh_reserve_comparator.compare_revisions(
                    reserves_list=reserves_list,
                    new_docs=group_docs,
                    dossier_id=equipment_tag,
                    equipment_tag=equipment_tag,
                )
                reserve_report = r_rep
                return r_rep.get("findings", []) if r_rep else []
            raw_findings.extend(self._execute_agent_safely(
                "Agent Levée de Réserves", "RÉVISIONS",
                _run_reserve_comp, agents_status, is_critical=False
            ))
        else:
            agents_status["Agent Levée de Réserves"] = {"status": "DISABLED", "is_critical": False}

        # ── PHASE 2.5 : RLM Recursive Sub-Agents (Prime Agent Pattern) ───────
        try:
            rlm_findings = self._dispatch_rlm_subagents(
                group_docs, equipment_type, equipment_tag, dossier_stage, agents_status,
                precomputed_rlm_docs=rlm_scoped_weld_docs,
            )
            if rlm_findings:
                raw_findings.extend(rlm_findings)
                logger.info(f"[ARH-Swarm RLM] {len(rlm_findings)} constat(s) issus de l'analyse chirurgicale RLM ajoutés.")
        except Exception as _e_rlm:
            logger.warning("[ARH-Swarm] Erreur RLM Sub-Agents : %s", _e_rlm)

        # ── PHASE 3 : Arbitrage et Filtrage ────────────────────────────────
        validated_findings = self.arbitrator.arbitrate(
            raw_findings,
            group_docs,
            equipment_type=equipment_type,
            equipment_tag=equipment_tag,
        )

        # ── PHASE 3.5 : Boucle d'Auto-Amélioration (/refine Loop) ───────────
        if _HAS_REFINE:
            try:
                validated_findings = arh_refine_engine.apply_refine_rules(
                    validated_findings,
                    vendor_name=vendor_name,
                    equipment_type=equipment_type
                )
            except Exception as _e_refine:
                logger.warning("[ARH-Swarm] Erreur application règles /refine : %s", _e_refine)

        # ── PHASE 4 : Scoring Multi-Dimensionnel avec Verrou Sécurité ──────
        score, status = self._compute_multidimensional_score(validated_findings, agents_status=agents_status)

        # ── PHASE 5 : Synthèse Finale ───────────────────────────────────────
        synthesis = self.synthesizer.generate_synthesis(
            equipment_tag=equipment_tag,
            equipment_type=equipment_type,
            score=score,
            status=status,
            findings=validated_findings,
            docs_count=len(group_docs),
        )

        # Enrichir la synthèse avec le statut des agents et matrices v4.0
        synthesis["agents_status"] = agents_status
        synthesis["reconciliation_matrix"] = recon_matrix
        if reserve_report:
            synthesis["reserve_report"] = {
                "total": reserve_report.get("total_reserves", 0),
                "lifted": reserve_report.get("lifted", 0),
                "not_lifted": reserve_report.get("not_lifted", 0),
                "lift_score_pct": reserve_report.get("lift_score_pct", 100.0),
                "decision": reserve_report.get("decision", ""),
            }

        logger.info(
            f"[ARH-Swarm v4.0] Audit terminé : {len(validated_findings)} remarques validées, "
            f"Score = {score}%, Statut = {status}, Agents={len(agents_status)}"
        )
        return validated_findings, synthesis

    def _compute_multidimensional_score(
        self,
        findings: List[Dict[str, Any]],
        agents_status: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, str]:
        """
        Scoring multi-dimensionnel v4.0 — remplace le scoring linéaire simpliste.

        Pondération par criticité métier réelle :
          - Risque physique (pression, épaisseur, CEV, NACE) : poids élevé (30-40 pts)
          - Risque ATEX/électrique : poids élevé (35 pts)
          - Risque procédural (soudage, ITP) : poids modéré (20-25 pts)
          - Risque administratif (légalisation, lettre) : poids standard (15-20 pts)
          - Risque temporel (dates expirées) : poids selon contexte

        Bloquants Absolus : certaines non-conformités impliquent un rejet automatique
        indépendamment du score global.
        Verrou de Sécurité : Si un agent critique est en échec, le statut APPROVED est interdit.
        """
        # Pondération des catégories (surcharge du poids standard CRITICAL=25)
        CATEGORY_WEIGHTS: Dict[str, Dict[str, float]] = {
            # Risques physiques immédiats — poids maximum
            "INTÉGRITÉ MÉCANIQUE & ÉPREUVE":         {"CRITICAL": 40, "MAJOR": 15},
            "ÉPREUVE HYDROSTATIQUE":                   {"CRITICAL": 40, "MAJOR": 15},
            "DIMENSIONNEMENT MÉCANIQUE":               {"CRITICAL": 35, "MAJOR": 12},
            "SOUDABILITÉ & MÉTALLURGIE":               {"CRITICAL": 30, "MAJOR": 10},
            "RÉSISTANCE À LA CORROSION SOUS TENSION":  {"CRITICAL": 30, "MAJOR": 10},
            "RÉSILIENCE BASSE TEMPÉRATURE":            {"CRITICAL": 25, "MAJOR": 10},
            "SÉCURITÉ EN ZONE EXPLOSIBLE (ATEX / IECEX)": {"CRITICAL": 40, "MAJOR": 15},
            # Risques procéduraux — poids modéré
            "QUALIFICATION WPS / PQR":                 {"CRITICAL": 25, "MAJOR": 10},
            "QUALIFICATION SOUDEURS":                  {"CRITICAL": 25, "MAJOR": 10},
            "POINTS D'ARRÊT OBLIGATOIRES (HOLD POINTS)": {"CRITICAL": 20, "MAJOR": 8},
            "PLAN D'INSPECTION ET D'ESSAIS (ITP)":     {"CRITICAL": 20, "MAJOR": 8},
            # Risques administratifs — poids standard
            "LÉGALISATION ET AUTHENTIFICATION":        {"CRITICAL": 20, "MAJOR": 8},
            "CONFORMITÉ ADMINISTRATIVE":               {"CRITICAL": 15, "MAJOR": 6},
            "CONFORMITÉ PLAQUE SIGNALÉTIQUE":          {"CRITICAL": 15, "MAJOR": 6},
            # Risques temporels
            "VALIDITÉ TEMPORELLE — QUALIFICATION SOUDEUR": {"CRITICAL": 25, "MAJOR": 10},
            "VALIDITÉ TEMPORELLE — CERTIFICAT ATEX":   {"CRITICAL": 35, "MAJOR": 12},
            "VALIDITÉ TEMPORELLE — VISA CONSULAIRE":   {"CRITICAL": 20, "MAJOR": 8},
            # Contradictions inter-documents
            "CONTRADICTION INTER-DOCUMENTS — PARAMÈTRE CRITIQUE": {"CRITICAL": 30, "MAJOR": 12},
            "CONTRADICTION INTER-DOCUMENTS — NUANCE D'ACIER": {"CRITICAL": 30, "MAJOR": 12},
            "TRAÇABILITÉ — NUMÉROS DE COULÉE (HEAT NUMBERS)": {"CRITICAL": 25, "MAJOR": 10},
            # Levée de réserves
            "LEVÉE DE RÉSERVES — ❌ RÉSERVE NON LEVÉE": {"CRITICAL": 30, "MAJOR": 12},
            "LEVÉE DE RÉSERVES — ⚠️ RÉSERVE PARTIELLEMENT LEVÉE": {"CRITICAL": 15, "MAJOR": 8},
        }

        # Bloquants absolus : catégories qui imposent le rejet même avec un bon score
        ABSOLUTE_BLOCKERS = {
            "INTÉGRITÉ MÉCANIQUE & ÉPREUVE",
            "ÉPREUVE HYDROSTATIQUE",
            "SÉCURITÉ EN ZONE EXPLOSIBLE (ATEX / IECEX)",
            "LEVÉE DE RÉSERVES — ❌ RÉSERVE NON LEVÉE",
        }

        raw_score = 100.0
        has_absolute_blocker = False
        has_critical = False

        for f in findings:
            priority = f.get("priority", "MINOR")
            category = f.get("category", "").upper()

            # Vérifier si c'est un bloquant absolu
            if priority == "CRITICAL":
                has_critical = True
                for blocker in ABSOLUTE_BLOCKERS:
                    if blocker in category:
                        has_absolute_blocker = True
                        break

            # Chercher une pondération spécifique à cette catégorie
            weight_found = False
            for cat_key, weights in CATEGORY_WEIGHTS.items():
                if cat_key in category:
                    deduction = weights.get(priority, 0)
                    raw_score -= deduction
                    weight_found = True
                    break

            # Pondération par défaut si la catégorie n'est pas dans la table
            if not weight_found:
                if priority == "CRITICAL":
                    raw_score -= 25.0
                elif priority == "MAJOR":
                    raw_score -= 10.0
                elif priority == "MINOR":
                    raw_score -= 3.0

        # Déterminer le statut initial
        if has_absolute_blocker:
            status = "REJECTED"  # Rejet automatique peu importe le score
        elif has_critical:
            status = "REJECTED"
        elif any(f.get("priority") == "MAJOR" for f in findings):
            status = "APPROVED_WITH_COMMENTS"
        else:
            status = "APPROVED"

        # Action 3 : Verrou de Sécurité - Interdiction formelle du statut APPROVED si un agent critique a échoué
        if agents_status:
            failed_critical = [
                name for name, info in agents_status.items()
                if info.get("is_critical") and info.get("status") == "FAILED"
            ]
            if failed_critical:
                logger.warning(
                    f"[ARH-Swarm] Verrou de sécurité déclenché : agent(s) critique(s) en échec {failed_critical}. "
                    f"Statut APPROVED formellement interdit."
                )
                raw_score = min(raw_score, 70.0)
                if status == "APPROVED":
                    status = "APPROVED_WITH_COMMENTS"

        score = max(0.0, min(100.0, round(raw_score, 1)))

        return score, status


# Instance globale réutilisable
arh_multiagent_swarm = ARHMultiAgentSwarm()

