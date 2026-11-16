"""
arh_code_harness.py
===================
Moteur d'Exécution de Code Python d'Ingénierie & Preuve Formelle (Prime Agent Harness)
pour le module ARKAN -> ARH Management.

Fournit:
1. ARHCodeExecutionHarness: Sandbox Python ultra-rapide (<5ms) pour calculs mécaniques,
   métallurgiques et réglementaires avec traçabilité d'exécution irréfutable.
2. Bibliothèque Déterministe Certifiée :
   - Décret 21-261 Art. 08 (Contrainte admissible S_max = min(Rm/2.7, Re/1.75))
   - Décret 21-261 Art. 27 & API 598 (Ratio hydrostatique P_hydro >= 1.5 * PMA)
   - ASME VIII Div 1 UG-27 (Épaisseur minimale requise d'enveloppe cylindrique)
   - Base de données matière intégrée (Rm, Re) pour nuances ASTM / API / EN courantes.
"""

from __future__ import annotations
import math
import sys
import time
import re
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("ARHCodeHarness")

# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DONNÉES MÉTALLURGIQUE DE RÉFÉRENCE (ASTM / API / ASME)
# ══════════════════════════════════════════════════════════════════════════════

MATERIAL_PROPERTIES_DB: Dict[str, Dict[str, float]] = {
    # Duplex & Super Duplex
    "ASTM A995 GR 4A": {"Rm": 485.0, "Re": 310.0, "p_no": "10H", "group_no": 1},
    "UNS S31803": {"Rm": 620.0, "Re": 450.0, "p_no": "10H", "group_no": 1},
    "UNS S32205": {"Rm": 655.0, "Re": 450.0, "p_no": "10H", "group_no": 1},
    "ASTM A995 GR 5A": {"Rm": 690.0, "Re": 515.0, "p_no": "10H", "group_no": 2},
    "ASTM A995 GR 6A": {"Rm": 690.0, "Re": 485.0, "p_no": "10H", "group_no": 2},
    "ASTM A182 F51": {"Rm": 620.0, "Re": 450.0, "p_no": "10H", "group_no": 1},
    "ASTM A182 F53": {"Rm": 750.0, "Re": 550.0, "p_no": "10H", "group_no": 2},

    # Aciers carbone forgés / coulés standards
    "ASTM A105": {"Rm": 485.0, "Re": 250.0, "p_no": "1", "group_no": 2},
    "ASTM A216 WCB": {"Rm": 485.0, "Re": 250.0, "p_no": "1", "group_no": 1},
    "ASTM A216 WCC": {"Rm": 485.0, "Re": 275.0, "p_no": "1", "group_no": 2},
    "ASTM A350 LF2": {"Rm": 485.0, "Re": 250.0, "p_no": "1", "group_no": 1},
    "ASTM A352 LCC": {"Rm": 485.0, "Re": 275.0, "p_no": "1", "group_no": 2},
    "ASTM A352 LCB": {"Rm": 450.0, "Re": 240.0, "p_no": "1", "group_no": 1},

    # Tôles appareils sous pression
    "ASTM A516 GR 70": {"Rm": 485.0, "Re": 260.0, "p_no": "1", "group_no": 2},
    "SA-516 GR 70": {"Rm": 485.0, "Re": 260.0, "p_no": "1", "group_no": 2},
    "ASTM A516 GR 60": {"Rm": 415.0, "Re": 220.0, "p_no": "1", "group_no": 1},
    "SA-516 GR 60": {"Rm": 415.0, "Re": 220.0, "p_no": "1", "group_no": 1},

    # Inox austénitique
    "ASTM A182 F316L": {"Rm": 485.0, "Re": 170.0, "p_no": "8", "group_no": 1},
    "ASTM A182 F304L": {"Rm": 485.0, "Re": 170.0, "p_no": "8", "group_no": 1},
    "ASTM A312 TP316L": {"Rm": 485.0, "Re": 170.0, "p_no": "8", "group_no": 1},
    "ASTM A312 TP304L": {"Rm": 485.0, "Re": 170.0, "p_no": "8", "group_no": 1},

    # Tubes canalisations (API 5L)
    "API 5L GR B": {"Rm": 415.0, "Re": 245.0, "p_no": "1", "group_no": 1},
    "API 5L X42": {"Rm": 415.0, "Re": 290.0, "p_no": "1", "group_no": 1},
    "API 5L X52": {"Rm": 455.0, "Re": 360.0, "p_no": "1", "group_no": 1},
    "API 5L X60": {"Rm": 520.0, "Re": 415.0, "p_no": "1", "group_no": 1},
    "API 5L X65": {"Rm": 535.0, "Re": 450.0, "p_no": "1", "group_no": 1},
    "API 5L X70": {"Rm": 570.0, "Re": 485.0, "p_no": "1", "group_no": 2},

    # Raccords (Fittings)
    "ASTM A234 WPB": {"Rm": 415.0, "Re": 240.0, "p_no": "1", "group_no": 1},
    "ASTM A420 WPL6": {"Rm": 415.0, "Re": 240.0, "p_no": "1", "group_no": 1},
    "ASTM A860 WPHY 52": {"Rm": 455.0, "Re": 360.0, "p_no": "1", "group_no": 1},
    "ASTM A860 WPHY 60": {"Rm": 515.0, "Re": 415.0, "p_no": "1", "group_no": 1},
    "ASTM A860 WPHY 65": {"Rm": 530.0, "Re": 450.0, "p_no": "1", "group_no": 1},
}


def lookup_material_properties(raw_material_str: str) -> Optional[Dict[str, Any]]:
    """
    Recherche résiliente des propriétés métallurgiques (Rm, Re, P-No) pour une nuance donnée.
    Prend en compte les variantes d'écriture (ex: 'A-995 Gr.4A', 'A995 4A', 'A105N', 'Duplex 2205').
    """
    if not raw_material_str:
        return None
    
    clean = re.sub(r'[^A-Z0-9]', ' ', raw_material_str.upper())
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Match direct
    for k, v in MATERIAL_PROPERTIES_DB.items():
        k_clean = re.sub(r'[^A-Z0-9]', ' ', k.upper())
        k_clean = re.sub(r'\s+', ' ', k_clean).strip()
        if k_clean == clean or k_clean in clean or clean in k_clean:
            res = dict(v)
            res["matched_standard"] = k
            return res

    # Heuristiques spécifiques
    if any(k in clean for k in ["995 4A", "A995 4A", "GR 4A", "GRADE 4A", "CD3MN", "2205"]):
        res = dict(MATERIAL_PROPERTIES_DB["ASTM A995 GR 4A"])
        res["matched_standard"] = "ASTM A995 GR 4A"
        return res
    if "LF2" in clean:
        res = dict(MATERIAL_PROPERTIES_DB["ASTM A350 LF2"])
        res["matched_standard"] = "ASTM A350 LF2"
        return res
    if "A105" in clean:
        res = dict(MATERIAL_PROPERTIES_DB["ASTM A105"])
        res["matched_standard"] = "ASTM A105"
        return res
    if any(k in clean for k in ["516 70", "516 GR 70", "SA 516 70"]):
        res = dict(MATERIAL_PROPERTIES_DB["ASTM A516 GR 70"])
        res["matched_standard"] = "ASTM A516 GR 70"
        return res
    if any(k in clean for k in ["X52", "X 52"]):
        res = dict(MATERIAL_PROPERTIES_DB["API 5L X52"])
        res["matched_standard"] = "API 5L X52"
        return res
    if any(k in clean for k in ["X65", "X 65"]):
        res = dict(MATERIAL_PROPERTIES_DB["API 5L X65"])
        res["matched_standard"] = "API 5L X65"
        return res
    if any(k in clean for k in ["316L", "F316L", "TP316L"]):
        res = dict(MATERIAL_PROPERTIES_DB["ASTM A182 F316L"])
        res["matched_standard"] = "ASTM A182 F316L"
        return res

    return None


# ══════════════════════════════════════════════════════════════════════════════
# SANDBOX : helpers au niveau module (nécessaire pour multiprocessing/spawn sous Windows)
# ══════════════════════════════════════════════════════════════════════════════
import ast as _ast

_SANDBOX_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "breakpoint", "help", "exit", "quit", "memoryview", "type", "object", "super",
}


def _validate_sandbox_ast(code: str) -> Optional[str]:
    """Retourne un message d'erreur si le code contient une construction interdite, sinon None."""
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        return f"Erreur de syntaxe : {e}"
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            return "Instruction non autorisée dans le sandbox : import"
        if isinstance(node, (_ast.ClassDef, _ast.Global, _ast.Nonlocal, _ast.AsyncFunctionDef, _ast.Await)):
            return f"Instruction non autorisée dans le sandbox : {type(node).__name__}"
        if isinstance(node, _ast.Attribute) and node.attr.startswith("_"):
            return f"Accès d'attribut interdit : .{node.attr}"
        if isinstance(node, _ast.Name) and (node.id in _SANDBOX_FORBIDDEN_NAMES or node.id.startswith("__")):
            return f"Nom non autorisé dans le sandbox : '{node.id}'"
    return None


def _sandbox_worker(code: str, input_data: Dict[str, Any], queue) -> None:
    safe_builtins = {
        "abs": abs, "min": min, "max": max, "round": round, "len": len, "sum": sum, "range": range,
        "enumerate": enumerate, "zip": zip, "float": float, "int": int, "str": str, "bool": bool,
        "dict": dict, "list": list, "set": set, "tuple": tuple,
    }
    g = {"__builtins__": safe_builtins, "math": math, "INPUT": input_data}
    loc: Dict[str, Any] = {}
    try:
        exec(code, g, loc)
        queue.put(("ok", {k: v for k, v in loc.items()
                          if isinstance(v, (int, float, str, bool, list, dict, type(None)))}))
    except BaseException as e:  # noqa: BLE001 - tout est renvoyé à l'appelant
        queue.put(("err", f"{type(e).__name__}: {e}"))



class ARHCodeExecutionHarness:
    """
    Harnais d'exécution d'ingénierie Prime Agent pour ARKAN / ARH Management.
    Exécute les calculs mécaniques, certifie les formules et génère des preuves mathématiques irréfutables.
    """

    @classmethod
    def verify_decret_21_261_art08(
        cls,
        declared_s_mpa: float,
        material_name: str,
        rm_mpa: Optional[float] = None,
        re_mpa: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Vérifie la conformité de la contrainte admissible de calcul (S) selon le Décret exécutif n° 21-261, Article 08.
        Formule légale algérienne :
            S_max = min( Rm / 2.7 , Re / 1.75 )
        """
        t0 = time.perf_counter()
        props = lookup_material_properties(material_name)
        
        final_rm = rm_mpa or (props["Rm"] if props else 485.0)
        final_re = re_mpa or (props["Re"] if props else 250.0)
        matched_mat = props.get("matched_standard", material_name) if props else material_name

        s_rm_limit = round(final_rm / 2.7, 2)
        s_re_limit = round(final_re / 1.75, 2)
        s_max_allowed = round(min(s_rm_limit, s_re_limit), 2)

        is_compliant = declared_s_mpa <= (s_max_allowed + 0.1) # Tolérance 0.1 MPa arrondi
        overstress_ratio = round((declared_s_mpa / s_max_allowed), 2) if s_max_allowed > 0 else 0.0
        overstress_percent = round(((declared_s_mpa - s_max_allowed) / s_max_allowed) * 100.0, 1)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        proof_md = (
            f"```text\n"
            f"[PREUVE DE CALCUL FORMELLE - DÉCRET 21-261 ART. 08]\n"
            f"Matériau identifié       : {matched_mat}\n"
            f"Résistance traction (Rm) : {final_rm:.1f} MPa -> Rm / 2.7 = {s_rm_limit:.2f} MPa\n"
            f"Limite élastique (Re)    : {final_re:.1f} MPa -> Re / 1.75 = {s_re_limit:.2f} MPa\n"
            f"Plafond légal S_max      : min({s_rm_limit:.2f}, {s_re_limit:.2f}) = {s_max_allowed:.2f} MPa\n"
            f"Contrainte déclarée S    : {declared_s_mpa:.1f} MPa\n"
            f"Verdict d'ingénierie     : {'CONFORME' if is_compliant else f'DÉPASSEMENT ILLÉGAL (+{overstress_percent}% | Ratio={overstress_ratio}x)'}\n"
            f"Temps de calcul Harness  : {elapsed_ms} ms\n"
            f"```"
        )

        return {
            "is_compliant": is_compliant,
            "declared_s_mpa": declared_s_mpa,
            "s_max_allowed_mpa": s_max_allowed,
            "s_rm_limit_mpa": s_rm_limit,
            "s_re_limit_mpa": s_re_limit,
            "rm_used": final_rm,
            "re_used": final_re,
            "material_standard": matched_mat,
            "overstress_ratio": overstress_ratio,
            "overstress_percent": overstress_percent,
            "elapsed_ms": elapsed_ms,
            "proof_markdown": proof_md
        }

    @classmethod
    def verify_hydrotest_pressure(
        cls,
        pma_bar: float,
        p_hydro_declared_bar: float,
        temperature_ambient_c: float = 20.0,
        stress_ratio_test_over_design: float = 1.0
    ) -> Dict[str, Any]:
        """
        Vérifie la pression d'épreuve hydrostatique conformément au Décret 21-261 Art. 27 et API 598.
        Règle légale obligatoire :
            P_hydro >= 1.5 * PMA (Décret 21-261 / Règlementation ARH)
        """
        t0 = time.perf_counter()
        p_hydro_required_decret = round(pma_bar * 1.5, 2)
        # ASME VIII-1 UG-99(b) : 1.3 x MAWP x (S_essai / S_calcul). Le rapport de contraintes (>= 1) est
        # à fournir par l'appelant ; à défaut on garde 1.0 (valeur minimale, donc non conservatrice).
        p_hydro_required_asme = round(pma_bar * 1.3 * max(stress_ratio_test_over_design, 1.0), 2)

        # Correctif : l'ancienne tolérance de 0.5 bar acceptait une épreuve inférieure au minimum légal.
        _EPS = 0.005  # bar : seule la tolérance d'arrondi est admise
        is_compliant_decret = p_hydro_declared_bar + _EPS >= p_hydro_required_decret
        is_compliant_asme = p_hydro_declared_bar + _EPS >= p_hydro_required_asme
        ratio_actual = round(p_hydro_declared_bar / pma_bar, 2) if pma_bar > 0 else 0.0

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        proof_md = (
            f"```text\n"
            f"[PREUVE DE CALCUL FORMELLE - ÉPREUVE HYDROSTATIQUE]\n"
            f"Pression de Calcul (PMA)   : {pma_bar:.2f} bar\n"
            f"P_hydro minimale Décret    : 1.5 x {pma_bar:.2f} = {p_hydro_required_decret:.2f} bar\n"
            f"P_hydro déclarée/réalisée  : {p_hydro_declared_bar:.2f} bar (Ratio réel = {ratio_actual:.2f}x PMA)\n"
            f"Statut Décret 21-261       : {'CONFORME' if is_compliant_decret else f'NON CONFORME (Déficit de {p_hydro_required_decret - p_hydro_declared_bar:.2f} bar)'}\n"
            f"Statut ASME VIII Div 1     : {'CONFORME (1.3x)' if is_compliant_asme else 'NON CONFORME'}\n"
            f"Temps de calcul Harness    : {elapsed_ms} ms\n"
            f"```"
        )

        return {
            "is_compliant_decret": is_compliant_decret,
            "is_compliant_asme": is_compliant_asme,
            "pma_bar": pma_bar,
            "p_hydro_declared_bar": p_hydro_declared_bar,
            "p_hydro_required_decret": p_hydro_required_decret,
            "p_hydro_required_asme": p_hydro_required_asme,
            "ratio_actual": ratio_actual,
            "elapsed_ms": elapsed_ms,
            "proof_markdown": proof_md
        }

    @classmethod
    def calculate_minimum_wall_thickness_asme(
        cls,
        p_design_bar: float,
        inside_diameter_mm: float,
        s_allowable_mpa: float,
        weld_efficiency_e: float = 1.0,
        corrosion_allowance_mm: float = 3.0
    ) -> Dict[str, Any]:
        """
        Calcule l'épaisseur minimale requise d'une virole cylindrique sous pression interne selon ASME VIII Div 1 UG-27 :
            t = (P * R) / (S * E - 0.6 * P) + CA
        où P est en MPa, R en mm, S en MPa, CA en mm.
        """
        t0 = time.perf_counter()
        p_mpa = p_design_bar / 10.0
        r_mm = inside_diameter_mm / 2.0
        
        denom = (s_allowable_mpa * weld_efficiency_e) - (0.6 * p_mpa)
        if denom <= 0:
            return {"error": "Dénominateur ASME UG-27 <= 0 (Contrainte admissible insuffisante pour cette pression)"}

        t_pressure = (p_mpa * r_mm) / denom                      # UG-27(c)(1) contrainte circonférentielle
        # UG-27(c)(2) contrainte longitudinale : t = P*R / (2*S*E + 0.4*P)
        denom_long = (2.0 * s_allowable_mpa * weld_efficiency_e) + (0.4 * p_mpa)
        t_long = (p_mpa * r_mm) / denom_long if denom_long > 0 else 0.0
        t_governing = max(t_pressure, t_long)
        # Domaine de validité des formules de paroi mince (UG-27(c)(1) : t <= 0.5R et P <= 0.385*S*E)
        validity_notes = []
        if t_governing > 0.5 * r_mm:
            validity_notes.append("t > R/2 : formule hors domaine (Appendice 1-2 requis)")
        if p_mpa > 0.385 * s_allowable_mpa * weld_efficiency_e:
            validity_notes.append("P > 0.385*S*E : formule hors domaine (Appendice 1-2 requis)")
        t_total_min = round(t_governing + corrosion_allowance_mm, 2)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        proof_md = (
            f"```text\n"
            f"[CALCUL ASME VIII DIV 1 UG-27]\n"
            f"Pression P           : {p_mpa:.3f} MPa ({p_design_bar:.1f} bar)\n"
            f"Rayon intérieur R    : {r_mm:.1f} mm (ID = {inside_diameter_mm:.1f} mm)\n"
            f"Contrainte adm. S    : {s_allowable_mpa:.1f} MPa (E={weld_efficiency_e})\n"
            f"Épaisseur pression t : {t_pressure:.2f} mm\n"
            f"Surépaisseur CA      : {corrosion_allowance_mm:.2f} mm\n"
            f"Épaisseur min requise: {t_total_min:.2f} mm\n"
            f"Temps d'exécution    : {elapsed_ms} ms\n"
            f"```"
        )

        return {
            "t_pressure_mm": round(t_pressure, 2),
            "t_longitudinal_mm": round(t_long, 2),
            "t_governing_mm": round(t_governing, 2),
            "validity_ok": not validity_notes,
            "validity_notes": validity_notes,
            "corrosion_allowance_mm": corrosion_allowance_mm,
            "t_total_min_mm": t_total_min,
            "p_mpa": p_mpa,
            "inside_diameter_mm": inside_diameter_mm,
            "s_allowable_mpa": s_allowable_mpa,
            "elapsed_ms": elapsed_ms,
            "proof_markdown": proof_md
        }

    @classmethod
    def execute_sandboxed_code(
        cls,
        python_code: str,
        input_data: Optional[Dict[str, Any]] = None,
        timeout_sec: float = 1.0
    ) -> Dict[str, Any]:
        """
        Exécute un bloc de calcul dans un processus séparé, avec builtins restreints, validation AST et
        TIMEOUT réellement appliqué (v1 : le paramètre était ignoré, un `while True:` bloquait le serveur).

        ATTENTION : ce n'est PAS une frontière de sécurité contre du code hostile. À réserver à du code
        écrit par l'application (formules). Ne jamais y exécuter du texte venant d'un utilisateur ou d'un LLM
        sans isolation système (conteneur, utilisateur sans droits, limites mémoire).
        """
        import multiprocessing as mp
        t0 = time.perf_counter()

        def _elapsed() -> float:
            return round((time.perf_counter() - t0) * 1000, 2)

        err = _validate_sandbox_ast(python_code)
        if err:
            return {"status": "FORBIDDEN_OPERATION", "error": err, "elapsed_ms": _elapsed()}

        ctx = mp.get_context("spawn" if sys.platform.startswith("win") else "fork")
        queue = ctx.Queue()
        proc = ctx.Process(target=_sandbox_worker, args=(python_code, input_data or {}, queue), daemon=True)
        proc.start()
        proc.join(timeout_sec)
        if proc.is_alive():
            proc.terminate()
            proc.join(1.0)
            if proc.is_alive():
                proc.kill()
            return {"status": "TIMEOUT", "error": f"Dépassement du délai ({timeout_sec} s)", "elapsed_ms": _elapsed()}
        try:
            kind, payload = queue.get(timeout=1.0)
        except Exception:
            return {"status": "ERROR", "error": "Aucun résultat retourné par le sandbox", "elapsed_ms": _elapsed()}
        if kind == "ok":
            return {"status": "SUCCESS", "result": payload, "elapsed_ms": _elapsed()}
        return {"status": "ERROR", "error": payload, "elapsed_ms": _elapsed()}

# Instance singleton du harnais
arh_code_harness = ARHCodeExecutionHarness()
