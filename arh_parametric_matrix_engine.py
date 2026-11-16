"""
arh_parametric_matrix_engine.py  —  v3.0
========================================
Principes :
  * AUCUNE valeur par défaut numérique. Donnée absente / ambiguë / hors table => « À VÉRIFIER ».
  * Trois états (CONFORME / NON CONFORME / À VÉRIFIER) + NON APPLICABLE.
  * Règles réglementaires dans arh_standards.yaml (obligatoire, sinon erreur franche).
    Chaque rapport porte la version + le sha256 du YAML et la liste des règles non vérifiées.
  * Unités normalisées avant toute comparaison ; virgule décimale française gérée.
  * Rôle d'une valeur (plan / calcul / PV) = pièce [DOC-xx] déduite de la page, jamais déduit du nom de fichier.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import json
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

OK, KO, TBC, NA = "CONFORME", "NON CONFORME", "À VÉRIFIER", "NON APPLICABLE"
REQUIRED_SECTIONS = ("meta", "hydrotest", "flange_ratings", "metallurgy", "concordance")


class StandardsError(RuntimeError):
    """Fichier de règles absent, illisible ou incomplet : l'audit ne doit PAS tourner."""


def load_standards(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise StandardsError(f"Fichier de règles introuvable : {path}")
    raw = p.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise StandardsError(f"YAML invalide : {e}") from e
    if not isinstance(data, dict):
        raise StandardsError("YAML vide ou de structure inattendue")
    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise StandardsError(f"Sections manquantes dans le YAML : {missing}")
    data["_sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def combine(statuses: List[str]) -> str:
    s = [x for x in statuses if x != NA]
    if not s:
        return NA
    if KO in s:
        return KO
    if TBC in s:
        return TBC
    return OK


def _res(flag: Optional[bool], verdict: str, **extra) -> Dict[str, Any]:
    status = OK if flag is True else KO if flag is False else TBC
    return {"status": status, "is_compliant": flag, "verdict": verdict, **extra}


# ───────────────────────── Parseurs unité-aware ─────────────────────────
_TO_BAR = {"bar": 1.0, "barg": 1.0, "mpa": 10.0, "kpa": 0.01, "psi": 0.0689476, "psig": 0.0689476}
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]")
_NUM = r"(-?\d+(?:[.,]\d+)?)"


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def parse_pressure_bar(text: Any) -> Optional[float]:
    """Exige une unité explicite : sans unité => None (on ne devine pas)."""
    m = re.search(_NUM + r"\s*(barg|bar|mpa|kpa|psig|psi)\b", str(text), re.I)
    return round(_f(m.group(1)) * _TO_BAR[m.group(2).lower()], 4) if m else None


def parse_temperature_c(text: Any) -> Optional[float]:
    m = re.search(_NUM + r"\s*(?:°|º|deg)?\s*C\b", str(text))
    return _f(m.group(1)) if m else None


def parse_thickness_mm(text: Any) -> Optional[float]:
    m = re.search(_NUM + r"\s*(mm|inch|in)\b", str(text), re.I)
    if not m:
        return None
    v = _f(m.group(1))
    return round(v * 25.4, 4) if m.group(2).lower() != "mm" else v


def normalize_grade(text: Any) -> Optional[str]:
    s = str(text)
    m = re.search(r"API\s*5L\b.*?\b(X\s*\d{2,3}|B)\b", s, re.I)
    if m:
        return "API5L-" + re.sub(r"\s", "", m.group(1).upper())
    m = re.search(r"\bA\s?(\d{2,4})\b\s*(?:GR(?:ADE)?\.?\s*)?([A-Z0-9]+)?", s, re.I)
    if m:
        return f"A{m.group(1)}" + (f"-{m.group(2).upper()}" if m.group(2) else "")
    return None


def normalize_rating(text: Any) -> Optional[str]:
    s = str(text)
    m = re.search(r"\bPN\s*(\d+)", s, re.I)
    if m:
        return f"PN{m.group(1)}"
    cl = set(re.findall(r"(?<!\d)(150|300|600|900|1500|2500)(?!\d)", s))
    return cl.pop() if len(cl) == 1 else None


def _norm_txt(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def classify_parameter(name: str) -> str:
    n = _norm_txt(name)
    if "rating" in n or "classe" in n:  # avant « pression » : « Classe de Pression » n'est pas une pression
        return "rating"
    if "epreuve" in n or "p_test" in n or "ptest" in n or "hydro" in n:
        return "pressure_test"
    if "pression" in n or "pma" in n:
        return "pressure_design"
    if "temperature" in n or "tma" in n:
        return "temperature"
    if "epaisseur" in n:
        return "thickness"
    if "nuance" in n or "grade" in n:
        return "grade"
    if "rating" in n or "classe" in n:
        return "rating"
    return "other"


_UNITS = {"pressure_design": "bar", "pressure_test": "bar", "temperature": "°C",
          "thickness": "mm", "grade": "Grade", "rating": "ANSI/PN"}
_SRC_RE = re.compile(r"^(?P<file>.*?)\s*\(p\.(?P<page>\d+)\)\s*$")


def parse_source_key(key: str):
    m = _SRC_RE.match(key)
    return (m.group("file"), int(m.group("page"))) if m else (key, None)


def _normalize_value(kind: str, raw: Any):
    s = str(raw).strip()
    if not s or _CJK.search(s):
        return None
    return {"pressure_design": parse_pressure_bar, "pressure_test": parse_pressure_bar,
            "temperature": parse_temperature_c, "thickness": parse_thickness_mm,
            "grade": normalize_grade, "rating": normalize_rating}.get(kind, lambda _: None)(s)


class ARHParametricMatrixEngine:
    def __init__(self, standards_path: Optional[str] = None, db_path: Optional[str] = None):
        self.standards_path = standards_path or os.environ.get(
            "ARH_STANDARDS_PATH", str(Path(__file__).parent / "arh_standards.yaml"))
        self.std = load_standards(self.standards_path)        # lève StandardsError
        self.db_path = db_path or os.environ.get("ARH_DB_PATH")

    @property
    def rules_info(self) -> Dict[str, str]:
        return {"version": str(self.std["meta"].get("version")), "sha256": self.std["_sha256"]}

    def _rule(self, path: List[str], used: List[str]) -> Optional[float]:
        node: Any = self.std
        for k in path:
            if not isinstance(node, dict) or k not in node:
                return None
            node = node[k]
        if not isinstance(node, dict) or node.get("value") is None:
            return None
        if not node.get("verified", False):
            used.append(f"{'.'.join(map(str, path))} = {node['value']} [{node.get('source', 'source ?')}]")
        return float(node["value"])

    # ───────────────────────── A. Épreuve hydrostatique ─────────────────────────
    def compute_hydrotest(self, pma_bar: Optional[float], p_test_bar: Optional[float] = None,
                          equipment_kind: Optional[str] = None, design_code: Optional[str] = None,
                          pipeline_zone: Optional[str] = None, s_test_mpa: Optional[float] = None,
                          s_design_mpa: Optional[float] = None) -> Dict[str, Any]:
        """equipment_kind : pressure_vessel | piping_b31_3 | pipeline | storage_tank (explicite, jamais déduit d'un tag)."""
        used: List[str] = []
        warnings: List[str] = []
        if pma_bar is None or pma_bar <= 0:
            return _res(None, "PMA absente ou invalide : calcul impossible", rules_unverified=used)
        kind = (equipment_kind or "").lower()
        dc = (design_code or "").upper()

        ratio = None
        if s_test_mpa and s_design_mpa and s_design_mpa > 0:
            ratio = s_test_mpa / s_design_mpa
            if ratio < 1:
                warnings.append("Ratio S_test/S_design < 1 : inhabituel, vérifier les contraintes admissibles.")

        decree_req = None
        if kind == "pressure_vessel":
            c = self._rule(["hydrotest", "vessel_decree_21_261"], used)
            decree_req = None if c is None else c * pma_bar
        elif kind == "pipeline":
            z = (pipeline_zone or "").strip().upper()
            if not z:
                return _res(None, "Zone d'emplacement (A/B/C/D) non renseignée : coefficient non déterminé "
                                  "(aucune valeur par défaut).", rules_unverified=used)
            c = self._rule(["hydrotest", "pipeline_zone_decree_21_314", z], used)
            if c is None:
                return _res(None, f"Zone '{z}' inconnue ou règle non définie.", rules_unverified=used)
            decree_req = c * pma_bar
            warnings.append("ASME B31.8 (classe d'emplacement) non modélisé : seul le décret est vérifié.")
        elif kind == "piping_b31_3":
            dc = dc or "B31.3"
        elif kind == "storage_tank":
            return _res(None, "Règle d'épreuve des réservoirs non définie dans le YAML.", rules_unverified=used)
        else:
            return _res(None, "Famille d'équipement non renseignée ou inconnue.", rules_unverified=used)

        code_coef, ratio_unknown = None, False
        if "VIII" in dc:
            code_coef = self._rule(["hydrotest", "asme_viii_div1"], used)
        elif "B31.3" in dc:
            code_coef = self._rule(["hydrotest", "asme_b31_3"], used)
        elif dc:
            warnings.append(f"Code '{design_code}' non modélisé : seul le décret est vérifié.")
        else:
            warnings.append("Code de construction non fourni : seul le décret est vérifié.")
        code_req = None
        if code_coef is not None:
            ratio_unknown = ratio is None
            code_req = code_coef * pma_bar * (ratio if ratio is not None else 1.0)

        reqs = [x for x in (decree_req, code_req) if x is not None]
        if not reqs:
            return _res(None, "Aucune exigence applicable déterminée.", rules_unverified=used, warnings=warnings)
        legal_min = round(max(reqs), 2)
        tol = self._rule(["hydrotest", "test_pressure_tolerance_bar"], used) or 0.0
        dur = self._rule(["hydrotest", "holding_duration_minutes"], used)

        base = {"pma_bar": pma_bar, "actual_test_p_bar": p_test_bar, "legal_minimum_bar": legal_min,
                "required_decree_bar": None if decree_req is None else round(decree_req, 2),
                "required_code_bar": None if code_req is None else round(code_req, 2),
                "stress_ratio": ratio, "holding_duration_minutes": dur,
                "holding_duration_note": None if dur is not None else
                "Durée non fixée par la règle chargée : procédure d'épreuve approuvée par l'ARH.",
                "warnings": warnings, "rules_unverified": used}
        if p_test_bar is None or p_test_bar <= 0:
            return _res(None, f"En attente du PV d'épreuve (minimum requis : {legal_min} bar).", **base)
        margin = round(p_test_bar - legal_min, 2)
        base["margin_bar"] = margin
        if p_test_bar + tol < legal_min - 1e-9:
            return _res(False, f"NON CONFORME — {p_test_bar} bar < {legal_min} bar requis "
                               f"(déficit {abs(margin)} bar).", **base)
        if ratio_unknown and code_coef and pma_bar:
            max_ratio = p_test_bar / (code_coef * pma_bar)
            return _res(None, f"P_test ≥ minimum avec ratio S_test/S_design = 1.0 ; conforme seulement si "
                              f"ratio ≤ {max_ratio:.3f} (ratio non fourni).", **base)
        return _res(True, f"CONFORME — {p_test_bar} bar ≥ {legal_min} bar requis.", **base)

    # ───────────────────────── A-bis. Contrainte admissible réglementaire ─────────
    def compute_allowable_stress(self, re_mpa: Optional[float], rm_mpa: Optional[float],
                                 declared_stress_mpa: Optional[float] = None,
                                 decree: str = "21-261") -> Dict[str, Any]:
        """Vérifie la contrainte admissible selon Décret 21-261 Art. 08 (min(Re/1.5, Rm/2.4)) ou Décret 21-315 Art. 12."""
        used: List[str] = []
        if "21-315" in str(decree):
            if re_mpa is None or re_mpa <= 0:
                return _res(None, "Limite d'élasticité Re absente : calcul Décret 21-315 impossible.")
            factor = self._rule(["allowable_stress", "decree_21_315_art12", "re_factor"], used)
            if factor is None:
                return _res(None, "Facteur Décret 21-315 Art. 12 non défini dans le YAML.", rules_unverified=used)
            s_max = round(factor * re_mpa, 2)
            base = {"re_mpa": re_mpa, "rm_mpa": rm_mpa, "max_allowable_stress_mpa": s_max,
                    "declared_stress_mpa": declared_stress_mpa, "decree": "21-315 Art. 12", "rules_unverified": used}
        else:
            if re_mpa is None or rm_mpa is None or re_mpa <= 0 or rm_mpa <= 0:
                return _res(None, "Re ou Rm absent(e) : calcul Décret 21-261 Art. 08 impossible.")
            re_div = self._rule(["allowable_stress", "decree_21_261_art08", "re_divisor"], used)
            rm_div = self._rule(["allowable_stress", "decree_21_261_art08", "rm_divisor"], used)
            if not re_div or not rm_div:
                return _res(None, "Diviseurs Décret 21-261 Art. 08 non définis dans le YAML.", rules_unverified=used)
            s_max = round(min(re_mpa / re_div, rm_mpa / rm_div), 2)
            base = {"re_mpa": re_mpa, "rm_mpa": rm_mpa, "max_allowable_stress_mpa": s_max,
                    "declared_stress_mpa": declared_stress_mpa, "decree": "21-261 Art. 08", "rules_unverified": used}
        if declared_stress_mpa is None or declared_stress_mpa <= 0:
            return _res(None, f"Contrainte déclarée absente (plafond réglementaire : {s_max} MPa).", **base)
        if declared_stress_mpa <= s_max + 1e-6:
            return _res(True, f"CONFORME — {declared_stress_mpa} MPa ≤ {s_max} MPa.", **base)
        return _res(False, f"NON CONFORME — {declared_stress_mpa} MPa > {s_max} MPa autorisés.", **base)

    # ───────────────────────── B. Rating brides ASME B16.5 / PN ─────────────────────────
    def material_group_from_grade(self, grade: Optional[str]) -> Optional[str]:
        def n(s):
            s = re.sub(r"[^A-Z0-9]", "", str(s).upper())
            return s.replace("GRADE", "").replace("GR", "")
        if not grade:
            return None
        g = n(grade)
        for name, grp in self.std["flange_ratings"]["groups"].items():
            if any(n(m) in g for m in grp.get("materials", [])):
                return name
        return None

    def compute_flange_rating(self, rating_text: Optional[str], pma_bar: Optional[float],
                              tma_c: Optional[float], material_group: Optional[str]) -> Dict[str, Any]:
        if not rating_text or pma_bar is None or tma_c is None:
            return _res(None, "Donnée manquante (rating, PMA ou TMA) : vérification impossible.")
        text = str(rating_text).upper()
        m_pn = re.search(r"\bPN\s*(\d+)", text)
        if m_pn:
            pn = float(m_pn.group(1))
            if pma_bar > pn:
                return _res(False, f"NON CONFORME — PMA {pma_bar} bar > PN {pn:g}.", code_ref="EN 1092-1")
            if tma_c <= 20:
                return _res(True, f"CONFORME — PMA {pma_bar} bar ≤ PN {pn:g} (20 °C).", code_ref="EN 1092-1")
            return _res(None, "PN : au-dessus de 20 °C la tenue dépend du matériau (table EN 1092-1 non chargée).")
        classes = set(re.findall(r"(?<!\d)(150|300|600|900|1500|2500)(?!\d)", text))
        if len(classes) != 1:
            return _res(None, f"Classe de bride non reconnue ou ambiguë dans « {rating_text} ».")
        cl = classes.pop()
        groups = self.std["flange_ratings"]["groups"]
        if not material_group or material_group not in groups:
            return _res(None, f"Groupe de matériau « {material_group} » non disponible : aucune table substituée.")
        used: List[str] = []
        if not groups[material_group].get("verified", False):
            used.append(f"flange_ratings.{material_group} [{groups[material_group].get('source')}]")
        table = groups[material_group]["classes"].get(cl)
        if not table:
            return _res(None, f"Table absente pour la classe {cl}.", rules_unverified=used)
        pts = sorted((float(k), float(v)) for k, v in table.items())
        if tma_c < pts[0][0] or tma_c > pts[-1][0]:
            return _res(None, f"TMA {tma_c} °C hors table ({pts[0][0]:g} à {pts[-1][0]:g} °C) : "
                              f"pas d'extrapolation ni de plafonnement.", rules_unverified=used)
        p_allow = pts[-1][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t0 <= tma_c <= t1:
                p_allow = v0 + (v1 - v0) * (tma_c - t0) / (t1 - t0)
                break
        p_allow = round(p_allow, 2)
        margin = round(p_allow - pma_bar, 2)
        info = dict(rating_class=f"ASME Class {cl}", max_allowable_pressure_bar=p_allow, margin_bar=margin,
                    tma_c=tma_c, pma_bar=pma_bar, rules_unverified=used,
                    code_ref=f"ASME B16.5 Table 2-1.1 ({material_group})")
        if pma_bar <= p_allow:
            return _res(True, f"CONFORME — Class {cl} admet {p_allow} bar à {tma_c} °C.", **info)
        return _res(False, f"NON CONFORME — Class {cl} plafonne à {p_allow} bar à {tma_c} °C (< PMA {pma_bar}).", **info)

    # ───────────────────────── C. Soudabilité & service acide ─────────────────────────
    def compute_weldability(self, comp: Dict[str, Optional[float]],
                            limits_override: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """comp : % massiques. Éléments manquants => À VÉRIFIER (aucune valeur par défaut)."""
        used: List[str] = []
        ov = limits_override or {}
        need = ["C", "Mn", "Cr", "Mo", "V", "Ni", "Cu"]
        missing = [e for e in need if comp.get(e) is None]
        if missing:
            return _res(None, f"Éléments manquants : {missing}.")
        c, mn, cr, mo, v, ni, cu = (comp[e] for e in need)
        iiw = round(c + mn / 6 + (cr + mo + v) / 5 + (ni + cu) / 15, 3)
        c_max = self._rule(["metallurgy", "pcm_applicability_c_max"], used)
        if c_max is None:
            return _res(None, "Seuil de choix de formule non défini.", cev_iiw=iiw)
        warnings: List[str] = []
        if c <= c_max:
            if comp.get("Si") is None:
                return _res(None, "C ≤ seuil : Pcm requis mais Si manquant.", cev_iiw=iiw)
            b_val = comp.get("B")
            if b_val is None:
                b_val = 0.0
                warnings.append("Bore (B) non déclaré : supposé 0.0% pour le calcul Pcm.")
            val = round(c + comp["Si"] / 30 + (mn + cu + cr) / 20 + ni / 60 + mo / 15 + v / 10 + 5 * b_val, 3)
            formula, lim = "Pcm", ov.get("pcm_max", self._rule(["metallurgy", "pcm_max"], used))
        else:
            val, formula, lim = iiw, "CE(IIW)", ov.get("cev_iiw_max", self._rule(["metallurgy", "cev_iiw_max"], used))
        info = dict(formula_used=formula, value=val, cev_iiw=iiw, limit=lim, rules_unverified=used, warnings=warnings)
        if lim is None:
            return _res(None, f"{formula} = {val} mais limite non définie pour cette spécification.", **info)
        if val <= lim:
            return _res(True, f"CONFORME — {formula} {val} ≤ {lim}.", **info)
        return _res(False, f"NON CONFORME — {formula} {val} > {lim} (limite de spécification ; "
                           f"un dépassement impose préchauffage/WPS qualifié, il n'interdit pas le soudage par lui-même).", **info)

    def evaluate_heats(self, heats: List[Dict[str, Any]], limits_override=None) -> Dict[str, Any]:
        """Pire cas sur toutes les coulées du dossier."""
        if not heats:
            return _res(None, "Aucune composition chimique fournie.", heats=[])
        out = [{"heat": h.get("heat"), **self.compute_weldability(h, limits_override)} for h in heats]
        st = combine([r["status"] for r in out])
        return {"status": st, "is_compliant": {OK: True, KO: False}.get(st), "heats": out,
                "verdict": f"Pire cas sur {len(out)} coulée(s) : {st}"}

    def check_sour_service(self, sour_service: Optional[bool], ni_pct: Optional[float],
                           hardness: Optional[float], hardness_unit: str = "HRC") -> Dict[str, Any]:
        """Contrôle ÉLÉMENTAIRE seulement (Ni, dureté) : ne vaut pas conformité NACE/ISO 15156 complète."""
        if sour_service is False:
            return {"status": NA, "is_compliant": None, "verdict": "Service acide non déclaré : non applicable."}
        if sour_service is None:
            return _res(None, "Service acide non précisé dans le dossier.")
        used: List[str] = []
        max_ni = self._rule(["metallurgy", "sour_service", "max_nickel_pct"], used)
        max_hrc = self._rule(["metallurgy", "sour_service", "max_hardness_hrc"], used)
        issues, unknown = [], []
        if ni_pct is None:
            unknown.append("Ni")
        elif max_ni is not None and ni_pct > max_ni:
            issues.append(f"Ni {ni_pct} % > {max_ni} %")
        if hardness is None or hardness_unit.upper() != "HRC":
            unknown.append("dureté (HRC requise ; conversion non faite)")
        elif max_hrc is not None and hardness > max_hrc:
            issues.append(f"Dureté {hardness} HRC > {max_hrc} HRC")
        scope = ("Contrôle élémentaire (Ni, dureté) ; non évalués : dureté ZAT/soudures, traitement thermique, "
                 "conditions du milieu (pH2S, pH, chlorures).")
        if issues:
            return _res(False, "NON CONFORME — " + "; ".join(issues), scope=scope, rules_unverified=used)
        if unknown:
            return _res(None, f"Données manquantes : {unknown}", scope=scope, rules_unverified=used)
        return _res(True, "Seuils élémentaires respectés (ne vaut pas conformité NACE complète).",
                    scope=scope, rules_unverified=used)

    def compute_charpy_resilience(self, energy_avg_j: Optional[float], temp_c: Optional[float],
                                  mdmt_c: Optional[float] = None,
                                  is_high_strength: bool = False) -> Dict[str, Any]:
        """Vérifie la résilience Charpy V-Notch (KV moyen et température d'essai vs MDMT) selon arh_standards.yaml."""
        if energy_avg_j is None or temp_c is None:
            return _res(None, "Énergie Charpy V (J) ou température d'essai (°C) manquante.")
        used: List[str] = []
        rule_key = "high_strength_min_energy_avg_j" if is_high_strength else "min_energy_avg_j"
        min_j = self._rule(["metallurgy", "charpy_v_notch", rule_key], used)
        if min_j is None:
            return _res(None, "Seuil minimal Charpy V non défini dans le référentiel.", rules_unverified=used)
        issues: List[str] = []
        if energy_avg_j < min_j:
            issues.append(f"KV moyen {energy_avg_j} J < {min_j} J requis")
        if mdmt_c is not None and temp_c > mdmt_c:
            issues.append(f"Température d'essai Charpy ({temp_c} °C) > MDMT ({mdmt_c} °C)")
        info = dict(energy_avg_j=energy_avg_j, min_required_j=min_j, test_temp_c=temp_c,
                    mdmt_c=mdmt_c, rules_unverified=used)
        if issues:
            return _res(False, "NON CONFORME — " + " ; ".join(issues) + ".", **info)
        return _res(True, f"CONFORME — KV moyen {energy_avg_j} J ≥ {min_j} J à {temp_c} °C.", **info)

    # ───────────────────────── D. Concordance (schéma réel de concordance_matrix) ─────────────────────────
    def build_concordance(self, concordance_matrix: List[Dict[str, Any]],
                          page_to_piece: Optional[Callable[[str, int], Optional[str]]] = None) -> List[Dict[str, Any]]:
        """Entrée : [{parameter_name, extracted_values: {"fichier.pdf (p.N)": "valeur"}}].
        page_to_piece(fichier, page) -> 'DOC-05' etc. (issu du découpage). Sans lui, aucun rôle n'est attribué."""
        tols = self.std["concordance"].get("tolerances", {})
        rows = []
        for item in concordance_matrix or []:
            name = item.get("parameter_name", "")
            kind = classify_parameter(name)
            entries, noise = [], []
            for key, raw in (item.get("extracted_values") or {}).items():
                file, page = parse_source_key(key)
                norm = _normalize_value(kind, raw)
                if norm is None:
                    noise.append({"raw": raw, "source": key})
                    continue
                piece = page_to_piece(file, page) if (page_to_piece and page) else None
                entries.append({"norm": norm, "raw": raw, "file": file, "page": page, "piece": piece})
            rows.append(self._judge(name, kind, entries, noise, tols.get(kind, 0.0), page_to_piece is not None))
        return rows

    @staticmethod
    def _judge(name, kind, entries, noise, tol, has_pieces) -> Dict[str, Any]:
        row = {"parameter_name": name, "kind": kind, "unit": _UNITS.get(kind, ""),
               "ignored_noise": noise, "clusters": [], "consolidated_value": None,
               "by_piece": {} if has_pieces else None}
        if kind in ("thickness", "other"):
            row.update(status=NA, is_concordant=None,
                       message="Paramètre non jugé par égalité (épaisseur : règle d'inégalité "
                               "e_nom×(1−tol) ≥ e_calcul + CA, non implémentée ici)." if kind == "thickness"
                       else "Paramètre non reconnu.")
            return row
        numeric = kind in ("pressure_design", "pressure_test", "temperature")
        clusters: List[Dict[str, Any]] = []
        for e in (sorted(entries, key=lambda x: x["norm"]) if numeric else entries):
            src = {"source": f"{e['file']} (p.{e['page']})", "piece": e["piece"], "raw": e["raw"]}
            for c in clusters:
                if (numeric and abs(e["norm"] - c["value"]) <= tol) or (not numeric and e["norm"] == c["value"]):
                    c["sources"].append(src)
                    break
            else:
                clusters.append({"value": e["norm"], "sources": [src]})
            if has_pieces and e["piece"]:
                row["by_piece"].setdefault(e["piece"], []).append(e["norm"])
        row["clusters"] = clusters
        if not clusters:
            row.update(status=TBC, is_concordant=None, message="Aucune valeur exploitable (tout est bruit ou sans unité).")
        elif len(clusters) == 1:
            n = len(clusters[0]["sources"])
            row.update(consolidated_value=clusters[0]["value"])
            if n == 1:
                row.update(status=TBC, is_concordant=None, message="Source unique : pas de confirmation croisée.")
            else:
                row.update(status=OK, is_concordant=True, message=f"Concordant sur {n} sources.")
        else:
            row.update(status=KO, is_concordant=False,
                       message=f"{len(clusters)} valeurs distinctes : " + " ≠ ".join(str(c['value']) for c in clusters))
        return row

    @staticmethod
    def _consolidated(rows, kind):
        for r in rows:
            if r["kind"] == kind and r["is_concordant"] is True:
                return r["consolidated_value"]
        return None

    # ───────────────────────── E. Analyse consolidée ─────────────────────────
    def analyze_dossier(self, concordance_matrix, context: Optional[Dict[str, Any]] = None,
                        page_to_piece=None) -> Dict[str, Any]:
        """context (à fournir par l'appelant, jamais inventé) : equipment_kind, design_code, pipeline_zone,
        s_test_mpa, s_design_mpa, flange_material_group | flange_grade, heats[], sour_service, hardness_hrc."""
        ctx = context or {}
        rows = self.build_concordance(concordance_matrix, page_to_piece)
        pma = self._consolidated(rows, "pressure_design")
        p_test = self._consolidated(rows, "pressure_test")
        tma = self._consolidated(rows, "temperature")
        rat = self._consolidated(rows, "rating")
        rating_text = None if rat is None else (rat if str(rat).startswith("PN") else f"CLASS {rat}")

        hydro = self.compute_hydrotest(pma, p_test, ctx.get("equipment_kind"), ctx.get("design_code"),
                                       ctx.get("pipeline_zone"), ctx.get("s_test_mpa"), ctx.get("s_design_mpa"))
        group = ctx.get("flange_material_group") or self.material_group_from_grade(ctx.get("flange_grade"))
        flange = self.compute_flange_rating(rating_text, pma, tma, group)
        metal = self.evaluate_heats(ctx.get("heats") or [], ctx.get("limits_override"))
        nis = [h.get("Ni") for h in (ctx.get("heats") or []) if h.get("Ni") is not None]
        sour = self.check_sour_service(ctx.get("sour_service"), max(nis) if nis else None, ctx.get("hardness_hrc"))
        conc_status = combine([r["status"] for r in rows if r["status"] != TBC] or [NA])

        parts = [hydro["status"], flange["status"], metal["status"], sour["status"], conc_status]
        if any(r["status"] == TBC for r in rows):
            parts.append(TBC)
        unverified = sorted(set(hydro.get("rules_unverified", []) + flange.get("rules_unverified", [])
                                + metal.get("rules_unverified", []) + sour.get("rules_unverified", [])
                                + [u for h in metal.get("heats", []) for u in h.get("rules_unverified", [])]))
        return {"rules": self.rules_info, "overall_status": combine(parts),
                "hydrotest": hydro, "flange": flange, "metallurgy": metal, "sour_service": sour,
                "concordance": rows, "rules_unverified_used": unverified,
                "not_evaluated": [r["parameter_name"] for r in rows if r["status"] == NA]}

    def generate_full_parametric_analysis(self, dossier_id: str, context=None, page_to_piece=None) -> Dict[str, Any]:
        if not self.db_path:
            raise StandardsError("Chemin de base non défini (argument db_path ou variable ARH_DB_PATH).")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,)).fetchall()
            if not rows:
                rows = conn.execute("SELECT * FROM arh_dossiers WHERE dossier_id LIKE ?", (f"%{dossier_id}%",)).fetchall()
        if not rows:
            return {"status": "ERROR", "message": f"Dossier {dossier_id} introuvable."}
        if len(rows) > 1:
            return {"status": "ERROR", "message": "Identifiant ambigu, précisez-le.",
                    "candidates": [r["dossier_id"] for r in rows][:10]}
        row = rows[0]
        data = json.loads(row["data_json"] or "{}")
        result = self.analyze_dossier(data.get("concordance_matrix", []), context, page_to_piece)
        return {"status": "SUCCESS", "dossier_id": row["dossier_id"], **result}


_engine: Optional[ARHParametricMatrixEngine] = None


def get_engine() -> ARHParametricMatrixEngine:
    """Instanciation paresseuse (plus de singleton à l'import)."""
    global _engine
    if _engine is None:
        _engine = ARHParametricMatrixEngine()
    return _engine
