# -*- coding: utf-8 -*-
"""
ie_mto_validator.py  (version corrigée – audit ARKAN v3)

Principes :
  * aucune règle n'invente de donnée : sans table / seuil / donnée d'entrée, la règle renvoie une
    anomalie INFO « non évaluée » (une seule par règle) au lieu d'un résultat plausible ;
  * sévérités : CRITICAL | WARNING | INFO uniquement ;
  * seuils et tables lus dans la config (normative_rules.*), pas codés en dur ;
  * les articles proposés restent des PROPOSITIONS (jamais injectés dans le MTO).

Règles :
  MALT_01   Section PE (IEC 60364-5-54, tableau 54.2) — cartographie phase -> PE, N/PE distingués.
  CHEMIN_01 Taux de remplissage = Σ(π/4·d²) / (L×H) par parcours — exige route_id + diamètres extérieurs.
  PUISSANCE_01 In <= Iz (et In >= Ib si Ib connu) — exige une table Iz dans la config.
  CABLE_00  Désignation de câble illisible.
"""
import logging
import math
import re
from typing import Any, Dict, List, Optional

from cable_parser import parse_cable

logger = logging.getLogger("arkan.ie_validator")

DEFAULT_STANDARD_SECTIONS_MM2 = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300, 400]


def _cfg(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if config is not None:
        return config
    try:
        from config_loader import load_project_config
        return load_project_config()
    except Exception as exc:                       # config illisible : on valide avec les défauts normatifs
        logger.warning("Config indisponible pour le validateur : %s", exc)
        return {}


def get_next_standard_section(sec: float, sections: Optional[List[float]] = None) -> Optional[float]:
    for s in sections or DEFAULT_STANDARD_SECTIONS_MM2:
        if s >= sec - 0.05:
            return float(s)
    return None                                     # au-delà de la table : à traiter, pas d'invention


def calculate_iec_pe_section(phase_section: float, rules: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """IEC 60364-5-54 tableau 54.2 : S<=16 -> S ; 16<S<=35 -> 16 ; S>35 -> S/2 arrondi à la section normalisée supérieure."""
    r = rules or {}
    t1, t2 = float(r.get("tier1_max_phase_mm2", 16.0)), float(r.get("tier2_max_phase_mm2", 35.0))
    fixed, factor = float(r.get("tier2_pe_fixed_mm2", 16.0)), float(r.get("tier3_factor", 0.5))
    if phase_section <= t1:
        return phase_section
    if phase_section <= t2:
        return fixed
    return get_next_standard_section(phase_section * factor, r.get("standard_sections_mm2"))


def _anomaly(rule, severity, tag, title, message, norm, reco, status="PROPOSED", **extra):
    a = {"rule": rule, "severity": severity, "tag": tag, "title": title, "message": message,
         "norm_source": norm, "recommendation": reco, "status": status}
    a.update(extra)
    return a


def _fmt(x: float) -> str:
    return f"{x:g}"


def check_tray_filling(items: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Taux de remplissage par parcours = Σ(π/4·d²·count) / (L×H).
    Exige : chemins avec `route_id` + `size` ("300x50"), câbles avec `route_id` + `outer_diameter_mm`,
    et le seuil normative_rules.cable_trays.max_filling_ratio. Sinon : UNE anomalie INFO « non évaluée ».
    """
    out: List[Dict[str, Any]] = []
    ct = (rules or {}).get("cable_trays") or {}
    max_fill = ct.get("max_filling_ratio")
    trays = [t for t in items if t.get("category") == "CABLE_TRAY"]
    power_cables = [c for c in items if c.get("category") == "CABLE"]
    have_data = bool(trays and power_cables and any(c.get("route_id") and c.get("outer_diameter_mm") for c in power_cables)
                     and any(t.get("route_id") for t in trays))
    if max_fill is None or not have_data:
        why = []
        if max_fill is None:
            why.append("seuil normative_rules.cable_trays.max_filling_ratio non configuré")
        if not have_data:
            why.append("routage (route_id) et diamètres extérieurs (outer_diameter_mm) des câbles non disponibles")
        if trays:
            out.append(_anomaly("CHEMIN_01_FILLING_NOT_EVALUATED", "INFO", trays[0].get("tag", "CDC"),
                "Taux de remplissage des chemins non évalué", " ; ".join(why) + ".", "Spécification projet",
                "Fournir le parcours de chaque câble et son diamètre extérieur.", status="NOT_EVALUATED"))
        return out
    for t in trays:
        m = re.match(r"^\s*(\d+)\s*[Xx*]\s*(\d+)", str(t.get("size") or ""))
        rid = t.get("route_id")
        if not (m and rid):
            continue
        w, h = float(m.group(1)), float(m.group(2))
        area = sum(math.pi / 4.0 * float(c["outer_diameter_mm"]) ** 2 * float(c.get("count", 1) or 1)
                   for c in power_cables if c.get("route_id") == rid and c.get("outer_diameter_mm"))
        ratio = area / (w * h)
        if ratio > float(max_fill):
            out.append(_anomaly("CHEMIN_01_OCCUPATION", "CRITICAL", t.get("tag", "CDC"),
                f"Remplissage {ratio:.0%} > {float(max_fill):.0%} sur le parcours {rid}",
                f"Σ(π/4·d²) = {area:.0f} mm² pour une section {w:g}×{h:g} mm.", "Spécification projet",
                "Augmenter la largeur du chemin ou répartir les câbles sur un second chemin."))
    return out


def validate_ie_mto(items: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None,
                    config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = _cfg(config)
    rules = cfg.get("normative_rules") or {}
    anomalies: List[Dict[str, Any]] = []

    cables = [it for it in items if it.get("category") in ("CABLE", "SWITCHGEAR_FEEDER")
              and (it.get("cable_section") or it.get("size"))]

    # ───────── MALT_01 : conducteur de protection ─────────
    pe_rules = rules.get("earthing_pe") or {}
    for c in cables:
        spec_raw = c.get("cable_section") or c.get("size")
        parsed = parse_cable(spec_raw)
        tag = c.get("tag", "CABLE")
        if parsed is None:
            if str(spec_raw).upper().strip() not in ("CANALISATION",):
                anomalies.append(_anomaly("CABLE_00_UNPARSED", "WARNING", tag,
                    f"Désignation de câble illisible sur {tag}", f"« {spec_raw} » n'est pas reconnue : section non vérifiée.",
                    "CEI 60502-1", "Corriger la désignation (ex. 3X120+70, 4G25, 12P0.75).", status="TO_CHECK"))
            continue
        if parsed["family"] != "POWER":
            continue
        s_ph = parsed["section_mm2"]
        s_req = calculate_iec_pe_section(s_ph, pe_rules)
        if s_req is None:
            anomalies.append(_anomaly("MALT_01_PE_SECTION", "WARNING", tag, f"Section PE non déterminable sur {tag}",
                f"Phase {_fmt(s_ph)} mm² au-delà de la table de sections configurée.", "IEC 60364-5-54 Tableau 54.2",
                "Compléter standard_sections_mm2 dans la config.", status="TO_CHECK"))
            continue
        if parsed["has_pe_core"]:
            continue                                # âme PE de même section que les phases : conforme
        r_sec, role = parsed["reduced_section_mm2"], parsed["reduced_role"]
        if r_sec is None:
            continue                                # pas de PE dans le câble : PE séparé, hors périmètre de cette ligne
        if role == "N":
            continue                                # neutre : le PE est tiré à part, vérifié par ailleurs
        if r_sec < s_req - 0.1:
            explicit = role == "PE"
            anomalies.append(_anomaly(
                "MALT_01_PE_SECTION", "CRITICAL" if explicit else "WARNING", tag,
                f"Section PE {'non conforme' if explicit else 'possiblement non conforme'} sur {tag}",
                f"Phase {_fmt(s_ph)} mm², conducteur réduit {_fmt(r_sec)} mm² "
                f"({'PE explicite' if explicit else 'rôle N ou PE non précisé'}) ; la norme impose PE ≥ {_fmt(s_req)} mm².",
                "IEC 60364-5-54 Tableau 54.2",
                f"Utiliser PE ≥ {_fmt(s_req)} mm²" + ("" if explicit else " si ce conducteur est le PE ; sinon tirer un PE séparé."),
                item_proposed={"category": "CABLE", "tag": f"{tag}-PE-CORR",
                               "description": f"Câble {_fmt(parsed['n_conductors'])}X{_fmt(s_ph)}+PE{_fmt(s_req)} mm² (proposition)",
                               "size": f"{parsed['n_conductors']}X{_fmt(s_ph)}+PE{_fmt(s_req)}", "unit": "m",
                               "quantity": c.get("quantity"), "proposed_only": True}))
        elif role == "UNSPECIFIED" and r_sec >= s_req - 0.1:
            pass                                    # réduit >= requis : conforme quel que soit son rôle

    # ───────── CHEMIN_01 : remplissage ─────────
    anomalies.extend(check_tray_filling(items, rules))

    # ───────── PUISSANCE_01 : In <= Iz, In >= Ib ─────────
    iz_table = (rules.get("current_capacity") or {}).get("iz_by_method")        # {méthode: {section: A}}
    sizing = [c for c in cables if c.get("calibre_a")]
    if sizing and not iz_table:
        anomalies.append(_anomaly("PUISSANCE_01_NOT_EVALUATED", "INFO", sizing[0].get("tag", "DISJ"),
            "Adéquation In / Iz non évaluée",
            "Aucune table Iz (normative_rules.current_capacity.iz_by_method) : Iz dépend du mode de pose, de l'isolant, "
            "de la température et du groupement ; aucune valeur n'est supposée.", "IEC 60364-5-52",
            "Renseigner la table Iz du projet (issue de la norme) et, par câble, installation_method et derating_factor.",
            status="NOT_EVALUATED"))
    elif sizing:
        for c in sizing:
            p = parse_cable(c.get("cable_section") or c.get("size"))
            method = str(c.get("installation_method") or "")
            row = (iz_table.get(method) or {}) if method else {}
            if not p or p["family"] != "POWER" or f"{p['section_mm2']:g}" not in {f"{float(k):g}" for k in row}:
                anomalies.append(_anomaly("PUISSANCE_01_NOT_EVALUATED", "INFO", c.get("tag", "DISJ"),
                    f"Iz non évaluée sur {c.get('tag')}", "Mode de pose ou section absents de la table Iz.", "IEC 60364-5-52",
                    "Préciser installation_method et compléter la table.", status="NOT_EVALUATED"))
                continue
            iz0 = next(float(v) for k, v in row.items() if f"{float(k):g}" == f"{p['section_mm2']:g}")
            k_tot = float(c.get("derating_factor") or 1.0)
            iz = iz0 * k_tot * max(1, p["parallel_runs"])
            in_a = float(c["calibre_a"])
            if in_a > iz:
                anomalies.append(_anomaly("PUISSANCE_01_OVERCURRENT", "CRITICAL", c.get("tag", "DISJ"),
                    f"In={in_a:g} A > Iz={iz:.0f} A sur {c.get('tag')}",
                    f"Iz = {iz0:g} A × k {k_tot:g}. (Ib ≤ In ≤ Iz suffit si le dispositif assure I2 ≤ 1,45·In.)",
                    "IEC 60364-5-52 / 60364-4-43", "Augmenter la section ou réduire In."))
            ib = c.get("ib_a")
            if ib and in_a < float(ib):
                anomalies.append(_anomaly("PUISSANCE_01_UNDERSIZED", "CRITICAL", c.get("tag", "DISJ"),
                    f"In={in_a:g} A < Ib={float(ib):g} A sur {c.get('tag')}", "Le calibre ne couvre pas le courant d'emploi.",
                    "IEC 60364-4-43", "Augmenter le calibre."))
    return anomalies
