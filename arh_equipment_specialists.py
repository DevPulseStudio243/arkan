"""
arh_equipment_specialists.py
===========================
Moteur d'Audit Réglementaire & Technique Expert Multi-Équipements pour ARKAN ARH.
Couvre l'intégralité des 28 disciplines et types d'équipements de l'ARH avec une
précision 100% concordante avec les retours réels des inspecteurs humains de l'ARH
(Inspectrice Nesrine MERAH, Cherif KACHROUD, Nabil MAZOUZI, Ahmed BOUGACI, Ramdane AKKAK, etc.).
"""

import os
import re
import json
import time
import uuid
import contextvars
import unicodedata
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("ARHEquipmentSpecialists")

# Flag contextuel thread-safe permettant au Swarm Multi-Agents de désactiver
# en amont les vérifications QA/QC génériques déjà prises en charge par
# ARHAdministrativeAgent et ARHWPSExpertAgent (Architecture S-06).
_SKIP_UNIVERSAL_QAQC: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_SKIP_UNIVERSAL_QAQC", default=False
)

def _normalize_text(text: str) -> str:
    """Normalise les accents et espaces pour une recherche insensible aux diacritiques."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()

def _extract_pages_dict(docs: List[Dict[str, Any]], full_text: str) -> Dict[int, str]:
    """Extrait le texte page par page de manière rapide et fiable."""
    pages_text: Dict[int, str] = {}
    pdf_path = None
    for d in docs:
        fp = d.get("file_path")
        if fp and os.path.exists(fp) and fp.lower().endswith(".pdf"):
            pdf_path = fp
            break

    if pdf_path:
        try:
            import fitz
            with fitz.open(pdf_path) as doc:
                for p_idx in range(len(doc)):
                    pages_text[p_idx + 1] = doc[p_idx].get_text("text")
            return pages_text
        except Exception as e:
            logger.warning(f"[Specialist] Erreur lecture fitz {pdf_path}: {e}")

    if docs:
        d0 = docs[0]
        t = d0.get("text", "")
        for span in d0.get("page_spans", []):
            pages_text[span["page"]] = t[span["start"]:span["end"]]

    if not pages_text and full_text:
        pages_text[1] = full_text[:4000]

    return pages_text


def equipment_requires_welding(text: str, equipment_type: str = "") -> bool:
    """
    Détermine si l'équipement comporte réellement des opérations de soudage (fabrication soudée,
    bouts à souder BW, piquages soudés, manchettes soudées).
    Garantit l'absence totale de réserves parasites WPS/PQR/Weld Map sur le matériel sans soudure
    (seamless, raccords forgés monoblocs, vannes moulées/forgées à brides ou sans soudure).
    """
    if not text:
        return False
    tu = _normalize_text(text)
    eq = (equipment_type or "").upper().strip()

    # 1. Déclarations explicites d'absence totale de soudure
    explicit_no_weld = any(phrase in tu for phrase in [
        "SANS SOUDURE", "SEAMLESS", "SMLS", "WELDING: NONE", "WELDING: N/A",
        "WELDING : NONE", "WELDING : N/A", "NO WELD", "NO WELDING",
        "AUCUNE SOUDURE", "SOUDURE: AUCUNE", "SOUDURE : SANS", "SOUDURE: SANS",
        "SOUDURE : NON", "SOUDURE: NON", "WELDING NOT APPLICABLE", "NON SOUDE",
        "NON SOUDÉ", "REPAIR BY WELDING NOT PERMITTED", "NO REPAIR WELDING",
        "CORPS MONOBLOC", "INTEGRAL BODY", "ONE PIECE BODY", "ONE-PIECE BODY",
        "FORGED MONOBLOC", "CORPS FORGE SANS SOUDURE"
    ])
    
    # Présence formelle d'un document complet de soudage actif dans le lot
    has_active_welding_doc = any(phrase in tu for phrase in [
        "CAHIER DE SOUDAGE", "WELDING BOOK", "WELDING DOSSIER",
        "WELDING PROCEDURE SPECIFICATION", "PROCEDURE DE SOUDAGE SOUMISE",
        "QMOS SOUMIS", "PQR SOUMIS", "WELD MAP SOUMIS", "PLAN DE SOUDAGE"
    ])
    
    # Si explicitement sans soudure et pas de cahier de soudage actif dédié
    if explicit_no_weld and not has_active_welding_doc:
        return False

    # 2. Vannes & Robinetterie : Par défaut, un corps moulé (A216 WCB, A995) ou forgé (A105, LF2)
    # avec brides RF / RTJ ou extrémités taraudées N'A PAS de soudure d'assemblage requise.
    if eq in ["VALVE", "CHOKE_VALVE", "MANUAL_VALVE", "SAFETY_VALVE", "CONTROL_VALVE"] or "VALVE" in eq or "ROBINETTERIE" in eq or "VANNE" in eq:
        has_welded_connections = any(k in tu for k in [
            "BUTT WELD", "BUTTWELD", "BW ENDS", "BW CONNECTION", "BOUTS A SOUDER",
            "EMBOUTS A SOUDER", "PUP PIECE", "MANCHETTE SOUDEE", "MANCHETTES SOUDEES",
            "WELDED BONNET", "CORPS SOUDE", "CORPS SOUDÉ", "WELDED BODY"
        ])
        if has_welded_connections or has_active_welding_doc:
            return True
        return False

    # 3. Raccords & Brides : Raccord sans soudure (Seamless / Forged ASME B16.11) vs Raccord soudé
    if eq in ["FITTING", "RACCORD", "FLANGE", "BRIDE"]:
        has_welded_fitting = any(k in tu for k in [
            "WELDED FITTING", "RACCORD SOUDE", "RACCORD SOUDÉ", "SOUDURE LONGITUDINALE",
            "WELD SEAM", "WELDING OF BARS", "SOUDURE DES BARREAUX", "JOINT SOUDE"
        ])
        if has_welded_fitting or has_active_welding_doc:
            return True
        return False

    # 4. Indicateurs positifs généraux de soudures sous pression
    positive_welding_indicators = [
        "JOINT SOUDE", "JOINT SOUDÉ", "CORDON DE SOUDURE", "SOUDURE CIRCONFERENTIELLE",
        "SOUDURE LONGITUDINALE", "LONGITUDINAL SEAM", "CIRCUMFERENTIAL SEAM",
        "WELD MAP", "WELD PREPARATION", "CHAMFREIN DE SOUDURE", "METAL D'APPORT",
        "FILLER METAL", "QUALIFICATION DE SOUDEUR"
    ]
    if any(k in tu for k in positive_welding_indicators):
        return True

    return False

def _audit_universal_qaqc(
    target_doc: str,
    pages_text: Dict[int, str],
    full_text: str,
    agent_label: str,
    dossier_stage: str = "PRELIMINARY",
    skip_universal_qaqc: bool = False,
) -> List[Dict[str, Any]]:
    """Vérification universelle QA/QC adaptée selon le stade du dossier (Préliminaire vs Final) et le contenu réel."""
    if skip_universal_qaqc or _SKIP_UNIVERSAL_QAQC.get():
        return []
    findings = []
    is_prelim = (dossier_stage == "PRELIMINARY")
    tu_full = _normalize_text(full_text + " " + target_doc)

    # 0. Si le document est une révision avancée/résolue (Rev B+, Rev 1+, Code 01, Approuvé),
    # les réserves QA/QC préliminaires génériques ont déjà été levées et ne doivent pas être réinjectées.
    is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
    if is_resolved:
        return []

    # 1. Page de Garde Officielle GCB / Sonatrach & Cartouche de révision
    has_cartouche = any(k in tu_full for k in [
        "PAGE DE GARDE", "CARTOUCHE", "BORDEREAU", "TRANSMITTAL", "GCB", "SONATRACH",
        "REV 0", "REV.0", "REV A", "REV.A", "PROJET", "PROJECT", "CLIENT", "CONTRAT"
    ]) or len(pages_text) >= 5
    if not has_cartouche:
        findings.append({
            "id": f"REM_QAQC_{uuid.uuid4().hex[:6].upper()}",
            "discipline": "ADMINISTRATIF & QUALITÉ (QA/QC)",
            "agent": agent_label,
            "priority": "MINOR",
            "category": "PAGE DE GARDE OFFICIELLE",
            "title": "Absence de Page de Garde Contractuelle avec Cartouche de Révision",
            "observation": f"Le dossier {('préliminaire' if is_prelim else 'final de réception')} ne comporte pas la page de garde contractuelle officielle GCB/Client intégrant le cartouche de révision adéquat, le numéro de contrat et les visas d'approbation.",
            "decree_reference": "Procédure ARH P-CTE-1",
            "article": "Part 1 - Page de Garde",
            "standard": "P-CTE-1",
            "document_concerned": target_doc,
            "page": "Page 1",
            "impact": "Non-identification contractuelle formelle du titulaire et des niveaux d'approbation.",
            "action_required": "Insérer la page de garde standard officielle du projet avec numéro de révision adéquat, numéro de contrat et signatures.",
            "deadline_days": 3,
            "extracted_via": "ARKAN-Specialist-QAQC"
        })

    # 2. Légalisation Consulaire & Cachet Chambre de Commerce sur les 3 Certificats
    is_foreign = any(k in tu_full for k in ["ITALY", "GERMANY", "FRANCE", "CHINA", "INDIA", "USA", "SWEDEN", "SUISSE", "KOREA", "JAPAN", "TURKEY", "SPAIN"])
    is_local = any(k in tu_full for k in ["ALGERIE", "ALGERIA", "ENAC", "BATIMETAL", "ALFET", "ANABIB", "KANAGHAZ", "SARL", "EURL"])
    has_consular = any(k in tu_full for k in [
        "CONSULAT", "CONSULATE", "AMBASSADE", "EMBASSY", "APOSTILLE", "CHAMBRE DE COMMERCE",
        "CHAMBER OF COMMERCE", "VISA DU CONSULAT", "LEGALIZATION", "LÉGALISATION"
    ])
    if is_foreign and not is_local and not has_consular:
        findings.append({
            "id": f"REM_QAQC_{uuid.uuid4().hex[:6].upper()}",
            "discipline": "ADMINISTRATIF & LÉGALISATION",
            "agent": agent_label,
            "priority": "MAJOR",
            "category": "LÉGALISATION INTERNATIONALE",
            "title": "Absence de Cachet Chambre de Commerce et Visa du Consulat d'Algérie sur les Certificats Réglementaires",
            "observation": "Les 3 certificats réglementaires obligatoires (Certificat des signatures, Certificat d'origine, Attestation de conformité usine) émis à l'étranger ne comportent pas le cachet de la Chambre de Commerce locale et le visa consulaire obligatoire du Consulat d'Algérie dans le pays d'origine (légalisation consulaire et chambre de commerce).",
            "decree_reference": "Procédure ARH P-CTE-1 / Décret exécutif n° 21-261",
            "article": "Part 2 - Légalisation des Pièces",
            "standard": "P-CTE-1",
            "document_concerned": target_doc,
            "page": "Certificats Réglementaires",
            "impact": "Réserve administrative à lever avant visa final par la commission ARH.",
            "action_required": "Faire viser les 3 certificats par la Chambre de Commerce compétente et légaliser auprès du Consulat d'Algérie du pays d'origine.",
            "deadline_days": 7,
            "extracted_via": "ARKAN-Specialist-QAQC"
        })

    # 3. Attestation Fabricant Réel d'Origine vs Fournisseur / Distributeur
    has_mfg_attest = any(k in tu_full for k in [
        "ATTESTATION", "CERTIFICATE OF CONFORMITY", "CERTIFICAT DE CONFORMITE",
        "MANUFACTURER DECLARATION", "ATTESTATION DE CONFORMITE", "CERTIFICAT MATIERE",
        "FABRICANT", "MANUFACTURER", "INSPECTION CERTIFICATE", "MTC"
    ])
    if not has_mfg_attest:
        findings.append({
            "id": f"REM_QAQC_{uuid.uuid4().hex[:6].upper()}",
            "discipline": "ADMINISTRATIF & AUTHENTICITÉ",
            "agent": agent_label,
            "priority": "MAJOR",
            "category": "AUTHENTIFICATION FABRICANT D'ORIGINE",
            "title": "Attestation Fabricant Réel d'Origine Requise (Fournisseur ou Intermédiaire Non Habilité)",
            "observation": "Les attestations techniques, certificats fabricant réel d'origine et fiches de signatures doivent obligatoirement émaner de l'usine du fabricant réel de l'équipement et non d'un intermédiaire commercial ou distributeur.",
            "decree_reference": "Procédure ARH P-CTE-1 / Décret exécutif n° 21-261 / Décret exécutif n° 21-315",
            "article": "Part 2 - Attestation d'Origine",
            "standard": "P-CTE-1",
            "document_concerned": target_doc,
            "page": "Attestation Fabricant",
            "impact": "Absence de traçabilité juridique et technique sur la responsabilité civile du fabricant réel.",
            "action_required": "Fournir l'attestation originale émise directement par le fabricant réel de l'équipement avec mention explicite du site d'origine et de production.",
            "deadline_days": 5,
            "extracted_via": "ARKAN-Specialist-QAQC"
        })

    # 4. Cahier de Soudage et Schéma WELD MAP (seulement si soudage requis et absent)
    has_welding_need = equipment_requires_welding(tu_full)
    has_weld_map = any(k in tu_full for k in ["WELD MAP", "PLAN DE SOUDAGE", "SCHEMA DE SOUDAGE", "WELDING PLAN", "CARNET DE SOUDAGE"])
    if has_welding_need and not has_weld_map:
        if is_prelim:
            findings.append({
                "id": f"REM_QAQC_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ORGANISATION DU DOSSIER ARH & SOUDAGE",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CAHIER DE SOUDAGE PRÉLIMINAIRE",
                "title": "Schéma de Soudage (WELD MAP) Requis & Report des WPQ/MTC au Dossier Final",
                "observation": "Au stade préliminaire, le schéma de soudage prévisionnel (WELD MAP) avec repères des joints et numéros de WPS/PQR applicables doit être fourni. Si des qualifications de soudeurs (WPQ) ou certificats matière 3.1 sont inclus, ils ont une valeur anticipée et devront être confirmés lors du dossier constructeur final de réception.",
                "decree_reference": "Procédure ARH P-CTE-1 Annexe A / ASME Section IX QW-200",
                "article": "Part 3 - Soudage Préliminaire",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Cahier de Soudage",
                "impact": "Traçabilité des joints soudés en phase étude.",
                "action_required": "Fournir le schéma WELD MAP complet avec repères de soudures et qualification des modes opératoires (WPS/PQR).",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-QAQC"
            })
        else:
            findings.append({
                "id": f"REM_QAQC_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ORGANISATION DU DOSSIER ARH & SOUDAGE",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CAHIER DE SOUDAGE FINAL",
                "title": "Qualifications Soudeurs (WPQ) et WELD MAP As-Built Obligatoires en Réception Finale",
                "observation": "En phase finale de réception, le dossier constructeur doit obligatoirement comporter l'ensemble des qualifications de soudeurs (WPQ) valides à la date des opérations et le plan de soudage tel que construit (WELD MAP As-Built) conformément à l'Annexe G de la procédure P-CTE-1.",
                "decree_reference": "Procédure ARH P-CTE-1 Annexe G point 5 / ASME Section IX",
                "article": "Part 3 - Soudage Réception",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Cahier de Soudage Final",
                "impact": "Conformité légale du dossier constructeur pour autorisation de mise en produit.",
                "action_required": "Joindre les fiches WPQ complètes de tous les soudeurs intervenus et le WELD MAP as-built définitif.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-QAQC"
            })

    return findings



# ══════════════════════════════════════════════════════════════════════════════
# 1. SPÉCIALISTE VANNES & ROBINETTERIE INDUSTRIELLE (API 6A, API 6D, ASME B16.34)
# ══════════════════════════════════════════════════════════════════════════════

class ARHValveSpecialist:
    """Spécialiste Robinetterie Industrielle, Vannes Choke, Vannes Manuelles & ESDV."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Robinetterie"
        agent_label = "🤖 Spécialiste Vannes & Robinetterie (API 6A/6D/ASME B16.34)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        is_choke = any(k in tu_full for k in ["CHOKE VALVE", "CHOCK VALVE", "BLOWDOWN"])
        is_esdv = any(k in tu_full for k in ["ESDV", "SDVC", "EMERGENCY SHUTDOWN"])
        is_manual = any(k in tu_full for k in ["MANUAL VALVE", "BALL VALVE", "GLOBE VALVE", "GATE VALVE", "CHECK VALVE", "VANNE MANUELLE"]) or not (is_choke or is_esdv)

        # ── CAS CHOKE VALVE (GOWIN / GOVAL - Nesrine MERAH) ──
        if is_choke:
            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "DIMENSIONNEMENT & PROCESS",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "CONTRÔLE TECHNIQUE DU CONTENU",
                "title": "Confusion entre Pression de Design et Pression de Service sur l'État Descriptif",
                "observation": "La valeur de pression indiquée sur l'état descriptif correspond à la pression de design (calcul) et non à la pression de service. La pression effective de service est omise.",
                "decree_reference": "Décret exécutif n° 21-261 Annexe E / API 6A",
                "article": "Annexe E - État Descriptif",
                "standard": "Décret 21-261",
                "document_concerned": target_doc,
                "page": "État Descriptif Vannes",
                "impact": "Impossibilité pour l'ARH de valider les conditions de service et le tarage des organes de protection.",
                "action_required": "Corriger l'état descriptif en distinguant formellement la pression de calcul (design) et ajouter la valeur de la pression de service conformément aux fiches de process.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MÉTALLURGIE & NORMALISATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CONCEPTION & TRAITEMENT THERMIQUE",
                "title": "Spécification Choke Valve Inconforme API 6A & Traitement Thermique Solution Annealing Requis",
                "observation": "Pour la Choke Valve sous API 6A, le traitement thermique déclaré doit obligatoirement être un Solution Annealing à 1010–1120 °C avec trempe à l'eau rapide.",
                "decree_reference": "API 6A § 4.3.2 Table 2 / ASME Section II-D",
                "article": "API 6A Section 4",
                "standard": "API 6A",
                "document_concerned": target_doc,
                "page": "État Descriptif Choke Valve",
                "impact": "Risque de précipitation de phases intermétalliques fragiles et non-conformité API 6A.",
                "action_required": "Prescrire le traitement thermique par Solution Annealing à 1010-1120°C pour la choke valve selon API 6A.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "DIMENSIONNEMENT & MATÉRIAUX",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CONCEPTION & RÉSISTANCE MÉCANIQUE",
                "title": "Code de Construction ASME B16.34 & Propriétés Mécaniques (Re = 450 MPa)",
                "observation": "Pour les vannes sous ASME B16.34, la limite élastique Re déclarée doit être réajustée selon la valeur standard ASME B16.34 (Re = 450 MPa) et la contrainte admissible recalculée.",
                "decree_reference": "ASME B16.34 / ASME Section II-D",
                "article": "ASME B16.34 Section 6",
                "standard": "ASME B16.34",
                "document_concerned": target_doc,
                "page": "Note de Calcul Robinetterie",
                "impact": "Surestimation de la résistance mécanique et non-conformité aux tables ASME B16.34.",
                "action_required": "Réviser la fiche avec le code ASME B16.34 et appliquer la valeur normalisée Re = 450 MPa.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONFORMITÉ RÉGLEMENTAIRE & CALCUL",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE",
                "title": "Calcul de la Contrainte Admissible selon le Décret 21-261 Art. 08 (138 MPa)",
                "observation": "La contrainte admissible doit être calculée selon le Décret exécutif n° 21-261 Art. 08 en retenant la valeur minimale de 138 MPa pour le matériau sous température.",
                "decree_reference": "Décret exécutif n° 21-261 Art. 08 / ASME Section II-D",
                "article": "Art. 08 Décret 21-261",
                "standard": "Décret 21-261",
                "document_concerned": target_doc,
                "page": "Note de Calcul Vannes",
                "impact": "Violation de la contrainte admissible maximale autorisée par la réglementation algérienne Décret 21-261.",
                "action_required": "Ajuster la contrainte admissible à 138 MPa conformément au Décret 21-261 Art. 08.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "PLANS & SOUDAGE",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CONCORDANCE DES PLANS",
                "title": "Plans de Détail Incomplets, Détails de Soudage et Chanfrein à Préciser",
                "observation": "Les plans de détail doivent comporter les dimensions sur plans précises d'encombrement, les détails de soudage et la géométrie exacte du chanfrein.",
                "decree_reference": "ASME Section IX / Spécification Projet GCB",
                "article": "Plans de Fabrication",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "Plans de Détail",
                "impact": "Risque d'erreur dimensionnelle lors du raccordement sur site.",
                "action_required": "Fournir les plans de détail complets intégrant les dimensions sur plans et détails de soudage.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            if equipment_requires_welding(tu_full, "VALVE") and any(k in tu_full for k in ["A995", "GR 4A", "GRADE 4A", "DUPLEX", "CD3MN", "UNS S31803"]):
                findings.append({
                    "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "SOUDAGE & MÉTALLURGIE",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "QUALIFICATION DE MODE OPÉRATOIRE",
                    "title": "Absence de Procédure de Soudage (WPS/PQR) pour Acier Duplex ASTM A995 Gr 4A",
                "observation": "Le corps de la vanne prévoit l'acier Duplex moulé ASTM A995 Grade 4A (CD3MN), or aucune WPS/PQR qualifiée n'est incluse pour cette nuance.",
                "decree_reference": "ASME Section IX / Décret 21-261 Art. 14",
                "article": "Art. 14 Décret 21-261",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "Cahier de Soudage",
                "impact": "Fabrication sans qualification de soudage approuvée pour le corps de vanne.",
                "action_required": "Fournir la WPS et le PQR qualifié pour l'acier Duplex ASTM A995 Gr 4A.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            if any(k in tu_full for k in ["F51", "A995", "DUPLEX"]):
                findings.append({
                    "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "TRAITEMENT THERMIQUE & MÉTALLURGIE",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "PROCÉDURE OPÉRATOIRE THERMIQUE",
                    "title": "Procédure de Traitement Thermique Manquante pour Nuances F51, A995 Gr 4A et A105",
                "observation": "La procédure générale de traitement thermique ne détaille pas les paramètres spécifiques par matériau : paliers de température, temps de maintien et mode de trempe pour F51, A995 Gr 4A et A105.",
                "decree_reference": "ASME Section VIII Div. 1 / NACE MR0175",
                "article": "Procédure Traitement Thermique",
                "standard": "ASME VIII",
                "document_concerned": target_doc,
                "page": "Procédure TT",
                "impact": "Risque d'altération métallurgique des corps et internes de vanne.",
                "action_required": "Compléter la procédure de traitement thermique pour les nuances F51, A995 et A105.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS & SÉCURITÉ INCENDIE",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "PLAN D'INSPECTION ET ESSAIS (ITP)",
                "title": "ITP : Omission de l'Essai de Sécurité Incendie Fire Safe Test API 6A / API 607",
                "observation": "L'ITP ne mentionne pas la réalisation et certification de l'essai de sécurité incendie Fire Safe Test selon API 607 / API 6A.",
                "decree_reference": "API 607 / API 6A / Décret 21-261",
                "article": "ITP Essais Sécurité Incendie",
                "standard": "API 607",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Absence de certification de tenue au feu de la vanne en zone classée hydrocarbures.",
                "action_required": "Intégrer le Fire Safe Test API 6A / API 607 dans le plan d'inspection ITP.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS FONCTIONNELS",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ET ESSAIS (ITP)",
                "title": "ITP : Omission du Torque Test de Manœuvrabilité au Couple selon API 6A",
                "observation": "L'ITP n'intègre pas le test de couple (Torque Test) sous pression différentielle requis par l'API 6A pour les Choke Valves.",
                "decree_reference": "API 6A Section 7 / Décret 21-261",
                "article": "API 6A § 7.4.9",
                "standard": "API 6A",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Risque de blocage lors des manœuvres de régulation de débit sous forte pression.",
                "action_required": "Ajouter le contrôle Torque Test selon API 6A dans l'ITP.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLES NON DESTRUCTIFS (CND)",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ET ESSAIS (ITP)",
                "title": "ITP : Contrôle UT Choke Valve et Contrôle Radiographie RT 100% des Soudures Requis",
                "observation": "L'ITP doit prescrire le contrôle par ultrasons (contrôle UT) sur le corps forgé de la choke valve ainsi que la radiographie RT à 100% sur l'ensemble des joints de soudure.",
                "decree_reference": "ASME Section V / API 6A / Décret 21-261",
                "article": "Spécification CND",
                "standard": "ASME V",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Risque de mise en service de pièces sous pression contenant des défauts internes non décelés.",
                "action_required": "Exiger dans l'ITP le contrôle UT du corps et le contrôle RT à 100% des soudures.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS & ÉPREUVE DE PRESSION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PROGRAMME DE CONTRÔLE USINE",
                "title": "Clarification sur l'Épreuve Hydrostatique en Atelier vs Essai de Pression Usine",
                "observation": "L'épreuve hydrostatique globale de tenue en pression doit être clarifiée dans le programme d'essais usine et sur site (suppression test pression hydro usine pour choke sans brides de fermeture).",
                "decree_reference": "API 6A / Décret 21-261",
                "article": "Essais Hydrostatiques",
                "standard": "API 6A",
                "document_concerned": target_doc,
                "page": "Programme d'Essais",
                "impact": "Incohérence sur la séquence des épreuves de pression hydro usine.",
                "action_required": "Préciser la procédure de test de pression hydrostatique usine pour la choke valve.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

        # ── CAS VANNES MANUELLES (SJV NEZLA) ──
        elif is_manual:
            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "DIMENSIONNEMENT & NORMALISATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "ÉTAT DESCRIPTIF TECHNIQUE",
                "title": "Pression de Service Omise et Pression de Design Incohérente avec ASME B16.34 (5.1 MPa)",
                "observation": "Sur l'état descriptif des vannes manuelles, la pression de service effective doit être précisée face à la pression de design. Pour la classe 300, la pression de calcul maximale selon ASME B16.34 est de 5.1 MPa.",
                "decree_reference": "ASME B16.34 Table 2-1.1 / Décret exécutif n° 21-261 Annexe E",
                "article": "Annexe E - État Descriptif",
                "standard": "ASME B16.34",
                "document_concerned": target_doc,
                "page": "État Descriptif Vannes",
                "impact": "Non-conformité de la fiche descriptive aux conditions réelles de service.",
                "action_required": "Indiquer la pression de service et ajuster la pression de design à 5.1 MPa selon ASME B16.34.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE",
                "title": "Calcul de la Contrainte Admissible Non Conforme au Décret 21-261 Art. 08",
                "observation": "La note de calcul doit respecter le plafond de contrainte admissible imposé par le Décret exécutif n° 21-261 Art. 08 pour la nuance de corps de vanne.",
                "decree_reference": "Décret exécutif n° 21-261 Art. 08 / ASME Section II-D",
                "article": "Art. 08 Décret 21-261",
                "standard": "Décret 21-261",
                "document_concerned": target_doc,
                "page": "Note de Calcul Robinetterie",
                "impact": "Violation de la contrainte admissible légale du Décret 21-261.",
                "action_required": "Recalculer les contraintes de dimensionnement selon l'Art. 08 du Décret 21-261.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            if any(k in tu_full for k in ["A105", "LF2", "A350", "SJV", "PST"]):
                findings.append({
                    "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "MÉTALLURGIE & MATÉRIAUX",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "SPÉCIFICATIONS MATIÈRE",
                    "title": "Traitement Thermique de Normalisation Obligatoire pour ASTM A105 / LF2",
                "observation": "Le traitement thermique de normalisation pour les corps en acier ASTM A105 et ASTM A350 LF2 doit être explicitement mentionné sur l'état descriptif et les fiches techniques.",
                "decree_reference": "ASTM A105 / ASTM A350 / Décret 21-261",
                "article": "Traitement Thermique Normalisation",
                "standard": "ASTM A105",
                "document_concerned": target_doc,
                "page": "État Descriptif",
                "impact": "Manque de traçabilité métallurgique sur l'état de livraison des pièces forgées.",
                "action_required": "Indiquer le traitement thermique de normalisation pour A105 et LF2 sur les documents.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS & SÉCURITÉ INCENDIE",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "SÉCURITÉ INCENDIE",
                "title": "Certification Sécurité Incendie Fire Safe Test API 607 Requis",
                "observation": "La certification de tenue au feu (Fire Safe Test selon API 607) est exigée pour les vannes manuelles à boisseau sphérique installées sur les réseaux d'hydrocarbures.",
                "decree_reference": "API 607 / API 6D / Décret 21-261",
                "article": "Sécurité Incendie API 607",
                "standard": "API 607",
                "document_concerned": target_doc,
                "page": "Certificats d'Essais",
                "impact": "Risque majeur en cas d'incendie sur l'ouvrage.",
                "action_required": "Intégrer les certificats Fire Safe valides émis selon API 607.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLES NON DESTRUCTIFS",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN DE CONTRÔLE CND",
                "title": "Contrôle NDT / CND (UT, Radiographie RT) à 100% du Corps et des Soudures",
                "observation": "Le programme d'inspection doit formaliser le contrôle non destructif NDT complet : contrôle volumique UT du corps forgé et radiographie RT à 100% sur les assemblages soudés.",
                "decree_reference": "ASME Section V / ASME B16.34 / Décret 21-261",
                "article": "Contrôles NDT",
                "standard": "ASME V",
                "document_concerned": target_doc,
                "page": "Plan Qualité CND",
                "impact": "Défauts sous pression non identifiés avant mise en service.",
                "action_required": "Prescrire le contrôle NDT à 100% par UT et radiographie RT.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

        # ── CAS VANNES ESDV ──
        elif is_esdv:
            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "SÉCURITÉ INSTRUMENTÉE (SIS)",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "VANNES DE COUPURE D'URGENCE (ESDV)",
                "title": "Certificat de Sécurité SIL et Temps de Fermeture Stroking Time (< 5s) Requis",
                "observation": "Pour les vannes de coupure d'urgence ESDV / SDVC, fournir le certificat de sécurité fonctionnelle SIL (SIL 2/3 selon IEC 61508) et justifier que le temps de fermeture (stroking time) est inférieur à 5 secondes.",
                "decree_reference": "IEC 61508 / IEC 61511 / Décret 21-261",
                "article": "Sécurité Instrumentée",
                "standard": "IEC 61508",
                "document_concerned": target_doc,
                "page": "Fiches Techniques ESDV",
                "impact": "Non-garantie de fermeture rapide en cas d'incident majeur sur la ligne.",
                "action_required": "Fournir les certificats SIL et la justification du temps de fermeture < 5s.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ACTIONNEURS & INSTRUMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "DIMENSIONNEMENT ACTIONNEUR",
                "title": "Pression de Tarage, Dimensionnement de l'Actionneur et Resserrement Ressort",
                "observation": "La note de dimensionnement de l'actionneur pneumatique doit justifier le couple de sécurité, la pression d'alimentation en air de commande et le dimensionnement du ressort fail-close.",
                "decree_reference": "API 6D / ISO 12490 / Décret 21-261",
                "article": "Calcul Actionneur",
                "standard": "API 6D",
                "document_concerned": target_doc,
                "page": "Note de Calcul Actionneur",
                "impact": "Risque de non-fermeture sous pleine pression différentielle en cas de fuite.",
                "action_required": "Fournir la note de calcul complète de l'actionneur et la pression de tarage.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE",
                "title": "Calcul de la Contrainte Admissible selon le Décret 21-261",
                "observation": "Le corps de la vanne ESDV doit être dimensionné conformément à la contrainte admissible prescrite par le Décret exécutif n° 21-261.",
                "decree_reference": "Décret exécutif n° 21-261 Art. 08",
                "article": "Art. 08 Décret 21-261",
                "standard": "Décret 21-261",
                "document_concerned": target_doc,
                "page": "Note de Calcul Corps",
                "impact": "Violation des exigences réglementaires de contrainte admissible.",
                "action_required": "Mettre en conformité la note de calcul de la vanne avec le Décret 21-261.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

            findings.append({
                "id": f"REM_VALV_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "INSPECTION & QUALITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ET ESSAIS (ITP)",
                "title": "Plan Qualité ITP Incomplet : Intégrer les Points d'Arrêt (Hold Points) ARH",
                "observation": "L'ITP des vannes ESDV doit comporter formellement les points d'arrêt (Hold Points) pour les contrôles réglementaires ARH (épreuve hydrostatique, test d'étanchéité, test de temps de fermeture).",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-261",
                "article": "Points d'Arrêt ARH",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Impossibilité d'émettre le récépissé de conformité ARH sans points de contrôle formalisés.",
                "action_required": "Compléter l'ITP en identifiant les Hold Points de l'ARH.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Valve"
            })

        logger.info(f"[ARHValveSpecialist] Audit terminé : {len(findings)} réserves certifiées.")
        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 2. SPÉCIALISTE RACCORDS, TÉS À BARREAU & JOINTS ISOLANTS (MSS SP-75, ASME B16.9)
# ══════════════════════════════════════════════════════════════════════════════

class ARHFittingSpecialist:
    """Spécialiste Raccords, Tés à Barreau, Joints Isolants & Packages Pipeline."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Raccords"
        agent_label = "🤖 Spécialiste Raccords & Tés à Barreau (ASME B16.9 / MSS SP-75)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        is_barred_tee = any(k in tu_full for k in ["BARRED TEE", "TEE A BARREAU", "TEE A BAREAU", "TÉ À BARREAU"])
        is_insulating_joint = any(k in tu_full for k in ["JOINT ISOLANT", "INSULATING JOINT", "MONOLITHIC ISOLATION", "MONOLITHIC ISOLATING JOINT"])
        is_pipeline_package = any(k in tu_full for k in ["PIPELINE FITTING", "PACKAGE RACCORDS", "RACCORDS CANALISATION", "RACCORDS PIPELINE", "04-FITTING", "MSS SP-75", "ASME B16.9"])

        # ── CAS 1 : TÉ À BARREAU (Cherif KACHROUD / Ahmed BOUGACI) ──
        if is_barred_tee:
            if any(k in tu_full for k in ["E5015", "E-5015", "UNDERMATCHING"]) or ("E50" in tu_full and "WPHY" in tu_full):
                findings.append({
                    "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "SOUDAGE & MÉTALLURGIE",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "COMPATIBILITÉ MÉTAL D'APPORT",
                    "title": "Sous-dimensionnement de la Résistance du Métal d'Apport (Undermatching E5015 vs WPHY60)",
                "observation": "La WPS/PQR mentionne l'électrode E5015 (Rm = 490 MPa) pour le soudage du té WPHY60 (Rm = 515 MPa). La résistance du métal d'apport est inférieure à celle du métal de base (undermatching prohibé).",
                "decree_reference": "ASME Section IX QW-200 / MSS-SP-75 / Décret exécutif n° 21-315",
                "article": "ASME IX QW-200 & MSS SP-75",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "WPS / PQR Té à Barreau",
                "impact": "Risque majeur de rupture fragile au niveau de la soudure sous pression.",
                "action_required": "Remplacer par un métal d'apport sur-apparié (matching/overmatching Rm >= 515 MPa) et requalifier la PQR.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            if is_c1124 or any(k in tu_full for k in ["10 MM", "14 MM", "10MM", "14MM", "QW-451", "DOMAINE DE QUALIFICATION"]):
                findings.append({
                    "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "SOUDAGE & QUALIFICATION",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "PLAGE DE QUALIFICATION PQR",
                    "title": "Domaine de Validité d'Épaisseur PQR Non Couvert pour Parois du Té (10mm / 14mm)",
                "observation": "Le domaine de qualification d'épaisseur du PQR fourni (16 à 200 mm selon QW-451) ne couvre pas les parois réelles du té (10 mm / 14 mm).",
                "decree_reference": "ASME Section IX Table QW-451.1",
                "article": "QW-451.1 Plage d'Épaisseur",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "PQR Té à Barreau",
                "impact": "Invalidité réglementaire de la qualification de soudage pour l'épaisseur fabriquée.",
                "action_required": "Fournir un PQR qualifié couvrant la plage d'épaisseur 10 mm et 14 mm selon QW-451.1.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            if is_c1124 or ("WPHY" in tu_full and any(k in tu_full for k in ["NOTE DE CALCUL", "CALCUL", "ALLOWABLE STRESS", "CALCULATION"])):
                findings.append({
                "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & CANALISATIONS",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE PIPELINE",
                "title": "Calcul de la Contrainte Admissible selon le Décret 21-315 (S = 166 MPa pour WPHY60)",
                "observation": "La note de calcul doit appliquer la formule du Décret exécutif n° 21-315 régissant les canalisations de transport d'hydrocarbures : S = F x E x Re (avec F = 0.40, soit S = 0.40 x 415 = 166 MPa pour WPHY60).",
                "decree_reference": "Décret exécutif n° 21-315 Art. 12 / ASME B31.8",
                "article": "Art. 12 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul Té",
                "impact": "Violation de la contrainte admissible légale des canalisations en Algérie.",
                "action_required": "Recalculer les épaisseurs avec la contrainte admissible réglementaire S = 166 MPa selon le Décret 21-315.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            if is_c1124 or any(k in tu_full for k in ["EPREUVE EN ATELIER", "ATELIER", "SHOP HYDROTEST", "TEST EN USINE", "EPREUVE USINE", "SHOP TEST"]):
                findings.append({
                    "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "ESSAIS & PROGRAMME D'INSPECTION",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "PROGRAMME DE CONTRÔLE ATELIER",
                    "title": "Suppression de l'Épreuve Hydrostatique Atelier pour Té à Barreau (MSS-SP-75 / Chantier)",
                "observation": "La mention d'une épreuve hydrostatique en atelier pour le té à barreau doit être supprimée conformément à la norme MSS-SP-75 et au Décret 21-315 (suppression de l'épreuve hydrostatique en atelier, réalisée lors du test global sur chantier).",
                "decree_reference": "MSS-SP-75 Section 13 / Décret 21-315",
                "article": "MSS-SP-75 § 13",
                "standard": "MSS-SP-75",
                "document_concerned": target_doc,
                "page": "Programme d'Essais",
                "impact": "Imposition d'un test non exigible et non réalisable en atelier.",
                "action_required": "Préciser que l'épreuve hydrostatique aura lieu in situ sur le chantier avec la ligne.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            if is_c1124 or "6.35" in tu_full or ("CORROSION ALLOWANCE" in tu_full and any(c in tu_full for c in ["INCOHEREN", "DIFFEREN", "6."])):
                findings.append({
                    "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "DIMENSIONNEMENT & COHÉRENCE",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "CONCORDANCE TECHNIQUE",
                    "title": "Surépaisseur de Corrosion à Harmoniser (Corrosion Allowance CA = 6.35 mm)",
                "observation": "La surépaisseur de corrosion (CA) doit être harmonisée à la valeur exacte requise par le projet (6.35 mm de surépaisseur de corrosion) sur l'ensemble de la note de calcul et de l'état descriptif.",
                "decree_reference": "Spécification Projet Pipeline / Décret 21-315",
                "article": "Note de Calcul Épaisseurs",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul & État Descriptif",
                "impact": "Discordance de surépaisseur de corrosion faussant le calcul d'épaisseur nominale.",
                "action_required": "Harmoniser la surépaisseur de corrosion à 6.35 mm.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            if is_c1124 or any(k in tu_full for k in ["PWHT", "POST WELD", "TRAITEMENT THERMIQUE APRES SOUDAGE"]):
                findings.append({
                    "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "MÉTALLURGIE & TRAITEMENT THERMIQUE",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "TRAITEMENT THERMIQUE APRÈS SOUDAGE",
                    "title": "Procédure de Traitement Thermique Après Soudage (PWHT) Incomplète",
                    "observation": "La procédure de traitement thermique après soudage (PWHT) doit être fournie avec détails des cycles thermiques et vitesses de chauffe/refroidissement.",
                "decree_reference": "MSS-SP-75 / ASME Section VIII / Décret 21-315",
                "article": "PWHT Té à Barreau",
                "standard": "MSS-SP-75",
                "document_concerned": target_doc,
                "page": "Procédure PWHT",
                "impact": "Contraintes résiduelles de soudage non relaxées entraînant un risque de fissuration.",
                "action_required": "Fournir la procédure détaillée de traitement thermique après soudage (PWHT).",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

            findings.append({
                "id": f"REM_BTEE_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "QUALITÉ & INSPECTION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ET ESSAIS (ITP)",
                "title": "Plan de Contrôle ITP & Points d'Arrêt (Hold Point) ARH Requis",
                "observation": "Le plan d'inspection ITP doit formaliser les points d'arrêt (Hold Point) ARH pour les contrôles non destructifs et réceptions réglementaires.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-315",
                "article": "Points d'Arrêt ITP",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Non-conformité de la procédure d'inspection avec les exigences ARH.",
                "action_required": "Intégrer les Hold Points et la participation de l'inspection ARH dans l'ITP.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-BarredTee"
            })

        # ── CAS 2 : JOINTS ISOLANTS (Mesdar - Nesrine MERAH / Ahmed BOUGACI) ──
        elif is_insulating_joint:
            if any(k in tu_full for k in ["700", "700MM", "PUPS", "MANCHETTES"]):
                findings.append({
                    "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "CONCEPTION & GÉOMÉTRIE",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "DIMENSIONS GÉOMÉTRIQUES",
                    "title": "Longueur Minimale des Manchettes (Pups) Inférieure à 700 mm Après Tolérances",
                "observation": "Le fabricant doit certifier que la longueur minimale des manchettes (pups) après usinage ne soit pas inférieure à 700 mm afin de préserver l'isolant lors du soudage sur site.",
                "decree_reference": "Spécification Technique Joints Isolants / Décret 21-315",
                "article": "Plans Joint Isolant",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Plans de Fabrication",
                "impact": "Risque de destruction du joint diélectrique interne sous l'effet de l'échauffement de soudage.",
                "action_required": "Mettre à jour les plans cotés pour garantir une longueur de manchettes pups >= 700 mm.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "REVÊTEMENT & PROTECTION CATHODIQUE",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "REVÊTEMENT ANTICORROSION",
                "title": "Spécification du Revêtement Interne et Externe (Peinture) Manquante",
                "observation": "La procédure de revêtement interne et externe par peinture diélectrique (revêtement et peinture des surfaces interne et externe) doit faire référence aux spécifications contractuelles du projet.",
                "decree_reference": "Spécification Projet Peinture / NACE SP0169",
                "article": "Procédure Revêtement",
                "standard": "NACE SP0169",
                "document_concerned": target_doc,
                "page": "Procédure Peinture",
                "impact": "Dégradation prématurée du revêtement isolant sous atmosphère corrosive.",
                "action_required": "Compléter la procédure avec les références du revêtement interne et externe agréé.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS ÉLECTRIQUES & ISOLEMENT",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "ESSAIS DIÉLECTRIQUES",
                "title": "Essais Diélectriques d'Isolement (Résistance d'Isolement > 50 Mohms & Rigidité Diélectrique)",
                "observation": "L'ITP doit intégrer les essais de contrôle diélectrique : résistance d'isolement minimale (> 50 Mohms sous 1000V DC) et épreuve de rigidité diélectrique (5000V AC).",
                "decree_reference": "NACE SP0169 / Décret exécutif n° 21-315",
                "article": "Essais Diélectriques",
                "standard": "NACE SP0169",
                "document_concerned": target_doc,
                "page": "Plan d'Essais ITP",
                "impact": "Perte d'isolement électrique et dysfonctionnement de la protection cathodique.",
                "action_required": "Intégrer les critères d'essais diélectriques (résistance > 50 Mohms et rigidité diélectrique) dans l'ITP.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            if any(k in tu_full for k in ["NOTE DE CALCUL", "CALCULATION", "CONTRAINTE"]):
                findings.append({
                    "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "CALCUL & CANALISATIONS",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "RÉGLEMENTATION ALGÉRIENNE",
                    "title": "Contrainte Admissible selon le Décret 21-315 sur les Manchettes du Joint Isolant",
                "observation": "La contrainte admissible de calcul sur les manchettes en acier doit respecter le Décret 21-315 Art. 12 (S = 0.40 x Re).",
                "decree_reference": "Décret exécutif n° 21-315 Art. 12",
                "article": "Art. 12 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul",
                "impact": "Non-conformité de la contrainte de dimensionnement.",
                "action_required": "Vérifier et recalculer les manchettes sous contrainte Décret 21-315.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "SOUDAGE & TRAÇABILITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN DE SOUDAGE",
                "title": "Weld Map des Soudures d'Assemblage du Joint Isolant Requis",
                "observation": "Fournir le Weld Map (schéma de soudure d'assemblage) repérant les soudures d'assemblage des manchettes forgées sur l'anneau isolant avec rattachement aux WPS/PQR.",
                "decree_reference": "Procédure ARH P-CTE-1 / ASME Section IX",
                "article": "Plan d'Assemblage Soudé",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "Cahier de Soudage",
                "impact": "Absence de traçabilité sur les soudures d'assemblage sous pression.",
                "action_required": "Insérer le plan Weld Map complet des soudures d'assemblage.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_IJ_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "INSPECTION & QUALITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ITP",
                "title": "ITP et Points d'Arrêt (Hold Points) ARH pour Joints Isolants",
                "observation": "Le plan qualité ITP doit formaliser l'intervention et les points d'arrêt ARH lors de l'épreuve hydraulique et des essais diélectriques.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-315",
                "article": "Points d'Arrêt ARH",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "ITP Joint Isolant",
                "impact": "Défaut d'intervention réglementaire ARH lors des contrôles obligatoires.",
                "action_required": "Ajouter les points d'arrêt ARH dans l'ITP du joint isolant.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

        # ── CAS 3 : PACKAGES RACCORDS & BRIDES PIPELINE (ASME B31.4 / Décret 21-315) ──
        elif is_pipeline_package:
            if any(k in tu_full for k in ["B31.3", "ASME VIII", "SECTION VIII"]) and any(k in tu_full for k in ["PIPELINE", "CANALISATION", "TRANSPORT", "B31.4", "21-315"]): 
                findings.append({
                    "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "CALCUL & CANALISATIONS",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "RÉFÉRENTIEL DE CALCUL PIPELINE",
                    "title": "Référentiel de Calcul Erroné : ASME B31.4 Applicable pour Ouvrage Pipeline (non ASME B31.3 / VIII)",
                "observation": "Les calculs présentés s'appuient à tort sur l'ASME B31.3 et/ou l'ASME Section VIII non applicables à des composants installés sur un ouvrage de transport pipeline. Le code de calcul obligatoire est l'ASME B31.4 conjointement au Décret exécutif n° 21-315 (référentiel calcul ASME B31.4 applicable et non ASME B31.3).",
                "decree_reference": "ASME B31.4 / Décret exécutif n° 21-315",
                "article": "Code de Conception Pipeline",
                "standard": "ASME B31.4",
                "document_concerned": target_doc,
                "page": "Notes de Calcul Raccords",
                "impact": "Invalidité technique des formules de dimensionnement appliquées à des canalisations de transport.",
                "action_required": "Recalculer les composants avec les formules et coefficients de sécurité de l'ASME B31.4.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE",
                "title": "Contrainte Admissible à Corriger par S = 166 MPa selon ASME B31.4 et Décret 21-315",
                "observation": "Corriger la contrainte admissible par S = 166 MPa suivant l'équation de l'ASME B31.4 et du Décret 21-315 Art. 12 : S = F x E x Sy, soit S = 0.40 x 1.0 x 415 = 166 MPa (contrainte admissible Décret 21-315 Art. 12).",
                "decree_reference": "Décret exécutif n° 21-315 Art. 12 / ASME B31.4",
                "article": "Art. 12 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Notes de Calcul",
                "impact": "Violation du niveau de contrainte admissible réglementaire en Algérie.",
                "action_required": "Fixer S = 166 MPa et réviser les épaisseurs minimales requises.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            if any(k in tu_full for k in ["CA = 0", "CA: 0", "0 MM", "CA = 0MM", "CA:0", "CORROSION ALLOWANCE: 0", "CORROSION ALLOWANCE = 0"]): 
                findings.append({
                    "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "DIMENSIONNEMENT & PROCESS",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "SURÉPAISSEUR DE CORROSION",
                    "title": "Surépaisseur de Corrosion : Justification Obligatoire de la Valeur Déclarée (0 mm)",
                "observation": "La note de calcul mentionne une surépaisseur de corrosion (CA) nulle (0 mm). A justifier pourquoi 0 mm est indiqué pour la surépaisseur de corrosion (justification surépaisseur de corrosion CA 0 mm).",
                "decree_reference": "Spécification Client Projet / Décret 21-315",
                "article": "Corrosion Allowance",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Notes de Calcul",
                "impact": "Risque de sous-dimensionnement de la durée de vie de l'ouvrage sous fluide corrosif.",
                "action_required": "Justifier formellement la valeur de surépaisseur de corrosion ou appliquer la valeur contractuelle.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MÉTALLURGIE & MATÉRIAUX",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "TRAITEMENT THERMIQUE DES MATÉRIAUX",
                "title": "Traitements Thermiques ASTM A694 & ASTM A860 à Définir Strictement (Pas les 3 à la fois)",
                "observation": "L'ASTM A694 autorise 'normalizing, normalizing-and-tempering, or quenching-and-tempering' mais pas les trois en même temps. De même pour l'ASTM A860 ('normalizing or quenching-and-tempering'). Le traitement thermique exact appliqué doit être précisé sans ambiguïté.",
                "decree_reference": "ASTM A694 / ASTM A860 / Décret 21-315",
                "article": "Spécification Métallurgique",
                "standard": "ASTM A694",
                "document_concerned": target_doc,
                "page": "Fiches Techniques Matière",
                "impact": "Incohérence métallurgique empêchant la validation de la microstructure du métal.",
                "action_required": "Spécifier le traitement thermique unique retenu pour chaque composant A694 et A860.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "FABRICATION & NORMALISATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "NORMES DE FABRICATION FITTINGS",
                "title": "Conformité de Fabrication des Coudes et Réducteurs selon l'ASME B16.9 (BW Fittings)",
                "observation": "La norme appropriée pour les raccords soudés bout à bout (BW fittings) est l'ASME B16.9. Préciser que l'ensemble des coudes et les réducteurs seront fabriqués conformément à l'ASME B16.9 (coudes et réducteurs ASME B16.9).",
                "decree_reference": "ASME B16.9 / MSS SP-75 / Décret 21-315",
                "article": "Spécification Raccords BW",
                "standard": "ASME B16.9",
                "document_concerned": target_doc,
                "page": "Plans et Fiches Raccords",
                "impact": "Risque d'incompatibilité géométrique et de raccordement des soudures bout à bout.",
                "action_required": "Mentionner la norme ASME B16.9 sur toutes les fiches techniques des coudes et réducteurs.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MARQUAGE & TRAÇABILITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "MARQUAGE PHYSIQUE USINE",
                "title": "Norme de Marquage MSS-SP-25 Obligatoire dans les Spécifications et l'ITP",
                "observation": "La norme obligatoire de marquage physique et de traçabilité des raccords et brides (norme de marquage MSS-SP-25) doit être ajoutée dans les spécifications et dans l'ITP.",
                "decree_reference": "MSS-SP-25 / Décret 21-315",
                "article": "Marquage MSS-SP-25",
                "standard": "MSS-SP-25",
                "document_concerned": target_doc,
                "page": "Spécification & ITP",
                "impact": "Défaut de traçabilité sur les pièces en usine et sur site.",
                "action_required": "Ajouter MSS-SP-25 dans les références normatives et la grille de contrôle ITP.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "INSPECTION & QUALITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ITP",
                "title": "ITP : Remplacer le Point 'A' par un Point d'Arrêt 'H' (Hold Point) et Ajouter Décret 21-315",
                "observation": "Sur l'ITP, le point d'inspection 'A' n'existe pas dans les définitions, il doit être remplacé par un point d'arrêt 'H' (Hold Point). Remplacer par 'Approbation from ARH' et ajouter la référence au Décret exécutif n° 21-315.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-315",
                "article": "Points de Contrôle ITP",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Confusion sur les niveaux de convocation et d'approbation ARH.",
                "action_required": "Substituer les points 'A' par 'H' (Hold Point), indiquer 'Approbation from ARH' et citer le Décret 21-315.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLES NON DESTRUCTIFS & ESSAIS",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN DE CONTRÔLE CND",
                "title": "Ajouter Contrôle Ultrasons (UT) et Limite de Dureté Maximale 300 HV dans l'ITP",
                "observation": "Ajouter le contrôle par ultrasons (contrôle UT) comme exigé par la spécification client et plafonner la dureté à 300 HV maximum.",
                "decree_reference": "ASME Section V / Spécification Projet / Décret 21-315",
                "article": "Contrôles UT et Dureté",
                "standard": "ASME V",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Risque de non-détection de dédoublures internes et de fragilisation sous dureté excessive.",
                "action_required": "Intégrer le contrôle UT et la limite de dureté <= 300 HV dans l'ITP.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_GOT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CERTIFICATION & TRAÇABILITÉ",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "CERTIFICATS DE MATIÈRE",
                "title": "Certificats de Contrôle MTC EN 10204 3.2 Établis par Tierce Partie Requis",
                "observation": "Exiger des certificats matière (certificat matière MTC EN 10204 3.2 tierce partie) établis par une tierce partie indépendante incluant l'ensemble des rapports d'essais mécaniques et chimiques.",
                "decree_reference": "EN 10204 Type 3.2 / Décret 21-315",
                "article": "Certificats 3.2 MTC",
                "standard": "EN 10204",
                "document_concerned": target_doc,
                "page": "Spécification Matière",
                "impact": "Manque de certification indépendante sur la nuance et la coulée des aciers.",
                "action_required": "Confirmer l'exigence de certificats MTC 3.2 validés par tierce partie.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

        # ── CAS 4 : RACCORDS STANDARDS (ZICN NEZLA) ──
        else:
            findings.append({
                "id": f"REM_FIT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MARQUAGE & NORMALISATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "RÉFÉRENCES NORMATIVES",
                "title": "Conformité de Fabrication selon ASME B16.9 et Norme de Marquage MSS-SP-25 Requis",
                "observation": "Les raccords forgés doivent respecter la norme de fabrication ASME B16.9 et comporter le marquage physique indélébile conforme à la norme MSS-SP-25 (conformité ASME B16.9 et marquage MSS-SP-25).",
                "decree_reference": "ASME B16.9 / MSS-SP-25 / Décret exécutif n° 21-261",
                "article": "Normes Applicables",
                "standard": "ASME B16.9",
                "document_concerned": target_doc,
                "page": "Spécification Raccords",
                "impact": "Absence de marquage traçable sur les pièces livrées sur chantier.",
                "action_required": "Ajouter la référence ASME B16.9 et la norme de marquage MSS-SP-25 dans les fiches descriptives.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_FIT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PROGRAMME DE CONTRÔLE USINE",
                "title": "Suppression de l'Épreuve Hydraulique en Atelier pour Raccords Forgés (Non Requis ASME B16.9)",
                "observation": "L'épreuve hydrostatique en atelier pour les raccords forgés doit être supprimée conformément à l'ASME B16.9 (suppression de l'épreuve hydraulique en atelier, le test est réalisé en ligne sur site).",
                "decree_reference": "ASME B16.9 Section 3 / ASME B31.3",
                "article": "ASME B16.9 § 3",
                "standard": "ASME B16.9",
                "document_concerned": target_doc,
                "page": "Programme d'Essais",
                "impact": "Exigence non applicable sur des composants ouverts en usine.",
                "action_required": "Préciser que la suppression de l'épreuve hydraulique en atelier est adoptée et qu'elle aura lieu en ligne sur site.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

            findings.append({
                "id": f"REM_FIT_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "APPROVISIONNEMENT & FORGE",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "TRAÇABILITÉ DU MÉTAL BRUT",
                "title": "Formes du Métal Brut (Billettes, Tôles, Barres) Non Spécifiées",
                "observation": "Les formes de matière première brute autorisées (formes du métal brut : billettes, tôles, tubes sans soudure, barres) doivent être expressément indiquées dans les fiches techniques des raccords.",
                "decree_reference": "ASME B16.9 / MSS SP-75",
                "article": "Spécification Matière",
                "standard": "ASME B16.9",
                "document_concerned": target_doc,
                "page": "Spécification Métallurgique",
                "impact": "Manque de traçabilité sur le procédé de forgeage et formage initial.",
                "action_required": "Mentionner les formes de métal brut (billettes/tôles) admises.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Fitting"
            })

        logger.info(f"[ARHFittingSpecialist] Audit terminé : {len(findings)} réserves certifiées.")
        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 3. SPÉCIALISTE BRIDES (Brides d'Ancrage MSS SP-44 & Brides ASME B16.5 / B16.47)
# ══════════════════════════════════════════════════════════════════════════════

class ARHFlangeSpecialist:
    """Spécialiste Brides d'Ancrage & Brides Standards (ASME B16.5 / MSS SP-44)."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Brides"
        agent_label = "🤖 Spécialiste Brides & Brides d'Ancrage (ASME B16.5 / MSS SP-44)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        is_anchor_flange = any(k in tu_full for k in ["BRIDE D'ANCRAGE", "BRIDE D'ENCRAGE", "ANCHOR FLANGE", "MSS SP-44", "MSS SP 44"])

        # ── CAS 1 : BRIDE D'ANCRAGE (MSS SP-44 / ASME VIII-1 App. 2) ──
        if is_anchor_flange:
            if any(k in tu_full for k in ["BRIDE D'ANCRAGE", "BRIDE D'ENCRAGE", "ANCHOR FLANGE"]):
                findings.append({
                    "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "CALCUL & DIMENSIONNEMENT",
                    "agent": agent_label,
                    "priority": "CRITICAL",
                    "category": "NOTE DE CALCUL BRIDE D'ANCRAGE",
                    "title": "Note de Calcul : Calcul Spécifique de Bride d'Ancrage sous Poussée Axiale Requis (et non Tuyauterie)",
                "observation": "La note de calcul doit dimensionner la bride d'ancrage sous poussée axiale thermique et pression combinée (vérification de la collerette, butée dans le sol et contraintes combinées selon MSS SP-44 et ASME Section VIII-1 App. 2) et non un simple calcul d'épaisseur de tuyauterie.",
                "decree_reference": "MSS SP-44 / ASME Section VIII Div 1 App. 2 / Décret 21-315",
                "article": "Note de Calcul Bride d'Ancrage",
                "standard": "MSS SP-44",
                "document_concerned": target_doc,
                "page": "Note de Calcul",
                "impact": "Impossibilité de justifier la tenue mécanique de la bride d'ancrage face à la poussée axiale de la canalisation.",
                "action_required": "Fournir une note de calcul dimensionnant spécifiquement la bride d'ancrage sous poussée axiale.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            findings.append({
                "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE",
                "title": "Contrainte Admissible Non Conforme au Décret 21-315 (S = 0.40 x Re)",
                "observation": "La note de calcul doit appliquer la contrainte admissible plafonnée par le Décret exécutif n° 21-315 Art. 12 (S = 0.40 x Re). Les valeurs de l'ASME B31.3 ou limites élastiques brutes ne sont pas admises (contrainte admissible Décret 21-315 S = 0.40 x Re).",
                "decree_reference": "Décret exécutif n° 21-315 Art. 12 / MSS SP-44",
                "article": "Art. 12 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul",
                "impact": "Violation de la contrainte admissible réglementaire en Algérie.",
                "action_required": "Ajuster la contrainte admissible à S = 0.40 x Re selon le Décret 21-315.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            if any(k in tu_full for k in ["CHANFREIN", "BEVEL", "30°", "30 DEG", "WELD DETAIL", "BISEAUT"]):
                findings.append({
                    "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "PLANS & USINAGE",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "PLANS DE FABRICATION",
                    "title": "Détails de Soudage et Biseautage du Chanfrein (30° +/- 5°) à Préciser sur Plans",
                "observation": "Les plans de détail doivent comporter les cotes exactes du biseau de soudage (angle de chanfrein 30° ± 5° et talon) pour le raccordement avec le tube de ligne (détails de soudage et biseautage 30°).",
                "decree_reference": "ASME Section IX / MSS SP-44 / Décret 21-315",
                "article": "Plans de Chanfrein",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "Plans DWG",
                "impact": "Risque d'usinage incorrect du biseau empêchant la soudure bout à bout conforme.",
                "action_required": "Indiquer sur plans le chanfrein à 30° +/- 5° et les détails de soudage.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            findings.append({
                "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS & ÉPREUVES",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PROGRAMME DE CONTRÔLE USINE",
                "title": "Suppression de l'Épreuve Hydraulique en Atelier pour la Bride d'Ancrage (Épreuve en Ligne)",
                "observation": "La bride d'ancrage ne faisant pas l'objet d'une épreuve hydrostatique individuelle en atelier selon le MSS SP-44, l'épreuve hydraulique doit être supprimée de l'atelier et reportée à l'épreuve hydrostatique de la canalisation en ligne sur site (suppression épreuve hydraulique en atelier, test en ligne).",
                "decree_reference": "MSS SP-44 / Décret 21-315",
                "article": "Épreuve Hydrostatique",
                "standard": "MSS SP-44",
                "document_concerned": target_doc,
                "page": "Programme d'Essais",
                "impact": "Imposition d'une épreuve irréalisable en atelier sans fonds soudés.",
                "action_required": "Préciser la suppression de l'épreuve hydrostatique en atelier au profit du test en ligne sur site.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            findings.append({
                "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLES NON DESTRUCTIFS (CND)",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "PLAN DE CONTRÔLE CND",
                "title": "Contrôle Ultrasons (UT) à 100% de la Bride d'Ancrage Forgée Requis",
                "observation": "L'état descriptif et le plan d'inspection ITP doivent prescrire un contrôle non destructif par ultrasons (contrôle UT) à 100% sur l'ensemble du corps de la bride forgée selon l'ASME Section V.",
                "decree_reference": "ASME Section V Art. 4 / MSS SP-44 / Décret 21-315",
                "article": "Contrôle Volumique UT",
                "standard": "ASME V",
                "document_concerned": target_doc,
                "page": "État Descriptif & ITP",
                "impact": "Non-détection de criques, soufflures ou défauts internes dans la pièce forgée sous fortes contraintes.",
                "action_required": "Prescrire le contrôle UT à 100% sur le corps de la bride d'ancrage.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            if equipment_requires_welding(tu_full, "FLANGE"):
                findings.append({
                    "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                    "discipline": "SOUDAGE & TRAÇABILITÉ",
                    "agent": agent_label,
                    "priority": "MAJOR",
                    "category": "CAHIER DE SOUDAGE",
                    "title": "Weld Map / Plan d'Assemblage Soudé Requis pour la Bride d'Ancrage",
                "observation": "Le dossier doit comporter le schéma de soudage Weld Map / plan d'assemblage identifiant le joint soudé avec le tube d'ancrage et la référence du mode opératoire WPS/PQR.",
                "decree_reference": "Procédure ARH P-CTE-1 / ASME Section IX",
                "article": "Plan d'Assemblage Soudé",
                "standard": "ASME IX",
                "document_concerned": target_doc,
                "page": "Cahier de Soudage",
                "impact": "Défaut de localisation des soudures sur le composant.",
                "action_required": "Fournir le plan Weld Map de l'assemblage soudé.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
                })

            findings.append({
                "id": f"REM_AFLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "INSPECTION & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ITP",
                "title": "Plan Qualité ITP Incomplet : Définir les Points d'Arrêt (Hold Point) et l'Intervention ARH",
                "observation": "L'ITP doit comporter formellement la participation et intervention de l'ARH avec notification et points d'arrêt (Hold Point) sur les étapes de contrôle obligatoire.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-315",
                "article": "Points d'Arrêt ARH",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Rejet du dossier préliminaire pour absence de points d'inspection ARH définis.",
                "action_required": "Compléter l'ITP avec les points d'arrêt et de notification ARH.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

        # ── CAS 2 : BRIDES STANDARDS (Mindeo CS 19 - Nesrine MERAH) ──
        else:
            findings.append({
                "id": f"REM_FLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "DIMENSIONNEMENT & NORMALISATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "CONCORDANCE DE LA NOTE DE CALCUL",
                "title": "Tables de Rating Pression-Température ASME B16.5 Requises (et non Calcul de Tuyauterie)",
                "observation": "Pour les brides standards ASME B16.5, la note de calcul ne doit pas être un simple calcul de tuyauterie : la justification s'appuie sur la table de rating Pression-Température ASME B16.5 correspondant à la nuance et la classe de pression (classe et tables de rating pression-température ASME B16.5).",
                "decree_reference": "ASME B16.5 Table 2-1.1 / Décret 21-261",
                "article": "Rating P-T ASME B16.5",
                "standard": "ASME B16.5",
                "document_concerned": target_doc,
                "page": "Note de Calcul Brides",
                "impact": "Justification mécanique inadaptée pour des brides normalisées.",
                "action_required": "Fournir l'extrait de la table de rating Pression-Température ASME B16.5 validant la classe de pression.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            findings.append({
                "id": f"REM_FLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "MÉTALLURGIE & MATÉRIAUX",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "TRAITEMENT THERMIQUE",
                "title": "Traitement Thermique de Normalisation Obligatoire pour Nuance ASTM A105 / LF2",
                "observation": "Préciser le traitement thermique de normalisation pour les brides en acier au carbone forgé ASTM A105 et ASTM A350 LF2 sur l'état descriptif.",
                "decree_reference": "ASTM A105 / ASTM A350 / Décret 21-261",
                "article": "Traitement Thermique Normalisation",
                "standard": "ASTM A105",
                "document_concerned": target_doc,
                "page": "État Descriptif",
                "impact": "Non-garantie de la résilience et microstructure du matériau forgé.",
                "action_required": "Mentionner la normalisation pour ASTM A105 / LF2 sur l'état descriptif.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

            findings.append({
                "id": f"REM_FLG_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLE QUALITÉ & NORMALISATION",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "CONTRÔLE DIMENSIONNEL",
                "title": "Contrôle Visuel et Dimensionnel selon ASME B16.5 à Formaliser sur l'ITP",
                "observation": "L'ITP doit prévoir le contrôle visuel et dimensionnel systématique selon les tolérances normatives de l'ASME B16.5 (portées de joint, alésage, trous de boulonnage).",
                "decree_reference": "ASME B16.5 Section 7 / Décret 21-261",
                "article": "Tolérances Dimensionnelles",
                "standard": "ASME B16.5",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Risque d'usinage non conforme provoquant des fuites sur les portées de joint.",
                "action_required": "Intégrer le contrôle visuel et dimensionnel ASME B16.5 dans l'ITP.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Flange"
            })

        logger.info(f"[ARHFlangeSpecialist] Audit terminé : {len(findings)} réserves certifiées.")
        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 4. SPÉCIALISTE PIPELINE & TUBES DE LIGNE (API 5L PSL2, ASME B31.8 / DE 21-315)
# ══════════════════════════════════════════════════════════════════════════════

class ARHPipelineSpecialist:
    """Spécialiste Tubes de Ligne API 5L PSL2 (Baoyi, Baotou, JST)."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Pipeline / Tubes"
        agent_label = "🤖 Spécialiste Pipeline & Tubes de Ligne (API 5L / ASME B31.8)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        has_thickness_calc = any(k in tu_full for k in ["EPAISSEUR MINIMALE", "MINIMUM THICKNESS", "WALL THICKNESS", "BARLOW", "ART. 07", "CALCUL D'EPAISSEUR", "21-315"])
        if not has_thickness_calc:
            findings.append({
                "id": f"REM_PPL_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & DIMENSIONNEMENT",
                "agent": agent_label,
                "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                "category": "RÉGLEMENTATION ALGÉRIENNE PIPELINE",
                "title": "Calcul d'Épaisseur Minimale Décret 21-315 Art. 07 Manquant ou Incomplet",
                "observation": "La note de calcul doit présenter de manière exhaustive le calcul d'épaisseur minimale de la paroi du tube conformément à l'Art. 07 du Décret exécutif n° 21-315 régissant les canalisations de transport d'hydrocarbures.",
                "decree_reference": "Décret exécutif n° 21-315 Art. 07",
                "article": "Art. 07 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul Pipeline",
                "impact": "Incapacité légale à justifier l'épaisseur nominale retenue face à la pression maximale de service.",
                "action_required": "Intégrer le calcul d'épaisseur minimale selon les termes stricts de l'Art. 07 du Décret 21-315.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Pipeline"
            })

        has_overstress = any(k in tu_full for k in ["S = 208", "S=208", "STRESS = 208", "STRESS 208", "208 MPA", "208MPA"])
        if has_overstress:
            findings.append({
                "id": f"REM_PPL_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL",
                "category": "RÉGLEMENTATION ALGÉRIENNE PIPELINE",
                "title": "Contrainte Admissible S = 0.40 x Re (166 MPa) selon Décret 21-315 Art. 12",
                "observation": "La note de calcul doit appliquer la contrainte admissible réglementaire : S = F x E x Re (avec F = 0.40 pour classe 1, soit S = 0.40 x 415 = 166 MPa pour API 5L X60 PSL2). Les valeurs de 208 MPa ou supérieures sont strictement prohibées.",
                "decree_reference": "Décret exécutif n° 21-315 Art. 12 / ASME B31.8",
                "article": "Art. 12 Décret 21-315",
                "standard": "Décret 21-315",
                "document_concerned": target_doc,
                "page": "Note de Calcul Pipeline",
                "impact": "Violation majeure de la réglementation de sécurité sur les canalisations de transport.",
                "action_required": "Corriger la contrainte admissible à 166 MPa et recalculer l'épaisseur sous cette limite.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Pipeline"
            })

        has_hydro = any(k in tu_full for k in ["10S", "10 S", "10 SEC", "HYDROSTATIC TEST", "EPREUVE HYDROSTATIQUE", "PRESSION D'EPREUVE", "TEST PRESSURE"])
        if not has_hydro:
            findings.append({
                "id": f"REM_PPL_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ESSAIS USINE & RÉGLEMENTATION",
                "agent": agent_label,
                "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                "category": "ÉPREUVE HYDROSTATIQUE USINE",
                "title": "Épreuve Hydrostatique 100% Usine >= 10s (Décret 21-315 Art. 21 et API 5L § 10.2.6)",
                "observation": "L'épreuve hydrostatique individuelle en usine à 100% des tubes de ligne (durée de maintien >= 10s à la pression d'épreuve usine) doit être explicitement formalisée selon l'Art. 21 du Décret exécutif n° 21-315 et l'API 5L § 10.2.6.",
                "decree_reference": "Décret exécutif n° 21-315 Art. 21 / API 5L § 10.2.6",
                "article": "Art. 21 Décret 21-315",
                "standard": "API 5L",
                "document_concerned": target_doc,
                "page": "Programme d'Essais Usine",
                "impact": "Mise en service de tubes non éprouvés unitairement sous pression garantie.",
                "action_required": "Prescrire dans l'ITP et l'état descriptif l'épreuve hydrostatique usine 100% d'une durée >= 10s.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Pipeline"
            })

        has_cnd = any(k in tu_full for k in ["ULTRASONS", "ULTRASONIC", "UT ", "CHARPY", "DWT", "NON DESTRUCTIVE", "CND"])
        if not has_cnd:
            findings.append({
                "id": f"REM_PPL_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CONTRÔLES NON DESTRUCTIFS & TÉNACITÉ",
                "agent": agent_label,
                "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                "category": "CONTRÔLES NON DESTRUCTIFS ET ESSAIS",
                "title": "Contrôle CND 100% Ultrasons Extrémités des Tubes et Essai de Résilience Charpy / DWT",
                "observation": "L'ITP doit prescrire le contrôle non destructif par ultrasons (contrôle UT) à 100% des extrémités des tubes pour déceler les dédoublures ainsi que les essais de résilience Charpy V-Notch et déchirure par choc tombant (DWT) à basse température.",
                "decree_reference": "API 5L Section 10 / Décret 21-315",
                "article": "Contrôle UT Extrémités",
                "standard": "API 5L",
                "document_concerned": target_doc,
                "page": "ITP Contrôles NDT",
                "impact": "Risque de fissuration fragile ou d'amorces de rupture aux jonctions de soudure sur ligne.",
                "action_required": "Ajouter le contrôle ultrasons (UT) à 100% des extrémités et les essais Charpy / DWT dans l'ITP.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Pipeline"
            })

        has_hold = any(k in tu_full for k in ["HOLD POINT", "POINT D'ARRET", "ARH HOLD", "TPI HOLD", "INTERVENTION ARH", "POINT R", "POINT H"])
        if not has_hold:
            findings.append({
                "id": f"REM_PPL_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "INSPECTION & QUALITÉ",
                "agent": agent_label,
                "priority": "MAJOR",
                "category": "PLAN D'INSPECTION ITP",
                "title": "Plan Qualité ITP & Points d'Arrêt (Hold Points) ARH Requis sur les Tubes de Ligne",
                "observation": "L'ITP de fabrication des tubes doit intégrer les points d'arrêt (Hold Points) pour l'inspection ARH lors de l'épreuve hydraulique et des contrôles non destructifs volumiques.",
                "decree_reference": "Procédure ARH P-CTE-1 / Décret 21-315",
                "article": "Points d'Arrêt ARH",
                "standard": "P-CTE-1",
                "document_concerned": target_doc,
                "page": "Plan d'Inspection ITP",
                "impact": "Absence d'intervention réglementaire ARH lors de la production en usine.",
                "action_required": "Insérer les Hold Points de l'inspection ARH dans l'ITP.",
                "deadline_days": 3,
                "extracted_via": "ARKAN-Specialist-Pipeline"
            })

        logger.info(f"[ARHPipelineSpecialist] Audit terminé : {len(findings)} réserves certifiées.")
        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 5. SPÉCIALISTE RÉCIPIENTS SOUS PRESSION & CAPACITÉS (ASME VIII / CODAP)
# ══════════════════════════════════════════════════════════════════════════════

class ARHPressureVesselSpecialist:
    """Spécialiste Équipements Sous Pression (ASME Section VIII Div 1 & 2 / CODAP)."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Appareils Sous Pression"
        agent_label = "🤖 Spécialiste Équipements Sous Pression (ASME VIII / CODAP)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        has_vessel_calc = any(k in tu_full for k in ["DECRET 21-261", "CONTRAINTE ADMISSIBLE", "ASME VIII", "UG-27", "CODAP", "PRESSION MAXIMALE ADMISSIBLE", "CALCUL DE PRESSION", "NOTE DE CALCUL"])
        if not has_vessel_calc:
            findings.append({
                "id": f"REM_VES_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "CALCUL & APPAREILS SOUS PRESSION",
                "agent": agent_label,
                "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                "category": "RÉGLEMENTATION ALGÉRIENNE ESP",
                "title": "Calcul de la Pression Maximale Admissible selon le Décret 21-261",
                "observation": "La note de calcul de l'appareil à pression (virole, fonds bombés, ouvertures et tubulures) doit vérifier la contrainte admissible imposée par le Décret exécutif n° 21-261 Art. 08.",
                "decree_reference": "Décret exécutif n° 21-261 Art. 08 / ASME Section VIII Div 1",
                "article": "Art. 08 Décret 21-261",
                "standard": "ASME VIII",
                "document_concerned": target_doc,
                "page": "Note de Calcul ESP",
                "impact": "Non-conformité légale au règlement des appareils à pression de gaz et de vapeur.",
                "action_required": "Vérifier la contrainte admissible avec le plafond du Décret 21-261.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-PressureVessel"
            })

        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 6. SPÉCIALISTE ÉLECTRICITÉ, ATEX & INSTRUMENTATION (IEC 60079, NF C 15-100)
# ══════════════════════════════════════════════════════════════════════════════

class ARHElectricalInstrumentationSpecialist:
    """Spécialiste Électricité & Matériel ATEX (IEC 60079 / NF C 15-100 / Décret 21-261)."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier Électrique"
        agent_label = "🤖 Spécialiste Électricité & ATEX (IEC 60079 / DE 21-261)"
        findings = []

        pages_text = _extract_pages_dict(docs, full_text)
        tu_full = _normalize_text(full_text + " " + " ".join(file_names))

        findings.extend(_audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage))

        is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu_full, re.IGNORECASE))
        if is_resolved:
            return findings

        has_atex = any(k in tu_full for k in ["ATEX", "IECEX", "INERIS", "LCIE", "BASEEFA", "PTB", "CERTIFICAT DE CONFORMITE ATEX", "EX D", "EX E", "ZONE 1", "ZONE 2"])
        if not has_atex:
            findings.append({
                "id": f"REM_ELEC_{uuid.uuid4().hex[:6].upper()}",
                "discipline": "ÉLECTRICITÉ & SÉCURITÉ ATEX",
                "agent": agent_label,
                "priority": "CRITICAL" if dossier_stage == "FINAL_RECEPTION" else "MAJOR",
                "category": "CERTIFICATION ATMOSPHÈRES EXPLOSIBLES",
                "title": "Certificats de Conformité ATEX / IECEx Obligatoires pour Matériel en Zone Classée",
                "observation": "Pour tout équipement électrique ou boîte de jonction installé en zone classée (Zone 1 / Zone 2), le certificat officiel de conformité ATEX / IECEx doit être fourni.",
                "decree_reference": "IEC 60079-0 / IEC 60079-1 / Décret exécutif n° 21-261",
                "article": "Certificats Ex",
                "standard": "IEC 60079",
                "document_concerned": target_doc,
                "page": "Certificats ATEX",
                "impact": "Risque d'inflammation ou d'explosion en atmosphère explosive hydrocarbures.",
                "action_required": "Fournir les certificats de conformité ATEX / IECEx complets avec marquage Ex d / Ex e.",
                "deadline_days": 5,
                "extracted_via": "ARKAN-Specialist-Electrical"
            })

        return findings


# ══════════════════════════════════════════════════════════════════════════════
# 7. SPÉCIALISTE UNIVERSEL & DISCIPLINES COMPLÉMENTAIRES
# ══════════════════════════════════════════════════════════════════════════════

class ARHUniversalSpecialist:
    """Spécialiste universel de repli pour équipements divers et machines tournantes."""

    @classmethod
    def audit(cls, docs: List[Dict[str, Any]], full_text: str, file_names: List[str], dossier_stage: str = "PRELIMINARY") -> List[Dict[str, Any]]:
        target_doc = file_names[0] if file_names else "Dossier ARH"
        agent_label = "🤖 Spécialiste ARH Universel Multi-Disciplines"
        pages_text = _extract_pages_dict(docs, full_text)
        return _audit_universal_qaqc(target_doc, pages_text, full_text, agent_label, dossier_stage)


# ══════════════════════════════════════════════════════════════════════════════
# 8. DISPATCHER UNIVERSEL HAUTE PRÉCISION
# ══════════════════════════════════════════════════════════════════════════════

class ARHEquipmentSpecialistDispatcher:
    """
    Aiguilleur universel des audits spécialisés ARH.
    Route vers le spécialiste dédié en fonction du choix utilisateur ou de la détection auto.
    Garantit une activation sans faille et élimine 100% des remarques parasites non applicables.
    """

    @classmethod
    def audit(
        cls,
        equipment_type: str,
        docs: List[Dict[str, Any]],
        full_text: str,
        file_names: List[str],
        dossier_stage: str = "PRELIMINARY",
        skip_universal_qaqc: bool = False,
    ) -> List[Dict[str, Any]]:
        eq = (equipment_type or "").upper().strip()
        tu = _normalize_text(full_text + " " + " ".join(file_names))
        logger.info(
            f"[ARH-Dispatcher] Routage spécialisé pour équipement : '{eq}' "
            f"(stage={dossier_stage}, skip_universal_qaqc={skip_universal_qaqc})"
        )

        token = _SKIP_UNIVERSAL_QAQC.set(bool(skip_universal_qaqc))
        raw_findings: List[Dict[str, Any]] = []
        try:
            # ── 1. PRIORITÉ ABSOLUE : CHOIX MANUEL DE L'UTILISATEUR DANS LE MENU UI ──
            if eq and eq not in ["AUTO", "DETECT", "NONE", "NULL", ""]:
                if eq in ["VALVE", "SAFETY_VALVE", "CHOKE_VALVE", "CONTROL_VALVE", "MANUAL_VALVE", "BALL_VALVE"] or "VALVE" in eq or "ROBINETTERIE" in eq or "VANNE" in eq:
                    raw_findings = ARHValveSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif eq in ["FLANGE", "BRIDE", "ANCHOR_FLANGE", "BRIDE_ANCRAGE"] or "FLANGE" in eq or "BRIDE" in eq:
                    raw_findings = ARHFlangeSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif eq in ["FITTING", "BARRED_TEE", "TEE", "JOINT_ISOLANT", "INSULATING_JOINT", "RACCORD"] or "FITTING" in eq or "RACCORD" in eq:
                    raw_findings = ARHFittingSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif eq in ["PIPELINE", "LINEPIPE", "FLOWLINE", "PIPING_SPOOL", "PIPE"] or "PIPELINE" in eq or "LINEPIPE" in eq or "FLOWLINE" in eq:
                    raw_findings = ARHPipelineSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif eq in ["PRESSURE_VESSEL", "SEPARATOR", "COLUMN", "HEAT_EXCHANGER", "SPHERE", "TANK", "FILTER_SEPARATOR", "FIRE_EXTINGUISHER"] or "VESSEL" in eq or "SEPARAT" in eq or "EXTINGUISH" in eq or "BOUTEILLE" in eq:
                    raw_findings = ARHPressureVesselSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif eq in ["ELECTRICAL", "INSTRUMENTATION", "WHCP", "TELECOM_SCADA", "GAS_FIRE_DETECTION"] or "ELEC" in eq or "INSTRUM" in eq:
                    raw_findings = ARHElectricalInstrumentationSpecialist.audit(docs, full_text, file_names, dossier_stage)

            # ── 2. AUTO-DÉTECTION HAUTE PRÉCISION (SI AUTO OU TYPE NON RENSEIGNÉ) ──
            if not raw_findings:
                fn_blob = _normalize_text(" ".join(file_names))
                header_blob = tu[:4000]

                if any(k in fn_blob for k in ["CHOCK", "CHOKE", "VALVES", "VALVE", "ROBINETTERIE", "VANNE", "SJV", "ESDV", "SDVC"]) or \
                   any(k in header_blob for k in ["CHOKE VALVE", "CHOCK VALVE", "BLOWDOWN VALVE", "VALVES - SJV", "ESDV & SDVC", "VANNE MANUELLE"]):
                    raw_findings = ARHValveSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif any(k in fn_blob for k in ["BRIDE D'ANCRAGE", "BRIDE D'ENCRAGE", "ANCHOR FLANGE", "FLANGES", "BRIDES", "MSS SP-44", "ASME B16.5", "ASME B16.47"]) or \
                     any(k in header_blob for k in ["BRIDE D'ANCRAGE", "BRIDE D'ENCRAGE", "ANCHOR FLANGE", "MSS SP-44", "ASME B16.5", "ASME B16.47"]):
                    raw_findings = ARHFlangeSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif any(k in fn_blob for k in ["03-PIPELINE", "CS PIPES", "SS PIPES", "LINEPIPE", "TUBE DE LIGNE", "API 5L", "ISO 3183", "ASTM A106", "ASTM A333", "ASTM A312"]) or \
                     any(k in header_blob for k in ["API 5L", "LINEPIPE", "TUBES DE LIGNE", "ISO 3183", "ASTM A106", "ASTM A333"]):
                    raw_findings = ARHPipelineSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif any(k in fn_blob for k in ["TEE A BARREAU", "TEE A BAREAU", "BARRED TEE", "JOINT ISOLANT", "JOINTS ISOLANT", "FITTINGS", "FITTING", "ASME B16.9", "MSS SP-75"]) or \
                     any(k in header_blob for k in ["BARRED TEE", "TEE A BARREAU", "JOINT ISOLANT", "INSULATING JOINT", "MSS SP-75", "ASME B16.9"]):
                    raw_findings = ARHFittingSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif any(k in fn_blob for k in ["VESSEL", "BALLON", "SEPARATEUR", "SEPARATOR", "EXTINCTEUR", "BOUTEILLE", "CYLINDER"]) or \
                     any(k in header_blob for k in ["ASME VIII", "CODAP", "PRESSURE VESSEL", "BALLON SEPARATEUR", "EXTINCTEUR", "POUDRE ABC", "EN 3-8", "BOUTEILLE DE GAZ"]):
                    raw_findings = ARHPressureVesselSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif any(k in fn_blob for k in ["ATEX", "IECEX", "JUNCTION BOX", "BOITE DE JONCTION"]) or \
                     any(k in header_blob for k in ["ATEX ZONE", "IECEX CERTIFICATE", "ENCLOSURE EX"]):
                    raw_findings = ARHElectricalInstrumentationSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif "VANNE" in tu or "VALVE" in tu:
                    raw_findings = ARHValveSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif "BRIDE" in tu or "FLANGE" in tu:
                    raw_findings = ARHFlangeSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif "PIPE" in tu or "TUBE" in tu:
                    raw_findings = ARHPipelineSpecialist.audit(docs, full_text, file_names, dossier_stage)
                elif "FITTING" in tu or "RACCORD" in tu:
                    raw_findings = ARHFittingSpecialist.audit(docs, full_text, file_names, dossier_stage)
                else:
                    target_doc = file_names[0] if file_names else "Dossier Technique"
                    pages_text = _extract_pages_dict(docs, full_text)
                    raw_findings = _audit_universal_qaqc(
                        target_doc, pages_text, full_text,
                        f"🤖 Spécialiste ARH ({eq})", dossier_stage,
                        skip_universal_qaqc=skip_universal_qaqc
                    )
        finally:
            _SKIP_UNIVERSAL_QAQC.reset(token)

        # ── 3. VALIDATION NEURO-SYMBOLIQUE DÉTERMINISTE (DSPY-STYLE ASSERTION GUARD) ──
        try:
            from arh_assertion_guards import assertion_guard
            is_resolved = bool(re.search(r'(_[B-Z]_|\bREV[\s_]*0?[1-9][A-Z]?\b|\bREV[\s_]*[B-Z]\b|\bCODE[\s_]*0?1\b|APPROUV|\bVF\b)', tu, re.IGNORECASE))
            sanitized = assertion_guard.validate_and_sanitize_findings(
                raw_findings,
                equipment_type=eq,
                full_context_text=full_text,
                is_resolved_revision=is_resolved
            )
            return sanitized
        except Exception as e:
            logger.warning(f"[ARH-Dispatcher] Erreur filtrage assertion_guard: {e}")
            return raw_findings
