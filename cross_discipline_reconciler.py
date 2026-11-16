# -*- coding: utf-8 -*-
"""
cross_discipline_reconciler.py  (version corrigée – audit ARKAN v3, lot 2)

Recoupement triangulaire P&ID / isométriques / SLD / cheminements / carnet de câbles.

Corrections :
  * plus AUCUNE donnée P&ID de démonstration : sans P&ID fourni, les contrôles concernés sont
    « NON ÉVALUÉS » (anomalie INFO), jamais « conformes » ni « en défaut » ;
  * les 7 contrôles sont codés (le code ne faisait que CROSS_01, 02 et 05) + le sens inverse de CROSS_02 ;
  * l'appariement des tags passe par TagNormalizer corrigé (unité, suffixe A/B, pas de fuzzy sur numéros) ;
    un appariement incertain (score < 0.95) est signalé INFO ;
  * sévérités CRITICAL | WARNING | INFO ; chaque anomalie porte `rule` ET `check_id` (matrice Excel) ;
  * `self.coverage` indique pour chaque contrôle s'il a été évalué.
"""
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from cable_parser import parse_cable
from ie_mto_validator import check_tray_filling
from tag_normalizer import TagNormalizer

logger = logging.getLogger("arkan.cross_reconciler")

MOTOR_TYPES = {"PUMP", "COMPRESSOR", "MOTOR", "FAN", "BLOWER", "AGITATOR"}
MOTOR_TAG_LETTERS = {"P", "C", "K", "M", "FAN", "AG"}
METALLIC_TYPES = MOTOR_TYPES | {"VESSEL", "TANK", "COLUMN", "EXCHANGER", "STRUCTURE", "SKID", "FILTER", "REACTOR"}
VALVE_ITEM_CATEGORIES = {"VALVE", "ROBINETTERIE", "CONTROL_VALVE", "SAFETY_VALVE"}
PANEL_TYPES = {"PANEL", "TABLEAU", "SUBPANEL", "COFFRET", "ARMOIRE"}
CONFIDENT = 0.95


def _a(check, severity, tag, title, message, norm, reco, status="PROPOSED", **extra):
    d = {"rule": check, "check_id": check, "severity": severity, "tag": tag, "title": title,
         "message": message, "norm_source": norm, "recommendation": reco, "status": status}
    d.update(extra)
    return d


class CrossDisciplineReconciler:
    def __init__(self, config: Optional[Dict[str, Any]] = None, normalizer: Optional[TagNormalizer] = None):
        if config is None:
            try:
                from config_loader import load_project_config
                config = load_project_config()
            except Exception as exc:
                if exc.__class__.__name__ == "ConfigError":
                    raise
                config = {}
        self.cfg = config or {}
        self.rules = self.cfg.get("normative_rules") or {}
        self.tn = normalizer or TagNormalizer(self.cfg)
        self.coverage: Dict[str, str] = {}

    # ------------------------------------------------------------------ utilitaires
    def _match(self, tag: Any, candidates: List[Dict[str, Any]], key: str = "tag") -> Tuple[Optional[Dict[str, Any]], float, str]:
        best, best_s, best_k = None, 0.0, "NO_MATCH"
        for c in candidates:
            ok, score, kind = self.tn.match_tags(tag, c.get(key, ""))
            if ok and score > best_s:
                best, best_s, best_k = c, score, kind
        return best, best_s, best_k

    def _not_evaluated(self, out: List[Dict[str, Any]], check: str, title: str, why: str, reco: str) -> None:
        self.coverage[check] = "NOT_EVALUATED"
        out.append(_a(f"{check}_NOT_EVALUATED", "INFO", "—", title, why, "Spécification projet", reco, status="NOT_EVALUATED"))

    # ------------------------------------------------------------------ point d'entrée
    def reconcile_all(
        self,
        piping_items: Optional[List[Dict[str, Any]]] = None,
        sld_feeders: Optional[List[Dict[str, Any]]] = None,
        routing_items: Optional[List[Dict[str, Any]]] = None,
        earthing_items: Optional[List[Dict[str, Any]]] = None,
        pid_equipment: Optional[List[Dict[str, Any]]] = None,
        cable_list: Optional[List[Dict[str, Any]]] = None,
        panels: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        self.coverage = {}
        out: List[Dict[str, Any]] = []
        self._cross_01(out, piping_items, pid_equipment)
        self._cross_02(out, sld_feeders, pid_equipment)
        self._cross_03(out, sld_feeders, cable_list)
        self._cross_04(out, routing_items, cable_list)
        self._cross_05(out, earthing_items, pid_equipment)
        self._cross_06(out, routing_items, cable_list)
        self._cross_07(out, sld_feeders, panels, pid_equipment)
        return out

    # ------------------------------------------------------------------ CROSS_01 P&ID vs ISO (vannes)
    def _cross_01(self, out, piping_items, pid):
        pid_valves = [e for e in (pid or []) if "VALVE" in str(e.get("type", "")).upper()]
        iso_valves = [p for p in (piping_items or []) if str(p.get("category") or "").upper() in VALVE_ITEM_CATEGORIES and p.get("tag")]
        if not pid_valves or not piping_items:
            return self._not_evaluated(out, "CROSS_01", "P&ID vs isométriques non évalué",
                                       "P&ID (vannes) ou isométriques non fournis.", "Fournir la liste des vannes du P&ID et le MTO isométrique.")
        if not iso_valves:
            return self._not_evaluated(out, "CROSS_01", "P&ID vs isométriques non évalué",
                                       "Aucune vanne repérée (tag) dans les isométriques : le MTO tuyauterie ne porte pas les tags.",
                                       "Renseigner les tags de vannes dans le MTO tuyauterie.")
        self.coverage["CROSS_01"] = "EVALUATED"
        for v in pid_valves:
            hit, score, kind = self._match(v.get("tag"), iso_valves)
            if hit is None:
                out.append(_a("CROSS_01_PID_ISO_VALVE", "CRITICAL", v.get("tag"),
                              f"Vanne {v.get('tag')} présente sur P&ID mais absente de l'isométrique",
                              "Aucun tag équivalent dans les isométriques (suffixes A/B et unités comparés).",
                              "Cohérence P&ID / isométrique", "Insérer la vanne (corps, brides, joints) dans la nomenclature isométrique."))
            elif score < CONFIDENT:
                out.append(_a("CROSS_01_UNCERTAIN_MATCH", "INFO", v.get("tag"), f"Appariement incertain de {v.get('tag')}",
                              f"Rapproché de « {hit.get('tag')} » ({kind}, score {score:.2f}).", "Cohérence P&ID / isométrique",
                              "Confirmer l'équivalence des tags.", status="TO_CHECK"))

    # ------------------------------------------------------------------ CROSS_02 moteurs vs départs (+ sens inverse)
    def _cross_02(self, out, feeders, pid):
        motors = [e for e in (pid or []) if str(e.get("type", "")).upper() in MOTOR_TYPES]
        if not motors or not feeders:
            return self._not_evaluated(out, "CROSS_02", "Moteurs P&ID vs départs TGBT non évalué",
                                       "Liste des moteurs du P&ID ou départs du SLD non fournis.",
                                       "Fournir le P&ID (moteurs) et extraire le SLD.")
        self.coverage["CROSS_02"] = "EVALUATED"
        for m in motors:
            hit, score, kind = self._match(m.get("tag"), feeders)
            if hit is None:
                out.append(_a("CROSS_02_MOTOR_NO_FEEDER", "CRITICAL", m.get("tag"),
                              f"Moteur {m.get('tag')} sans départ identifié sur le TGBT",
                              f"{m.get('description') or m.get('type')}"
                              + (f", {m.get('power_kw')} kW" if m.get("power_kw") else ""),
                              "Cohérence P&ID / SLD", f"Prévoir un départ protégé pour {m.get('tag')}."))
            elif score < CONFIDENT:
                out.append(_a("CROSS_02_UNCERTAIN_MATCH", "INFO", m.get("tag"), f"Appariement incertain de {m.get('tag')}",
                              f"Rapproché du départ « {hit.get('tag')} » ({kind}, score {score:.2f}).", "Cohérence P&ID / SLD",
                              "Confirmer l'équivalence des tags.", status="TO_CHECK"))
        for f in feeders:                                            # sens inverse : départ sans équipement
            d = self.tn.decompose_tag(f.get("tag", ""))
            if d["structured"] and d["type"] in MOTOR_TAG_LETTERS and self._match(f.get("tag"), motors)[0] is None:
                out.append(_a("CROSS_02_FEEDER_NO_MOTOR", "WARNING", f.get("tag"),
                              f"Départ {f.get('tag')} sans moteur correspondant au P&ID",
                              "Équipement non listé au P&ID, réserve, ou tag différent.", "Cohérence P&ID / SLD",
                              "Vérifier l'existence de l'équipement ou classer le départ en réserve."))

    # ------------------------------------------------------------------ CROSS_03 SLD vs carnet de câbles
    def _cross_03(self, out, feeders, cable_list):
        feeders = [f for f in (feeders or []) if f.get("cable_section")]
        if not feeders or not cable_list:
            return self._not_evaluated(out, "CROSS_03", "SLD vs carnet de câbles non évalué",
                                       "Départs SLD (avec section) ou carnet de câbles non fournis.", "Fournir le carnet de câbles.")
        self.coverage["CROSS_03"] = "EVALUATED"
        used = set()
        for f in feeders:
            hit, score, kind = self._match(f.get("tag"), cable_list)
            if hit is None:
                out.append(_a("CROSS_03_FEEDER_NOT_IN_CABLE_LIST", "WARNING", f.get("tag"),
                              f"Départ {f.get('tag')} absent du carnet de câbles", "Aucune liaison correspondante.",
                              "Cohérence SLD / carnet", "Ajouter la liaison au carnet."))
                continue
            used.add(id(hit))
            a, b = parse_cable(f.get("cable_section")), parse_cable(hit.get("section") or hit.get("cable_section"))
            if a and b and (a.get("family"), a.get("n_conductors"), a.get("section_mm2"), a.get("reduced_section_mm2")) != \
                    (b.get("family"), b.get("n_conductors"), b.get("section_mm2"), b.get("reduced_section_mm2")):
                out.append(_a("CROSS_03_SECTION_MISMATCH", "CRITICAL", f.get("tag"),
                              f"Section différente entre SLD et carnet sur {f.get('tag')}",
                              f"SLD : {f.get('cable_section')} ; carnet : {hit.get('section') or hit.get('cable_section')}.",
                              "Cohérence SLD / carnet", "Aligner le carnet et le SLD (vérifier In et Iz)."))
            elif score < CONFIDENT:
                out.append(_a("CROSS_03_UNCERTAIN_MATCH", "INFO", f.get("tag"), f"Appariement incertain de {f.get('tag')}",
                              f"Rapproché de « {hit.get('tag')} » ({kind}, score {score:.2f}).", "Cohérence SLD / carnet",
                              "Confirmer l'équivalence des tags.", status="TO_CHECK"))
        for c in cable_list:
            if id(c) not in used and self._match(c.get("tag"), feeders)[0] is None:
                out.append(_a("CROSS_03_CABLE_NOT_IN_SLD", "WARNING", c.get("tag"),
                              f"Liaison {c.get('tag')} du carnet sans départ au SLD", "Câble tiré sans départ identifié.",
                              "Cohérence SLD / carnet", "Vérifier l'existence du départ."))

    # ------------------------------------------------------------------ CROSS_04 câbles vs capacité des chemins
    def _cross_04(self, out, routing_items, cable_list):
        trays = [t for t in (routing_items or []) if t.get("category") == "CABLE_TRAY"]
        cables = [dict(c, category="CABLE") for c in (cable_list or [])]
        if not trays or not cables:
            return self._not_evaluated(out, "CROSS_04", "Câbles vs capacité des chemins non évalué",
                                       "Chemins (route_id, dimension) ou carnet de câbles non fournis.",
                                       "Fournir le parcours de chaque câble et les chemins mesurés.")
        found = check_tray_filling(trays + cables, self.rules)
        if found and found[0]["status"] == "NOT_EVALUATED":
            return self._not_evaluated(out, "CROSS_04", "Câbles vs capacité des chemins non évalué", found[0]["message"],
                                       "Fournir route_id et outer_diameter_mm par câble, et le seuil de remplissage en config.")
        self.coverage["CROSS_04"] = "EVALUATED"
        for a in found:
            a["check_id"] = "CROSS_04"
            out.append(a)

    # ------------------------------------------------------------------ CROSS_05 équipements vs terre
    def _cross_05(self, out, earthing_items, pid):
        if earthing_items is None:
            return self._not_evaluated(out, "CROSS_05", "Équipements vs réseau de terre non évalué",
                                       "Plan de mise à la terre non fourni.", "Extraire le plan MALT.")
        self.coverage["CROSS_05"] = "EVALUATED"
        length = sum(float(e.get("quantity") or 0.0) for e in earthing_items
                     if e.get("category") == "EARTHING" and str(e.get("unit", "m")).lower() == "m")
        if length <= 0:
            out.append(_a("CROSS_05_MISSING_EARTHING_NETWORK", "CRITICAL", "MALT-GENERAL",
                          "Aucun linéaire de réseau de terre sur le plan fourni",
                          "Aucun câble de terre n'a été mesuré (calques MALT/TERRE/EARTH vides ou non reconnus).",
                          "IEC 60364-5-54", "Vérifier les noms de calques (ie_extraction.layers.earthing) ou budgétiser la boucle de terre.",
                          item_proposed={"category": "EARTHING", "description": "Câble cuivre nu 50 mm² pour boucle générale de terre",
                                         "size": "50 mm2", "quantity": 100.0, "unit": "m", "weight_unit": 0.448, "weight_total": 44.8}))
        equipment = [e for e in (pid or []) if str(e.get("type", "")).upper() in METALLIC_TYPES]
        connected = {t for e in earthing_items for t in (e.get("connected_tags") or [])}
        if equipment and not connected:
            out.append(_a("CROSS_05_CONNECTIONS_NOT_EVALUATED", "INFO", "MALT", "Raccordement par équipement non évalué",
                          "Le plan ne fournit pas de liste d'équipements raccordés (connected_tags).", "IEC 60364-5-54",
                          "Fournir les raccordements (blocs de terre associés aux équipements).", status="NOT_EVALUATED"))
        elif equipment:
            pool = [{"tag": t} for t in connected]
            for e in equipment:
                if self._match(e.get("tag"), pool)[0] is None:
                    out.append(_a("CROSS_05_EQUIPMENT_NOT_EARTHED", "WARNING", e.get("tag"),
                                  f"{e.get('tag')} sans raccordement à la boucle de terre",
                                  "Équipement métallique absent des raccordements de terre.", "IEC 60364-5-54",
                                  "Prévoir la descente de terre et le raccordement."))

    # ------------------------------------------------------------------ CROSS_06 tranchées vs fourreaux
    def _cross_06(self, out, routing_items, cable_list):
        r = self.rules.get("ducts_conduits") or {}
        lim = {1: r.get("max_filling_ratio_1cable"), 2: r.get("max_filling_ratio_2cables"),
               3: r.get("max_filling_ratio_3cables_or_more")}
        ducts = [d for d in (routing_items or []) if d.get("category") == "CONDUIT" and d.get("duct_id") and d.get("inner_diameter_mm")]
        cables = [c for c in (cable_list or []) if c.get("duct_id") and c.get("outer_diameter_mm")]
        if not ducts or not cables or any(v is None for v in lim.values()):
            why = []
            if not ducts:
                why.append("fourreaux sans duct_id / inner_diameter_mm")
            if not cables:
                why.append("câbles sans duct_id / outer_diameter_mm")
            if any(v is None for v in lim.values()):
                why.append("ratios normative_rules.ducts_conduits non configurés")
            return self._not_evaluated(out, "CROSS_06", "Tranchées vs fourreaux non évalué", " ; ".join(why) + ".",
                                       "Renseigner le diamètre intérieur des fourreaux, le fourreau de chaque câble et les ratios en config.")
        self.coverage["CROSS_06"] = "EVALUATED"
        for d in ducts:
            inside = [c for c in cables if c["duct_id"] == d["duct_id"]]
            n_cables = sum(int(c.get("count", 1) or 1) for c in inside)
            if not n_cables:
                continue
            tubes = int(d.get("nb_tubes") or 1)
            per_tube = math.ceil(n_cables / tubes)
            limit = float(lim[1 if per_tube == 1 else 2 if per_tube == 2 else 3])
            area = sum(math.pi / 4 * float(c["outer_diameter_mm"]) ** 2 * int(c.get("count", 1) or 1) for c in inside)
            cap = tubes * math.pi / 4 * float(d["inner_diameter_mm"]) ** 2
            if area / cap > limit:
                out.append(_a("CROSS_06_DUCT_OVERFILL", "CRITICAL", d.get("tag") or d["duct_id"],
                              f"Fourreau {d['duct_id']} : remplissage {area / cap:.0%} > {limit:.0%}",
                              f"{n_cables} câble(s) dans {tubes} tube(s) Ø int. {d['inner_diameter_mm']} mm.",
                              "Spécification projet", "Ajouter un tube ou répartir les câbles."))

    # ------------------------------------------------------------------ CROSS_07 sous-tableaux vs TGBT
    def _cross_07(self, out, feeders, panels, pid):
        pans = list(panels or []) + [e for e in (pid or []) if str(e.get("type", "")).upper() in PANEL_TYPES]
        if not pans or not feeders:
            return self._not_evaluated(out, "CROSS_07", "Sous-tableaux vs TGBT non évalué",
                                       "Liste des coffrets/armoires ou départs du SLD non fournis.", "Fournir la liste des tableaux divisionnaires.")
        self.coverage["CROSS_07"] = "EVALUATED"
        for p in pans:
            hit, score, kind = self._match(p.get("tag"), feeders)
            if hit is None:
                out.append(_a("CROSS_07_PANEL_NO_HEAD_BREAKER", "CRITICAL", p.get("tag"),
                              f"Tableau {p.get('tag')} sans disjoncteur de tête au TGBT",
                              "Aucun départ du SLD n'alimente ce tableau.", "Cohérence SLD / tableaux",
                              f"Prévoir un départ protégé pour {p.get('tag')}."))
            elif score < CONFIDENT:
                out.append(_a("CROSS_07_UNCERTAIN_MATCH", "INFO", p.get("tag"), f"Appariement incertain de {p.get('tag')}",
                              f"Rapproché de « {hit.get('tag')} » ({kind}, score {score:.2f}).", "Cohérence SLD / tableaux",
                              "Confirmer l'équivalence des tags.", status="TO_CHECK"))
        return out


def run_cross_discipline_reconciliation(
    piping_items: Optional[List[Dict[str, Any]]] = None,
    sld_feeders: Optional[List[Dict[str, Any]]] = None,
    routing_items: Optional[List[Dict[str, Any]]] = None,
    earthing_items: Optional[List[Dict[str, Any]]] = None,
    pid_equipment: Optional[List[Dict[str, Any]]] = None,
    cable_list: Optional[List[Dict[str, Any]]] = None,
    panels: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    normalizer: Optional[TagNormalizer] = None
) -> List[Dict[str, Any]]:
    """Fonction passerelle universelle exécutant l'ensemble des 7 contrôles croisés inter-disciplines."""
    rec = CrossDisciplineReconciler(config=config, normalizer=normalizer)
    return rec.reconcile_all(
        piping_items=piping_items,
        sld_feeders=sld_feeders,
        routing_items=routing_items,
        earthing_items=earthing_items,
        pid_equipment=pid_equipment,
        cable_list=cable_list,
        panels=panels
    )
