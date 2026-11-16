"""
arh_composition_analyzer.py
===========================
Analyseur de Composition Réglementaire et Détecteur de Documents Supplémentaires
pour les dossiers ARH (Autorité de Régulation des Hydrocarbures).

Fonctionnalités :
1. Vérification systématique de la présence de 100% des pièces obligatoires
   de composition du dossier (Checklist réglementaire ARH P-CTE-1).
2. Détection, identification et segmentation des documents et pièces supplémentaires
   (Annexes, Procédures de soudage, PWHT, CND, Étalonnage, Revêtement, Certificats ISO, etc.).
3. Génération des métadonnées et URLs de visualisation haute définition pour chaque pièce.
"""

from __future__ import annotations
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("ARHCompositionAnalyzer")

ADDITIONAL_PATTERNS = [
    {
        "id": "WPS_PACKAGE",
        "keywords": ["WPS", "WELDING PROCEDURE SPECIFICATION", "SPECIFICATION DES PROCEDURES DE SOUDAGE", "DESCRIPTIF DU MODE OPERATOIRE DE SOUDAGE", "DMOS"],
        "title": "Spécifications de Procédures de Soudage (Cahier WPS Usine)",
        "category": "SOUDAGE & ASSEMBLAGE",
        "icon": "ph-flame",
        "arh_status": "VALIDE",
        "arh_status_label": "Cahier de Soudage Conforme",
        "badge_color": "#27AE60",
        "note": "Cahier de soudage fabricant. L'inspecteur ARH exige d'identifier formellement la WPS appliquée et de joindre la PQR correspondante."
    },
    {
        "id": "WPQ_WELDER",
        "keywords": ["WPQ", "WELDER PERFORMANCE QUALIFICATION", "QUALIFICATION DE SOUDEUR", "HOMOLOGATION SOUDEUR", "QW-484", "ISO 9606", "EN 287"],
        "title": "Qualifications de Soudeurs (WPQ - ASME IX / ISO 9606)",
        "category": "QUALIFICATIONS PERSONNEL",
        "icon": "ph-certificate",
        "arh_status": "A_RETIRER_PRELIMINAIRE",
        "arh_status_label": "Pièce Excédentaire (À retirer au préliminaire)",
        "badge_color": "#E67E22",
        "note": "Selon la procédure P-CTE-1 de l'ARH, les qualifications individuelles de soudeurs (WPQ) ne doivent pas être incluses au stade préliminaire mais sont réservées au dossier final de montage chantier."
    },
    {
        "id": "PWHT_TREATMENT",
        "keywords": ["HEAT TREATMENT", "TRAITEMENT THERMIQUE", "PWHT", "NORMALISATION", "POST WELD HEAT TREATMENT", "DIAGRAMME DE TRAITEMENT"],
        "title": "Procédure de Traitement Thermique (PWHT / Normalisation)",
        "category": "TRAITEMENT THERMIQUE",
        "icon": "ph-thermometer-hot",
        "arh_status": "VALIDE",
        "arh_status_label": "Spécification Thermique Valide",
        "badge_color": "#27AE60",
        "note": "Cycle thermique prescrit pour l'atténuation des contraintes résiduelles de soudage et la garantie de la résilience NACE MR0175."
    },
    {
        "id": "ORIGIN_CONFORMITY",
        "keywords": ["PAYS D'ORIGINE", "COUNTRY OF ORIGIN", "CONFORMITE POUR UTILISATION", "CONFORMITY CERTIFICATE ATTESTING", "CERTIFICAT ATTESTANT"],
        "title": "Certificat de Conformité pour Utilisation dans le Pays d'Origine",
        "category": "ADMINISTRATIF & LÉGALISATION",
        "icon": "ph-stamp",
        "arh_status": "VALIDE",
        "arh_status_label": "Pièce Réglementaire Reçue",
        "badge_color": "#27AE60",
        "note": "Attestation légalisée obligatoire stipulant que le matériel est agréé pour un usage industriel dans son pays de fabrication."
    },
    {
        "id": "NDT_REPORTS",
        "keywords": ["CONTROLE NON DESTRUCTIF", "NON DESTRUCTIVE TESTING", "CND", "NDT REPORT", "ULTRASONS", "ULTRASONIC", "RADIOGRAPH", "MAGNETOSCOPIE", "MAGNETIC PARTICLE", "RESSUAGE", "PENETRANT"],
        "title": "Rapports d'Essais et Contrôles Non Destructifs (CND / NDT)",
        "category": "CONTRÔLES NON DESTRUCTIFS",
        "icon": "ph-scan",
        "arh_status": "VALIDE",
        "arh_status_label": "Rapports CND Conformes",
        "badge_color": "#27AE60",
        "note": "PV de contrôles volumiques (UT/RT) et surfaciques (MT/PT) attestant de l'absence de défauts inacceptables selon ASME / API."
    },
    {
        "id": "PAINTING_COATING",
        "keywords": ["PAINTING", "COATING", "PEINTURE", "SABLAGE", "REVETEMENT", "BLASTING", "ANTICORROSION", "APPLICATION REVETEMENT"],
        "title": "Spécification de Peinture, Sablage & Revêtement Anticorrosion",
        "category": "REVÊTEMENT & PROTECTION",
        "icon": "ph-paint-brush",
        "arh_status": "INFORMATIF",
        "arh_status_label": "Annexe Technique d'Appui",
        "badge_color": "#3498DB",
        "note": "Procédure d'application du système de revêtement de protection de surface externe de l'équipement."
    },
    {
        "id": "CALIBRATION_CERT",
        "keywords": ["CALIBRATION", "ETALONNAGE", "PRESSURE GAUGE", "MANOMETRE", "TEST BENCH", "BANC D'EPREUVE", "CERTIFICAT D'ETALONNAGE"],
        "title": "Certificats d'Étalonnage des Manomètres & Instruments de Mesure",
        "category": "MÉTROLOGIE & INSTRUMENTATION",
        "icon": "ph-gauge",
        "arh_status": "VALIDE",
        "arh_status_label": "Document Métrologique Conforme",
        "badge_color": "#27AE60",
        "note": "Attestations d'étalonnage des appareils de mesure de pression utilisés lors des tests hydrostatiques."
    },
    {
        "id": "ISO_QUALITY_CERT",
        "keywords": ["ISO 9001", "ISO 14001", "ISO 45001", "CERTIFICATE OF REGISTRATION", "SYSTEME DE MANAGEMENT QUALITE"],
        "title": "Certificat de Système de Management Qualité Usine (ISO 9001)",
        "category": "ASSURANCE QUALITÉ USINE",
        "icon": "ph-medal",
        "arh_status": "INFORMATIF",
        "arh_status_label": "Annexe d'Appui Qualité",
        "badge_color": "#3498DB",
        "note": "Certificat d'accréditation du système d'assurance qualité du site de fabrication."
    },
    {
        "id": "MATERIAL_LIST",
        "keywords": ["LISTE DE MATERIELS", "MATERIAL LIST", "LISTE DU MATERIEL", "BILL OF MATERIALS", "BOM"],
        "title": "Liste de Matériels & Bordereau de Fourniture Détaillé",
        "category": "NOMENCLATURE & MATÉRIEL",
        "icon": "ph-list-checks",
        "arh_status": "VALIDE",
        "arh_status_label": "Nomenclature Fournie",
        "badge_color": "#27AE60",
        "note": "Bordereau technique listant les spécifications, dimensions et nuances de chaque composant fourni."
    },
    {
        "id": "COMMENT_SHEET",
        "keywords": ["COMMENT SHEET", "FICHE DE REMARQUES", "OPEN COMMENTS", "RESERVES INGENIERIE", "REVUE D'INGENIERIE"],
        "title": "Fiches de Remarques Techniques & Revue d'Ingénierie",
        "category": "REVUE D'INGÉNIERIE",
        "icon": "ph-chat-circle-dots",
        "arh_status": "A_TRAITER",
        "arh_status_label": "Réserves en Cours de Traitement",
        "badge_color": "#F39C12",
        "note": "Fiches de commentaires d'ingénierie ouvertes ou levées pendant l'instruction du dossier."
    }
]


def analyze_dossier_composition(dossier_data: Dict[str, Any], dossier_stage: str = None) -> Dict[str, Any]:
    """
    Établit la Fiche Récapitulative Officielle de Composition du Dossier ARH :
    1. Identification formelle du STADE (Dossier Préliminaire Annexe A vs Dossier Final Annexe G).
    2. Vérification systématique en premier lieu de la présence de 100% des pièces obligatoires du stade.
    3. Traitement isolé des pièces non obligatoires (post-fabrication / anticipées) pour éviter toute confusion avec Arkan.
    4. Génération d'un Tableau Récapitulatif structuré (JSON et Markdown).
    """
    checklist = dossier_data.get("mandatory_checklist", [])
    
    stage = dossier_stage or dossier_data.get("dossier_stage") or "PRELIMINARY"
    stage_label = "DOSSIER PRÉLIMINAIRE (CONCEPTION / ÉTUDES / P-CTE-1 ANNEXE A)" if stage == "PRELIMINARY" else "DOSSIER FINAL DE RÉCEPTION (CONSTRUCTION / P-CTE-1 ANNEXE G)"
    
    # ── Résolution des pièces découpées (SQLite / Mémoire) ──
    sliced_pieces = dossier_data.get("sliced_pieces") or []
    dossier_id = dossier_data.get("dossier_id")
    if not sliced_pieces and dossier_id:
        try:
            from arh_document_slicer import arh_slicer
            sliced_pieces = arh_slicer.get_sliced_pieces(dossier_id)
        except Exception:
            sliced_pieces = []

    DOC_CODE_MAP = {
        "LETTRE_DEMANDE_AVIS": "DOC-01", "REQ_LETTER": "DOC-01", "DOC-01": "DOC-01",
        "CERT_SIGNATURES_FABRICANT": "DOC-02", "LEGAL_VISA": "DOC-02", "DOC-02": "DOC-02",
        "CERT_VISITE_INT_EXT": "DOC-03", "COC_INSPECTION": "DOC-03", "DOC-03": "DOC-03",
        "CERT_PAYS_ORIGINE": "DOC-04", "ORIGIN_COC": "DOC-04", "DOC-04": "DOC-04", "CE_DECL": "DOC-04",
        "ETAT_DESCRIPTIF": "DOC-05", "ANNEXE_E": "DOC-05", "DS": "DOC-05", "DOC-05": "DOC-05",
        "CALC": "DOC-06", "NOTE_CALCUL": "DOC-06", "SIZING_NOTE": "DOC-06", "DOC-06": "DOC-06",
        "PLANS_DETAILLES_INDEX": "DOC-07", "PLANS": "DOC-07", "GA_DWG": "DOC-07", "DOC-07": "DOC-07",
        "WPS_PQR": "DOC-08", "WELD_BOOK": "DOC-08", "WELD_CERT": "DOC-08", "DOC-08": "DOC-08",
        "TRAIT_THERMIQUE_SPEC": "DOC-09", "PWHT_SPEC": "DOC-09", "DOC-09": "DOC-09",
        "ITP": "DOC-10", "QA_ITP": "DOC-10", "INSP_REP": "DOC-10", "DOC-10": "DOC-10",
        "HYDRO_PV": "DOC-11", "TEST_PV": "DOC-11", "FAT": "DOC-11", "DOC-11": "DOC-11",
        "MAT_CERT": "DOC-12", "DOC-12": "DOC-12",
        "NDT_REP": "DOC-13", "DOC-13": "DOC-13",
        "DIM_CERT": "DOC-14", "DOC-14": "DOC-14",
    }

    sliced_by_code = {p.get("piece_code"): p for p in sliced_pieces if p.get("piece_code")}

    primary_file = ""
    for k_f in ("files", "source_documents", "ingested_files"):
        f_list = dossier_data.get(k_f) or []
        if f_list and isinstance(f_list, list) and f_list[0]:
            primary_file = f_list[0]
            break

    mandatory_pieces = []
    non_mandatory_pieces = []
    received_count = 0
    missing_count = 0
    not_required_count = 0
    
    for item in checklist:
        code = item.get("code", "DOC")
        name = item.get("name", "Document Réglementaire")
        status = item.get("status", "MISSING")
        crit = item.get("criticality", "Critical")
        matched_page = item.get("matched_page")
        matched_file = item.get("matched_file", "")
        if not matched_file or matched_file == "?":
            matched_file = primary_file
        decree_ref = item.get("decree_reference") or item.get("standard") or ("P-CTE-1 Annexe A" if stage == "PRELIMINARY" else "P-CTE-1 Annexe G")
        
        target_doc_code = DOC_CODE_MAP.get(code, code)
        piece_match = sliced_by_code.get(target_doc_code) or sliced_by_code.get(code)

        is_na = item.get("is_na", False) or (status == "NOT_APPLICABLE_STAGE") or (item.get("status_badge") == "NOT_APPLICABLE_STAGE")

        if piece_match and not is_na:
            start_page = piece_match.get("page_start", 1)
            end_page = piece_match.get("page_end", start_page)
            page_count = piece_match.get("page_count", (end_page - start_page + 1))
            matched_page = start_page
            is_received = True
            matched_file = matched_file or primary_file
        else:
            start_page = item.get("start_page") or item.get("matched_page")
            end_page = item.get("end_page") or start_page
            page_count = item.get("page_count") or ((end_page - start_page + 1) if (start_page and end_page) else 1)
            is_received = (status == "RECEIVED") or (item.get("is_received") is True)

        if is_na:
            pages_display = "Non Applicable (N/A déclaré)"
            start_page = None
            end_page = None
            page_count = 0
        elif start_page and end_page and start_page != end_page:
            pages_display = f"Pages {start_page} à {end_page} ({page_count} p.)"
        elif start_page:
            pages_display = f"Page {start_page}"
        else:
            pages_display = "—"

        is_stage_optional = (crit == "Stage_Optional") or item.get("is_stage_optional") or (status == "NOT_YET_REQUIRED") or is_na
        
        if is_stage_optional:
            # ── SECTION 2 : PIÈCE NON OBLIGATOIRE AU STADE ACTUEL ──
            not_required_count += 1
            if is_na:
                stat_badge = "NOT_APPLICABLE_STAGE"
                stat_label = "Non applicable (N/A déclaré)"
                badge_col = "#7F8C8D"
                note_str = item.get("note") or "Déclaré Non Applicable par le constructeur dans le sommaire officiel."
            elif is_received:
                stat_badge = "RECEIVED_ANTICIPATED"
                stat_label = "Présent par anticipation (Non bloquant)"
                badge_col = "#2980B9"
                note_str = "Pièce fournie par anticipation. Valable à titre informatif ; ne constitue aucun motif de rejet technique en phase préliminaire."
            else:
                stat_badge = "NOT_APPLICABLE_STAGE"
                stat_label = "Non exigible à ce stade (Différé au dossier final)"
                badge_col = "#7F8C8D"
                note_str = item.get("stage_note") or "Exigé au dossier final de réception constructeur (P-CTE-1 Annexe G). Aucune pénalité Arkan."
            
            non_mandatory_pieces.append({
                "code": code,
                "name": name,
                "status": stat_badge,
                "status_label": stat_label,
                "badge_color": badge_col,
                "is_received": is_received and not is_na,
                "is_na": is_na,
                "criticality": "Stage_Optional",
                "decree_reference": decree_ref,
                "start_page": start_page,
                "end_page": end_page,
                "page_count": page_count,
                "pages_display": pages_display,
                "matched_page": start_page if (is_received and not is_na) else None,
                "matched_file": matched_file if (is_received and not is_na) else "",
                "note": note_str
            })
        else:
            # ── SECTION 1 : PIÈCE RÉGLEMENTAIRE OBLIGATOIRE DU STADE ──
            if is_received:
                received_count += 1
                stat_badge = "PRESENT"
                stat_label = "Présent / Reçu [OK]"
                badge_col = "#27AE60"
            else:
                missing_count += 1
                stat_badge = "MISSING"
                stat_label = "MANQUANT [✕]"
                badge_col = "#E74C3C"

            if crit == "Critical":
                crit_label = "Obligatoire (Critique)"
                crit_color = "#E74C3C"
            else:
                crit_label = "Recommandé / Majeur"
                crit_color = "#F39C12"

            mandatory_pieces.append({
                "code": code,
                "name": name,
                "status": stat_badge,
                "status_label": stat_label,
                "badge_color": badge_col,
                "is_received": is_received,
                "is_na": False,
                "criticality": crit,
                "criticality_label": crit_label,
                "criticality_color": crit_color,
                "decree_reference": decree_ref,
                "start_page": start_page,
                "end_page": end_page,
                "page_count": page_count,
                "pages_display": pages_display,
                "matched_page": start_page if is_received else None,
                "matched_file": matched_file if is_received else "",
                "note": item.get("note", "")
            })

    total_strictly_required = len(mandatory_pieces)
    completion_rate = round((received_count / max(total_strictly_required, 1)) * 100, 1) if total_strictly_required > 0 else 100.0
    is_fully_composed = (missing_count == 0)

    reception_status = "RECEVABLE" if missing_count == 0 else ("RECEVABLE_AVEC_RESERVES" if completion_rate >= 60.0 else "IRRECEVABLE")

    # ── GÉNÉRATION DU TABLEAU RÉCAPITULATIF MARKDOWN ──
    lines = []
    lines.append(f"### 📋 TABLEAU RÉCAPITULATIF DE COMPOSITION DU DOSSIER ARH")
    lines.append(f"- **Stade Réglementaire Identifié :** **{stage_label}**")
    lines.append(f"- **Taux de Complétude des Pièces Obligatoires :** **{completion_rate}%** ({received_count} / {total_strictly_required} pièces reçues)")
    lines.append(f"- **Statut de Recevabilité Documentaire :** **{'✅ DOSSIER RECEVABLE' if reception_status == 'RECEVABLE' else ('⚠️ RECEVABLE AVEC RÉSERVES (CODE 02)' if reception_status == 'RECEVABLE_AVEC_RESERVES' else '❌ IRRECEVABLE POUR INCOMPLÉTUDE (CODE 03)')}**")
    lines.append("")
    lines.append("#### 1. Pièces Réglementaires Obligatoires (Stade Actuel)")
    lines.append("| N° | Code | Intitulé Réglementaire | Référence | Statut | Localisation selon Index |")
    lines.append("| :-: | :--- | :--- | :--- | :---: | :--- |")
    for idx, p in enumerate(mandatory_pieces, 1):
        st_icon = "✅ PRÉSENT" if p["is_received"] else "❌ MANQUANT"
        loc = p.get("pages_display", "—")
        if p["is_received"] and p.get("matched_file"):
            loc = f"{loc} (`{p['matched_file']}`)"
        lines.append(f"| {idx:02d} | `{p['code']}` | **{p['name']}** | {p['decree_reference']} | {st_icon} | {loc} |")

    lines.append("")
    lines.append("#### 2. Pièces Non Obligatoires / Hors Périmètre du Stade (Évitement de Confusion Arkan)")
    if non_mandatory_pieces:
        lines.append("| N° | Code | Pièce Technique | Exigence à ce Stade | Statut Détecté | Règle ARH Applicable | Localisation |")
        lines.append("| :-: | :--- | :--- | :--- | :---: | :--- | :--- |")
        for idx, p in enumerate(non_mandatory_pieces, 1):
            if p.get("is_na"):
                stat_str = "⚪ Non Applicable (N/A)"
            elif p["is_received"]:
                stat_str = "ℹ️ Présent par anticipation"
            else:
                stat_str = "⚪ Non exigible"
            lines.append(f"| {idx:02d} | `{p['code']}` | {p['name']} | Différé au dossier final | {stat_str} | {p['note']} | {p.get('pages_display', '—')} |")
    else:
        lines.append("*Toutes les pièces examinées sont strictement obligatoires pour ce stade.*")

    lines.append("")
    lines.append("---")
    recap_table_md = "\n".join(lines)

    return {
        "dossier_stage": stage,
        "dossier_stage_label": stage_label,
        "total_checklist_items": len(checklist),
        "total_required": total_strictly_required,
        "received_count": received_count,
        "missing_count": missing_count,
        "not_required_count": not_required_count,
        "completion_rate": completion_rate,
        "is_fully_composed": is_fully_composed,
        "reception_status": reception_status,
        "mandatory_pieces": mandatory_pieces,
        "non_mandatory_pieces": non_mandatory_pieces,
        "missing_pieces": [p for p in mandatory_pieces if p["status"] == "MISSING"],
        "recap_table_markdown": recap_table_md
    }


def detect_additional_documents(dossier_id: str, dossier_data: Dict[str, Any], uploads_base_dir: str = r"d:\DATA BASE IA\arh_uploads") -> List[Dict[str, Any]]:
    """
    Détecte et segmente l'ensemble des documents supplémentaires présents dans le dossier :
    - Scanne les fichiers sources PDF du dossier
    - Identifie les chapitres, procédures de soudage, PWHT, CND, métrologie, certificats d'origine, etc.
    - Génère les plages de pages et vignettes visuelles.
    """
    dossier_dir = Path(uploads_base_dir) / dossier_id
    if not dossier_dir.exists():
        return []

    pdf_files = [f.name for f in dossier_dir.iterdir() if f.name.lower().endswith(".pdf") and not f.name.startswith("annotated_")]
    if not pdf_files:
        pdf_files = [f.name for f in dossier_dir.iterdir() if f.name.lower().endswith(".pdf")]

    additional_docs = []
    seen_keys = set()

    try:
        import fitz
    except ImportError:
        logger.warning("[ARH-Composition] PyMuPDF (fitz) non disponible pour l'extraction de pages.")
        return []

    for fname in pdf_files:
        fpath = dossier_dir / fname
        try:
            doc = fitz.open(str(fpath))
            total_pages = len(doc)
            
            for pat in ADDITIONAL_PATTERNS:
                matching_pages = []
                for p_idx in range(total_pages):
                    p_num = p_idx + 1
                    p_txt = doc[p_idx].get_text()
                    pu = p_txt.upper()
                    
                    if p_num <= 2 and "SOMMAIRE" in pu and "TABLE OF CONTENTS" in pu:
                        continue

                    if any(itp_term in pu for itp_term in ["INSPECTION & TEST PLAN", "INSPECTION AND TEST PLAN", "ITP FOR FITTING"]) and len(pu.split("\n")) > 10 and pat["id"] not in ("WPS_PACKAGE", "NDT_REPORTS"):
                        continue

                    if any(kw in pu for kw in pat["keywords"]):
                        matching_pages.append(p_num)

                if matching_pages:
                    ranges = []
                    range_start = matching_pages[0]
                    prev_p = matching_pages[0]
                    for p in matching_pages[1:]:
                        if p == prev_p + 1:
                            prev_p = p
                        else:
                            ranges.append((range_start, prev_p))
                            range_start = p
                            prev_p = p
                    ranges.append((range_start, prev_p))

                    for r_start, r_end in ranges:
                        p_count = (r_end - r_start) + 1
                        p_display = f"Page {r_start}" if r_start == r_end else f"Pages {r_start} à {r_end}"
                        
                        dedup_key = f"{pat['id']}::{r_start}::{r_end}"
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)

                        raw_snip = doc[r_start - 1].get_text().strip().replace("\n", " ")
                        raw_snip = re.sub(r'\s+', ' ', raw_snip)
                        preview_snip = raw_snip[:220] if raw_snip else pat["title"]

                        doc_entry = {
                            "id": f"ADD_{pat['id']}_{r_start}",
                            "title": pat["title"],
                            "category": pat["category"],
                            "icon": pat["icon"],
                            "file_name": fname,
                            "start_page": r_start,
                            "end_page": r_end,
                            "pages_display": p_display,
                            "page_count": p_count,
                            "arh_status": pat["arh_status"],
                            "arh_status_label": pat["arh_status_label"],
                            "badge_color": pat["badge_color"],
                            "arh_note": pat["note"],
                            "preview_snippet": preview_snip,
                            "thumbnail_url": f"/api/arh/dossiers/{dossier_id}/pages/{fname}/{r_start}.png"
                        }
                        additional_docs.append(doc_entry)

            doc.close()
        except Exception as err:
            logger.error("[ARH-Composition] Erreur lecture document %s: %s", fname, err)

    additional_docs.sort(key=lambda d: d.get("start_page", 0))
    return additional_docs


def get_full_dossier_composition_report(dossier_id: str, dossier_data: Dict[str, Any], uploads_base_dir: str = r"d:\DATA BASE IA\arh_uploads") -> Dict[str, Any]:
    """
    Point d'entrée global : retourne la fiche récapitulative complète + documents supplémentaires.
    """
    if dossier_id and not dossier_data.get("dossier_id"):
        dossier_data["dossier_id"] = dossier_id
    d_stage = dossier_data.get("dossier_stage") or "PRELIMINARY"
    comp_summary = analyze_dossier_composition(dossier_data, dossier_stage=d_stage)
    additional_docs = detect_additional_documents(dossier_id, dossier_data, uploads_base_dir)
    
    return {
        "dossier_id": dossier_id,
        "project_name": dossier_data.get("project_name", "PROJET ARH"),
        "unit_name": dossier_data.get("unit_name", "-"),
        "equipment_tag": dossier_data.get("equipment_tag", "-"),
        "equipment_type": dossier_data.get("equipment_type", "UNKNOWN"),
        "equipment_label": dossier_data.get("equipment_label", "Équipement"),
        "dossier_stage": dossier_data.get("dossier_stage", "PRELIMINARY"),
        "dossier_stage_label": dossier_data.get("dossier_stage_label", "Dossier Préliminaire"),
        "status": dossier_data.get("status", "REJECTED"),
        "arh_decision": dossier_data.get("arh_decision", "NON CONFORME"),
        "compliance_score": dossier_data.get("compliance_score", 0.0),
        "created_at": dossier_data.get("created_at", ""),
        "composition_summary": comp_summary,
        "additional_documents": additional_docs,
        "additional_documents_count": len(additional_docs)
    }
