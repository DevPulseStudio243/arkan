"""
arh_revision_comparator.py
==========================
Moteur de Comparaison et de Levée de Réserves Multi-Révisions pour ARKAN ARH Management.
Compare un dossier initial (Rev 00 / DRAFT) avec un dossier corrigé (Rev 01 / REV B).

Fonctionnalités :
  1. Tracking des Remarques :
     - 🟢 RÉSERVES LEVÉES (CLOSED) : Écarts corrigés en Rev 1
     - 🔴 RÉSERVES RECONDUITES (OPEN) : Écarts non résolus
     - 🟠 NOUVELLES ANOMALIES (REGRESSIONS) : Nouveaux écarts apparus en Rev 1
  2. Diff Paramétrique (Concordance Matrix Diff) :
     - Variations de pressions, températures, épaisseurs, nuances d'acier
  3. Diff Check-list Réglementaire (P-CTE-1) :
     - Documents précédemment manquants désormais fournis
  4. Calcul de l'indice d'amélioration et Décision ARH révisée
  5. Génération de la Matrice Officielle de Levée de Réserves
"""

import re
import datetime
from typing import Dict, List, Any, Optional, Tuple


class ARHRevisionComparator:
    """
    Comparateur intelligent de révisions de dossiers techniques ARH.
    """

    def __init__(self):
        pass

    def compare(
        self,
        dossier_rev0: Dict[str, Any],
        dossier_rev1: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Exécute la comparaison complète entre Rev 0 et Rev 1.
        """
        id0 = dossier_rev0.get("dossier_id", "REV_0")
        id1 = dossier_rev1.get("dossier_id", "REV_1")
        tag0 = dossier_rev0.get("equipment_tag", "EQUIP_0")
        tag1 = dossier_rev1.get("equipment_tag", "EQUIP_1")
        eq_type = dossier_rev1.get("equipment_type", dossier_rev0.get("equipment_type", "EQUIPMENT"))
        
        score0 = float(dossier_rev0.get("compliance_score", 0.0) or 0.0)
        score1 = float(dossier_rev1.get("compliance_score", 0.0) or 0.0)
        score_delta = round(score1 - score0, 1)

        dec0 = dossier_rev0.get("arh_decision", "NON CONFORME (REJETÉ)")
        dec1 = dossier_rev1.get("arh_decision", "NON CONFORME (REJETÉ)")

        comments0 = dossier_rev0.get("comments", [])
        comments1 = dossier_rev1.get("comments", [])

        # ── 1. CLASSIFICATION DES REMARQUES & LEVÉE DE RÉSERVES ──
        resolved_comments = []
        persisting_comments = []
        new_comments = []

        matched_rev1_ids = set()

        for c0 in comments0:
            c0_id = c0.get("id", "")
            c0_title = c0.get("title", "")
            c0_cat = c0.get("category", "")
            c0_page = c0.get("page", "")

            # Chercher correspondance en Rev 1 par similarité de titre ou catégorie/page
            match_in_rev1 = None
            for c1 in comments1:
                c1_id = c1.get("id", "")
                if c1_id in matched_rev1_ids:
                    continue

                if self._are_comments_matching(c0, c1):
                    match_in_rev1 = c1
                    matched_rev1_ids.add(c1_id)
                    break

            if match_in_rev1:
                # La réserve persiste toujours en Rev 1
                persisting_comments.append({
                    "ref_id": c0_id,
                    "title": c0_title,
                    "category": c0_cat,
                    "page_rev0": c0_page,
                    "page_rev1": match_in_rev1.get("page", "N/A"),
                    "priority": match_in_rev1.get("priority", c0.get("priority", "MAJOR")),
                    "status_rev0": "OUVERTE (OPEN)",
                    "status_rev1": "🔴 NON LEVÉE (RECONDUITE)",
                    "status_code": "PERSISTING",
                    "observation_rev0": c0.get("observation", c0_title),
                    "observation_rev1": match_in_rev1.get("observation", ""),
                    "action_required": match_in_rev1.get("action_required", c0.get("action_required", "")),
                    "responsible": match_in_rev1.get("responsible", c0.get("responsible", "Constructeur"))
                })
            else:
                # La réserve a été levée en Rev 1 !
                resolved_comments.append({
                    "ref_id": c0_id,
                    "title": c0_title,
                    "category": c0_cat,
                    "page_rev0": c0_page,
                    "page_rev1": "Corrigé / Validé",
                    "priority": c0.get("priority", "MAJOR"),
                    "status_rev0": "OUVERTE (OPEN)",
                    "status_rev1": "🟢 LEVÉE (CLOSED & CONFORME)",
                    "status_code": "RESOLVED",
                    "observation_rev0": c0.get("observation", c0_title),
                    "resolution_proof": f"Non-conformité résolue en {id1}. Paramètre ou document rendu conforme aux exigences ARH.",
                    "action_required": "Aucune action résiduelle (Clôturé).",
                    "responsible": c0.get("responsible", "Constructeur")
                })

        # Nouvelles anomalies introduites en Rev 1
        for c1 in comments1:
            c1_id = c1.get("id", "")
            if c1_id not in matched_rev1_ids:
                new_comments.append({
                    "ref_id": c1_id,
                    "title": c1.get("title", ""),
                    "category": c1.get("category", ""),
                    "page_rev0": "Non présent en Rev 0",
                    "page_rev1": c1.get("page", "N/A"),
                    "priority": c1.get("priority", "MAJOR"),
                    "status_rev0": "N/A",
                    "status_rev1": "🟠 NOUVEL ÉCART DÉTECTÉ (RÉGRESSION)",
                    "status_code": "NEW_REGRESSION",
                    "observation_rev0": "Absent de la révision précédente.",
                    "observation_rev1": c1.get("observation", c1.get("title", "")),
                    "action_required": c1.get("action_required", "Corriger la nouvelle incohérence apparue en Rev 1."),
                    "responsible": c1.get("responsible", "Constructeur")
                })

        # ── 2. DIFF DE LA CHECK-LIST RÉGLEMENTAIRE (DOCUMENTS REÇUS VS MANQUANTS) ──
        cl0 = {item.get("code"): item for item in dossier_rev0.get("mandatory_checklist", []) if item.get("code")}
        cl1 = {item.get("code"): item for item in dossier_rev1.get("mandatory_checklist", []) if item.get("code")}

        checklist_diff = []
        all_codes = set(cl0.keys()).union(set(cl1.keys()))

        for code in sorted(all_codes):
            item0 = cl0.get(code, {})
            item1 = cl1.get(code, {})
            name = item1.get("name") or item0.get("name") or code
            stat0 = item0.get("status", "MISSING")
            stat1 = item1.get("status", "MISSING")

            diff_status = "UNCHANGED"
            if stat0 == "MISSING" and stat1 == "RECEIVED":
                diff_status = "DOCUMENT_FURNISHED"
            elif stat0 == "RECEIVED" and stat1 == "MISSING":
                diff_status = "DOCUMENT_REMOVED"

            checklist_diff.append({
                "code": code,
                "name": name,
                "status_rev0": stat0,
                "status_rev1": stat1,
                "diff_status": diff_status,
                "matched_file_rev1": item1.get("matched_file", ""),
                "matched_page_rev1": item1.get("matched_page", "")
            })

        # ── 3. DIFF DE LA MATRICE DE CONCORDANCE PARAMÉTRIQUE ──
        matrix0 = {m.get("parameter_name"): m for m in dossier_rev0.get("concordance_matrix", []) if m.get("parameter_name")}
        matrix1 = {m.get("parameter_name"): m for m in dossier_rev1.get("concordance_matrix", []) if m.get("parameter_name")}

        parametric_diff = []
        all_params = set(matrix0.keys()).union(set(matrix1.keys()))

        for param in sorted(all_params):
            p0 = matrix0.get(param, {})
            p1 = matrix1.get(param, {})
            unit = p1.get("unit") or p0.get("unit", "")
            vals0 = p0.get("extracted_values", {})
            vals1 = p1.get("extracted_values", {})
            concord0 = p0.get("is_concordant", True)
            concord1 = p1.get("is_concordant", True)

            diff_tag = "IDENTICAL"
            if not concord0 and concord1:
                diff_tag = "CONCORDANCE_RESTORED"
            elif concord0 and not concord1:
                diff_tag = "NEW_INCONSISTENCY"
            elif vals0 != vals1:
                diff_tag = "VALUES_CHANGED"

            parametric_diff.append({
                "parameter_name": param,
                "unit": unit,
                "is_concordant_rev0": concord0,
                "is_concordant_rev1": concord1,
                "values_rev0": vals0,
                "values_rev1": vals1,
                "diff_tag": diff_tag
            })

        # ── 4. SYNTHÈSE STATISTIQUE & RÉSUMÉ ANALYTIQUE ──
        total_rev0_comments = len(comments0)
        total_resolved = len(resolved_comments)
        total_persisting = len(persisting_comments)
        total_new = len(new_comments)
        resolution_rate = round((total_resolved / max(total_rev0_comments, 1)) * 100.0, 1)

        summary_narrative = self._generate_comparison_narrative(
            id0, id1, tag1, eq_type, score0, score1, score_delta,
            total_resolved, total_persisting, total_new, resolution_rate, dec1
        )

        return {
            "rev0_dossier_id": id0,
            "rev1_dossier_id": id1,
            "equipment_tag": tag1 or tag0,
            "equipment_type": eq_type,
            "comparison_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kpis": {
                "score_rev0": score0,
                "score_rev1": score1,
                "score_delta": score_delta,
                "decision_rev0": dec0,
                "decision_rev1": dec1,
                "total_initial_reserves": total_rev0_comments,
                "resolved_reserves_count": total_resolved,
                "persisting_reserves_count": total_persisting,
                "new_regressions_count": total_new,
                "resolution_rate_percent": resolution_rate,
            },
            "matrix_tracking_sheet": {
                "resolved": resolved_comments,
                "persisting": persisting_comments,
                "new_regressions": new_comments,
                "all_matrix_rows": resolved_comments + persisting_comments + new_comments
            },
            "checklist_diff": checklist_diff,
            "parametric_diff": parametric_diff,
            "summary_narrative": summary_narrative
        }

    def _are_comments_matching(self, c0: Dict[str, Any], c1: Dict[str, Any]) -> bool:
        """
        Détermine si deux remarques de deux révisions distinctes correspondent au même écart.
        """
        t0 = c0.get("title", "").strip().upper()
        t1 = c1.get("title", "").strip().upper()

        if t0 == t1:
            return True

        # Même catégorie et même règle métier essentielle
        cat0 = c0.get("category", "").upper()
        cat1 = c1.get("category", "").upper()

        keywords = [
            ("CONSULAT", "CONSULAT"),
            ("BARREAU", "BARREAU"),
            ("ANNEXE E", "ANNEXE E"),
            ("TEMPERATURE", "TEMPERATURE"),
            ("WPS", "WPS"),
            ("PQR", "PQR"),
            ("ITP", "ITP"),
            ("HOLD POINT", "HOLD POINT"),
            ("PEINTURE", "PEINTURE"),
            ("DFT", "DFT"),
            ("NACE", "NACE"),
            ("HARDNESS", "HARDNESS"),
            ("DURETE", "DURETE"),
            ("HYDROTEST", "HYDROTEST"),
            ("EPREUVE", "EPREUVE"),
            ("MANQUANT", "MANQUANT"),
        ]

        if cat0 == cat1:
            for kw0, kw1 in keywords:
                if kw0 in t0 and kw1 in t1:
                    return True

        return False

    def _generate_comparison_narrative(
        self,
        id0: str,
        id1: str,
        tag: str,
        eq_type: str,
        score0: float,
        score1: float,
        score_delta: float,
        resolved: int,
        persisting: int,
        new_cnt: int,
        rate: float,
        decision: str
    ) -> str:
        """
        Génère une synthèse narrative rédigée pour le rapport officiel ARH.
        """
        sign = "+" if score_delta > 0 else ""
        text = (
            f"L'audit comparatif entre le dossier initial {id0} (Rev.00) et le dossier révisé {id1} (Rev.01) "
            f"pour l'équipement {tag} ({eq_type}) indique un taux de levée des réserves de {rate}% "
            f"({resolved} réserve(s) levée(s) sur un total initial de {resolved + persisting}).\n\n"
            f"Le score global de conformité évolue de {score0:.1f}% à {score1:.1f}% ({sign}{score_delta:.1f}%). "
        )

        if persisting > 0:
            text += f"Il subsiste {persisting} réserve(s) non traitée(s) / reconduite(s) nécessitant une mise en conformité impérative par le contractant EPC. "
        else:
            text += "L'ensemble des réserves documentaires et techniques initiales a été valablement clôturé. "

        if new_cnt > 0:
            text += f"⚠️ ATTENTION : {new_cnt} nouvelle(s) anomalie(s) ou régression(s) ont été identifiées dans la Révision 01. "

        text += f"\n\nDécision ARH actuelle pour la Révision 01 : {decision}."
        return text
