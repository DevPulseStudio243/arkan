"""
ei_triangulation_engine.py
==========================
Moteur de Triangulation Totale E&I (Plan CAD vs Carnet de Câbles vs Note de Calcul vs MTO ARKAN).
Confronte les 4 sources et génère les fiches d'arbitrage comparatives 3 colonnes
avec proposition d'articles normalisés et traçabilité experte.
Conforme aux standards IEC 60364 / CEI 61537 / NF C 15-100 et Directive Workspace Règle 4.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from cable_parser import parse_cable, estimate_cable_weight_kg_m
from tag_normalizer import normalize_tag

logger = logging.getLogger("arkan.ei_triangulation")

# Sections normalisées en cuivre selon CEI 60228 (mm²)
STANDARD_SECTIONS_CU = [
    1.5, 2.5, 4.0, 6.0, 10.0, 16.0, 25.0, 35.0, 50.0, 70.0, 95.0,
    120.0, 150.0, 185.0, 240.0, 300.0, 400.0, 500.0, 630.0
]


def _get_next_standard_section(current_sec_mm2: float) -> float:
    """Retourne la section normalisée immédiatement supérieure."""
    for s in STANDARD_SECTIONS_CU:
        if s > current_sec_mm2 + 0.1:
            return s
    return current_sec_mm2 * 1.5


def _extract_primary_cross_section(sec_str: Optional[str]) -> Optional[float]:
    """Extrait la section numérique de phase (ex: 4G16 -> 16.0, 3x120+70 -> 120.0)."""
    if not sec_str:
        return None
    parsed = parse_cable(sec_str)
    return parsed.get("section_mm2") if parsed else None


def _format_upsized_cable(sec_str: Optional[str], next_s: float) -> str:
    """Reconstruit une désignation normalisée avec la section surdimensionnée."""
    if not sec_str:
        return f"4G{int(next_s)}"
    p = parse_cable(sec_str)
    if not p:
        return f"{int(next_s)}mm²"
    n = p.get("n_conductors", 3)
    s_val = int(next_s) if next_s.is_integer() else next_s
    if p.get("family") == "INSTRUMENTATION":
        return f"{max(1, n // 2)}P{s_val}"
    extra = p.get("reduced_section_mm2")
    if extra:
        return f"3x{s_val}+{int(extra)}"
    sep = "G" if (p.get("has_earth") and n > 1) else "x"
    return f"{n}{sep}{s_val}"


class EITriangulationEngine:
    """Moteur central de confrontation triangulaire E&I."""

    def __init__(
        self,
        length_tolerance_pct: float = 10.0,
        max_voltage_drop_power_pct: float = 5.0,
        max_voltage_drop_control_pct: float = 3.0,
    ) -> None:
        self.length_tolerance_pct = length_tolerance_pct
        self.max_voltage_drop_power_pct = max_voltage_drop_power_pct
        self.max_voltage_drop_control_pct = max_voltage_drop_control_pct

    def triangulate(
        self,
        cad_feeders: List[Dict[str, Any]],
        cable_schedule_items: List[Dict[str, Any]],
        calc_note_items: List[Dict[str, Any]],
        cad_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Exécute la triangulation totale sur les 4 axes.
        Retourne un dictionnaire contenant les statistiques globales et les fiches d'arbitrage.
        """
        cad_dict: Dict[str, Dict[str, Any]] = {}
        for f in cad_feeders:
            t = normalize_tag(f.get("tag", ""))
            if t:
                cad_dict[t] = f

        cs_dict: Dict[str, Dict[str, Any]] = {}
        for item in cable_schedule_items:
            t = normalize_tag(item.get("tag", ""))
            if t:
                cs_dict[t] = item

        cn_dict: Dict[str, Dict[str, Any]] = {}
        for item in calc_note_items:
            t = normalize_tag(item.get("tag", ""))
            if t:
                cn_dict[t] = item

        all_tags: Set[str] = set(cad_dict.keys()) | set(cs_dict.keys()) | set(cn_dict.keys())

        cards: List[Dict[str, Any]] = []
        stats = {
            "total_tags_triangulated": len(all_tags),
            "fully_consistent_count": 0,
            "discrepancies_count": 0,
            "critical_count": 0,
            "warning_count": 0,
            "info_count": 0,
        }

        for tag in sorted(all_tags):
            cad_f = cad_dict.get(tag)
            cs_f = cs_dict.get(tag)
            cn_f = cn_dict.get(tag)

            discrepancy = self._analyze_tag_triangulation(tag, cad_f, cs_f, cn_f)
            if discrepancy:
                cards.append(discrepancy)
                stats["discrepancies_count"] += 1
                sev = discrepancy.get("severity", "WARNING")
                if sev == "CRITICAL":
                    stats["critical_count"] += 1
                elif sev == "WARNING":
                    stats["warning_count"] += 1
                else:
                    stats["info_count"] += 1
            else:
                stats["fully_consistent_count"] += 1

        return {
            "summary": stats,
            "discrepancy_cards": cards,
            "cad_feeders_count": len(cad_dict),
            "cable_schedule_count": len(cs_dict),
            "calc_note_count": len(cn_dict),
        }

    def _analyze_tag_triangulation(
        self,
        tag: str,
        cad_f: Optional[Dict[str, Any]],
        cs_f: Optional[Dict[str, Any]],
        cn_f: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Analyse un câble sur les 4 axes de triangulation."""

        # -------------------------------------------------------------
        # AXE 1 : DÉTECTION DES OUBLIS (OMISSIONS)
        # -------------------------------------------------------------
        # Cas 1.1 : Sur le Plan CAD et la Note, mais oublié dans le Carnet de Câbles
        if cad_f and cn_f and not cs_f:
            l_cad = cad_f.get("length_m") or cad_f.get("cable_len_m") or cn_f.get("calc_length_m") or 0.0
            sec = cn_f.get("calc_section") or "3x120+70"
            return self._build_card(
                tag=tag,
                category="OMISSION",
                severity="CRITICAL",
                title="Câble omis dans le Carnet de Câbles",
                cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                comment=(
                    f"Le départ {tag} est raccordé sur le plan CAD et dimensionné dans la note de calcul, "
                    f"mais totalement absent du Carnet de Câbles de l'ingénieur. Oubli critique."
                ),
                proposed_section=sec,
                proposed_length=l_cad,
                proposed_action="INJECT_MISSING_CABLE"
            )

        # Cas 1.2 : Dans le Carnet et la Note, mais absent / non raccordé sur le Plan CAD
        if cs_f and cn_f and not cad_f:
            l_cs = cs_f.get("declared_length_m") or cn_f.get("calc_length_m") or 0.0
            sec = cs_f.get("declared_section") or cn_f.get("calc_section") or "3x120+70"
            return self._build_card(
                tag=tag,
                category="OMISSION",
                severity="WARNING",
                title="Câble absent ou non raccordé sur le Plan CAD",
                cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                comment=(
                    f"Le câble {tag} est listé au carnet et dans la note de calcul, "
                    f"mais le récepteur ou le cheminement n'a pas été identifié sur le plan CAD."
                ),
                proposed_section=sec,
                proposed_length=l_cs,
                proposed_action="CONFIRM_ROUTING_OR_ESTIMATE"
            )

        # Cas 1.3 : Présent sur Plan et Carnet, mais omis de la Note de Calcul
        if cad_f and cs_f and not cn_f:
            l_cad = cad_f.get("length_m") or cs_f.get("declared_length_m") or 0.0
            sec = cs_f.get("declared_section") or "5X6"
            return self._build_card(
                tag=tag,
                category="OMISSION",
                severity="WARNING",
                title="Câble non dimensionné dans la Note de Calcul",
                cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                comment=(
                    f"Le câble {tag} apparaît sur le plan et le carnet de câbles, "
                    f"mais aucune justification par note de calcul (Caneco/ETAP) n'a été trouvée."
                ),
                proposed_section=sec,
                proposed_length=l_cad,
                proposed_action="REQUIRE_CALC_NOTE_JUSTIFICATION"
            )

        # Cas 1.4 : Unique à une seule source (ex: présent seulement au carnet)
        if sum(1 for x in [cad_f, cs_f, cn_f] if x is not None) == 1:
            source_name = "Carnet" if cs_f else ("Note" if cn_f else "Plan CAD")
            l_val = (cs_f or cn_f or cad_f).get("declared_length_m") or (cs_f or cn_f or cad_f).get("calc_length_m") or (cs_f or cn_f or cad_f).get("length_m") or 0.0
            sec = (cs_f or cn_f or cad_f).get("declared_section") or (cs_f or cn_f or cad_f).get("calc_section") or "5X6"
            return self._build_card(
                tag=tag,
                category="OMISSION",
                severity="INFO",
                title=f"Câble isolé identifié uniquement dans {source_name}",
                cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                comment=f"Ce câble n'a de correspondance dans aucune des deux autres sources.",
                proposed_section=sec,
                proposed_length=l_val,
                proposed_action="INVESTIGATE_ISOLATED_CABLE"
            )

        # Si les trois sources (ou au moins deux) existent, analyser les valeurs physiques
        # -------------------------------------------------------------
        # AXE 2 : ÉCARTS DE LONGUEUR (CAD vs CARNET vs NOTE)
        # -------------------------------------------------------------
        l_cad = cad_f.get("length_m") or cad_f.get("cable_len_m") if cad_f else None
        l_cs = cs_f.get("declared_length_m") if cs_f else None
        l_cn = cn_f.get("calc_length_m") if cn_f else None

        if l_cad is not None and l_cs is not None and l_cs > 0:
            delta_pct = ((l_cad - l_cs) / l_cs) * 100.0
            if delta_pct > self.length_tolerance_pct:
                # CAD plus long que le carnet (Sous-estimation carnet)
                sec = (cn_f and cn_f.get("calc_section")) or (cs_f and cs_f.get("declared_section")) or "5X6"
                return self._build_card(
                    tag=tag,
                    category="LENGTH_MISMATCH",
                    severity="CRITICAL" if delta_pct > 20.0 else "WARNING",
                    title="Métré sous-estimé dans le Carnet de Câbles",
                    cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                    comment=(
                        f"La longueur physique mesurée sur le plan CAD ({l_cad:.1f} m) dépasse la longueur "
                        f"déclarée au carnet ({l_cs:.1f} m) de {delta_pct:.1f}%. Risque de déficit au chiffrage."
                    ),
                    proposed_section=sec,
                    proposed_length=round(l_cad, 1),
                    proposed_action="UPDATE_LENGTH_TO_CAD"
                )
            elif delta_pct < -self.length_tolerance_pct and abs(delta_pct) > 20.0:
                # Carnet nettement plus long que le tracé
                sec = (cn_f and cn_f.get("calc_section")) or (cs_f and cs_f.get("declared_section")) or "5X6"
                return self._build_card(
                    tag=tag,
                    category="LENGTH_MISMATCH",
                    severity="INFO",
                    title="Métré carnet supérieur au tracé CAD",
                    cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                    comment=(
                        f"Le carnet prévoit {l_cs:.1f} m contre {l_cad:.1f} m calculés sur plan (-{abs(delta_pct):.1f}%). "
                        f"Marge projet ou tracé 3D plus tortueux."
                    ),
                    proposed_section=sec,
                    proposed_length=round(l_cs, 1),
                    proposed_action="KEEP_CONSERVATIVE_LENGTH"
                )

        # -------------------------------------------------------------
        # AXE 3 : SECTION ET RECALCUL CHUTE DE TENSION (DELTA U %)
        # -------------------------------------------------------------
        sec_cad = cad_f.get("cable_section") if cad_f else None
        sec_cs = cs_f.get("declared_section") if cs_f else None
        sec_cn = cn_f.get("calc_section") if cn_f else None

        effective_sec_str = sec_cn or sec_cs or sec_cad
        ref_length = l_cad if (l_cad and l_cad > 0) else (l_cs or l_cn or 0.0)

        # Si nous avons la note de calcul avec chute de tension et longueur de calcul
        if cn_f and l_cad and l_cn and l_cn > 0:
            init_du = cn_f.get("calc_du_pct")
            if init_du is not None and init_du > 0:
                # Recalcul de chute de tension au prorata de la longueur réelle CAD
                recalc_du = init_du * (l_cad / l_cn)
                max_du = self.max_voltage_drop_control_pct if "1P" in (effective_sec_str or "") else self.max_voltage_drop_power_pct

                if recalc_du > max_du:
                    # Chute de tension dépassée sur métré réel CAD !
                    current_s = _extract_primary_cross_section(effective_sec_str) or 16.0
                    next_s = _get_next_standard_section(current_s)
                    # Nouvelle chute de tension approximée : Delta U proportionnel à 1/S
                    recalc_du_corrected = recalc_du * (current_s / next_s)
                    corr_sec_str = _format_upsized_cable(effective_sec_str, next_s)

                    return self._build_card(
                        tag=tag,
                        category="VOLTAGE_DROP_EXCEEDED",
                        severity="CRITICAL",
                        title="Chute de tension inadmissible sur tracé réel CAD",
                        cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                        comment=(
                            f"La note prévoyait {effective_sec_str} pour {l_cn:.1f} m (ΔU = {init_du:.2f}%). "
                            f"Avec la longueur réelle CAD de {l_cad:.1f} m, la chute de tension atteint {recalc_du:.2f}% "
                            f"(seuil max {max_du}%). Surdimensionnement obligatoire en {corr_sec_str} (ΔU estimé: {recalc_du_corrected:.2f}%)."
                        ),
                        proposed_section=corr_sec_str,
                        proposed_length=round(l_cad, 1),
                        proposed_action="UPSIZE_SECTION_VOLTAGE_DROP"
                    )

        # Vérification simple de divergence de section entre le carnet et la note
        if sec_cs and sec_cn and sec_cs.upper().replace(" ", "") != sec_cn.upper().replace(" ", ""):
            return self._build_card(
                tag=tag,
                category="SPEC_MISMATCH",
                severity="WARNING",
                title="Divergence de section Carnet vs Note de Calcul",
                cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                comment=(
                    f"Le Carnet de Câbles indique '{sec_cs}' alors que la Note de Calcul retient '{sec_cn}'. "
                    f"La section de la Note de Calcul est préconisée pour garantir la conformité thermique et Icc."
                ),
                proposed_section=sec_cn,
                proposed_length=round(ref_length, 1),
                proposed_action="ALIGN_TO_CALC_NOTE_SECTION"
            )

        # -------------------------------------------------------------
        # AXE 4 : SPÉCIFICATION ET TYPE DE CÂBLE (ISOLANT / ARMURE / ÂME)
        # -------------------------------------------------------------
        type_cs = (cs_f and cs_f.get("cable_type") or "").upper()
        type_cn = (cn_f and cn_f.get("cable_type") or "").upper()
        if type_cs and type_cn:
            # Vérifier divergence flagrante (ex: PVC vs XLPE ou CU vs AL)
            pvc_vs_xlpe = ("PVC" in type_cs and "XLPE" in type_cn) or ("XLPE" in type_cs and "PVC" in type_cn)
            cu_vs_al = ("CU" in type_cs and "AL" in type_cn) or ("AL" in type_cs and "CU" in type_cn)
            if pvc_vs_xlpe or cu_vs_al:
                return self._build_card(
                    tag=tag,
                    category="SPEC_MISMATCH",
                    severity="WARNING",
                    title="Incohérence de type d'isolant ou d'âme (Carnet vs Note)",
                    cad_f=cad_f, cs_f=cs_f, cn_f=cn_f,
                    comment=f"Spécification discordante : Carnet '{type_cs}' vs Note '{type_cn}'.",
                    proposed_section=effective_sec_str or "5X6",
                    proposed_length=round(ref_length, 1),
                    proposed_action="CONFIRM_CABLE_SPEC"
                )

        return None

    def _build_card(
        self,
        tag: str,
        category: str,
        severity: str,
        title: str,
        cad_f: Optional[Dict[str, Any]],
        cs_f: Optional[Dict[str, Any]],
        cn_f: Optional[Dict[str, Any]],
        comment: str,
        proposed_section: str,
        proposed_length: float,
        proposed_action: str,
    ) -> Dict[str, Any]:
        """Construit une fiche d'arbitrage 3 colonnes avec item proposé normalisé."""
        disc_id = f"DISC-{tag}-{uuid.uuid4().hex[:6].upper()}"

        # Calcul des caractéristiques physiques du câble proposé (diamètre, poids/m)
        p = parse_cable(proposed_section)
        unit_weight = p.get("linear_weight_kg_m", 1.2) if p else 1.2
        total_weight = round(unit_weight * proposed_length, 2) if proposed_length else 0.0

        item_proposed = {
            "tag": tag,
            "description": f"CÂBLE {proposed_section}".upper(),
            "category": "CARNET_DE_CABLES",
            "discipline": "ELEC",
            "quantity": proposed_length,
            "unit": "m",
            "cable_section": proposed_section,
            "unit_weight": unit_weight,
            "total_weight": total_weight,
            "status": "PROPOSED_TRIANGULATION",
            "source": "TRIANGULATION_VALIDEE",
            "provenance": "TRIANGULATION_ENGINE",
            "notes": comment,
            "discrepancy_id": disc_id,
        }

        # Vue comparative 3 colonnes
        cad_view = {
            "length_m": cad_f.get("length_m") or cad_f.get("cable_len_m") if cad_f else None,
            "section": cad_f.get("cable_section") if cad_f else None,
            "status": cad_f.get("status", "NOT_FOUND") if cad_f else "NON_LOCALISE",
            "routing_path": cad_f.get("routing_path") if cad_f else None,
        }

        cs_view = {
            "declared_length_m": cs_f.get("declared_length_m") if cs_f else None,
            "declared_section": cs_f.get("declared_section") if cs_f else None,
            "cable_type": cs_f.get("cable_type") if cs_f else None,
            "source": cs_f.get("source") if cs_f else None,
            "destination": cs_f.get("destination") if cs_f else None,
        }

        cn_view = {
            "calc_length_m": cn_f.get("calc_length_m") if cn_f else None,
            "calc_section": cn_f.get("calc_section") if cn_f else None,
            "calc_du_pct": cn_f.get("calc_du_pct") if cn_f else None,
            "ib_a": cn_f.get("ib_a") if cn_f else None,
            "in_rating_a": cn_f.get("in_rating_a") if cn_f else None,
            "cable_type": cn_f.get("cable_type") if cn_f else None,
        }

        return {
            "discrepancy_id": disc_id,
            "tag": tag,
            "category": category,
            "severity": severity,
            "title": title,
            "analysis_comment": comment,
            "cad_view": cad_view,
            "cs_view": cs_view,
            "cn_view": cn_view,
            "proposed_resolution": {
                "action": proposed_action,
                "section": proposed_section,
                "length_m": proposed_length,
                "unit_weight_kg_m": unit_weight,
                "total_weight_kg": total_weight,
            },
            "item_proposed": item_proposed,
            "status": "PENDING_REVIEW",  # PENDING_REVIEW, VALIDATED, IGNORED
            "expert_notes": "",
        }
