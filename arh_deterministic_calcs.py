"""
arh_deterministic_calcs.py
==========================
Calculs réglementaires déterministes (sans IA) pour ARKAN ARH, avec domaines de validité et sources.

Chaque fonction retourne un dict contenant la valeur, la formule, la référence normative et des
`warnings`. Les contraintes admissibles NE SONT PAS codées ici : elles doivent venir des tables
ASME II-D (par grade, par température) fournies par l'appelant.

Références (à contrôler sur l'édition applicable du code / du texte au Journal Officiel) :
  - ASME VIII-1 UG-27(c)(1)/(c)(2), UG-99(b)
  - Barlow (Décret exécutif 21-315)
  - CEV IIW / Pcm (Ito-Bessyo)
"""
from __future__ import annotations
from typing import Dict, Any, Optional


def ug27_cylindrical_shell(p_mpa: float, inside_radius_mm: float, s_allowable_mpa: float,
                           joint_efficiency: float = 1.0, corrosion_allowance_mm: float = 0.0) -> Dict[str, Any]:
    """Épaisseur minimale d'une virole cylindrique sous pression interne (UG-27(c)(1) et (c)(2))."""
    warnings = []
    if min(p_mpa, inside_radius_mm, s_allowable_mpa, joint_efficiency) <= 0:
        raise ValueError("P, R, S et E doivent être strictement positifs")
    if joint_efficiency > 1.0:
        raise ValueError("Le coefficient de joint E doit être <= 1.0")
    se = s_allowable_mpa * joint_efficiency
    denom_c = se - 0.6 * p_mpa
    if denom_c <= 0:
        raise ValueError("S*E - 0.6*P <= 0 : pression incompatible avec la contrainte admissible")
    t_circ = p_mpa * inside_radius_mm / denom_c
    t_long = p_mpa * inside_radius_mm / (2.0 * se + 0.4 * p_mpa)
    t_gov = max(t_circ, t_long)
    if t_gov > 0.5 * inside_radius_mm:
        warnings.append("t > R/2 : hors domaine UG-27(c), utiliser l'Appendice 1-2")
    if p_mpa > 0.385 * se:
        warnings.append("P > 0.385*S*E : hors domaine UG-27(c)(1), utiliser l'Appendice 1-2")
    return {
        "t_circumferential_mm": round(t_circ, 3), "t_longitudinal_mm": round(t_long, 3),
        "t_governing_mm": round(t_gov, 3), "t_with_corrosion_mm": round(t_gov + corrosion_allowance_mm, 3),
        "formula": "t = P*R/(S*E-0.6*P) ; t = P*R/(2*S*E+0.4*P)", "reference": "ASME VIII-1 UG-27(c)",
        "valid": not warnings, "warnings": warnings,
    }


def ug99_hydrotest_minimum(mawp_bar: float, s_test_mpa: float, s_design_mpa: float) -> Dict[str, Any]:
    """Pression d'épreuve hydrostatique minimale ASME : 1.3 x MAWP x (S_essai / S_calcul)  (UG-99(b))."""
    if min(mawp_bar, s_test_mpa, s_design_mpa) <= 0:
        raise ValueError("MAWP et contraintes doivent être strictement positifs")
    ratio = max(s_test_mpa / s_design_mpa, 1.0)
    return {"p_test_min_bar": round(1.3 * mawp_bar * ratio, 2), "stress_ratio": round(ratio, 4),
            "reference": "ASME VIII-1 UG-99(b)"}


def decree_hydrotest_minimum(pma_bar: float, kind: str = "ESP", zone: str = "A") -> Dict[str, Any]:
    """Pression d'épreuve minimale réglementaire : ESP 150 % PMA (21-261) ; canalisations 150 % (A/B) ou 125 % (C/D) (21-314)."""
    if pma_bar <= 0:
        raise ValueError("PMA doit être strictement positive")
    if kind.upper() == "PIPELINE":
        mult = 1.25 if zone.upper() in ("C", "D") else 1.50
        ref = f"Décret 21-314 Art. 21 (zone {zone.upper()})"
    else:
        mult, ref = 1.50, "Décret 21-261 Art. 27"
    return {"p_test_min_bar": round(pma_bar * mult, 2), "multiplier": mult, "reference": ref}


def governing_hydrotest_minimum(pma_bar: float, s_test_mpa: float, s_design_mpa: float,
                                kind: str = "ESP", zone: str = "A") -> Dict[str, Any]:
    """Retient le référentiel le plus sévère entre décret et ASME UG-99, et nomme celui qui gouverne."""
    d = decree_hydrotest_minimum(pma_bar, kind, zone)
    a = ug99_hydrotest_minimum(pma_bar, s_test_mpa, s_design_mpa)
    gov = "décret" if d["p_test_min_bar"] >= a["p_test_min_bar"] else "ASME UG-99"
    return {"p_test_min_bar": max(d["p_test_min_bar"], a["p_test_min_bar"]), "governing": gov,
            "decree": d, "asme": a}


def barlow_pipe_thickness(p_mpa: float, outside_diameter_mm: float, rt05_mpa: float,
                          design_factor_f: float, z_coef: float = 1.0) -> Dict[str, Any]:
    """Décret 21-315 : e = P*D / (2 * R_t0.5 * F * Z)  (F attendu dans [0.40 ; 0.72])."""
    if min(p_mpa, outside_diameter_mm, rt05_mpa, design_factor_f, z_coef) <= 0:
        raise ValueError("Toutes les entrées doivent être strictement positives")
    warnings = []
    if not 0.40 <= design_factor_f <= 0.72:
        warnings.append("Facteur de conception F hors de [0.40 ; 0.72]")
    e = p_mpa * outside_diameter_mm / (2.0 * rt05_mpa * design_factor_f * z_coef)
    return {"e_mm": round(e, 3), "reference": "Décret 21-315 (Barlow)", "warnings": warnings}


def carbon_equivalent(c: float, mn: float, cr: float = 0.0, mo: float = 0.0, v: float = 0.0,
                      ni: float = 0.0, cu: float = 0.0, si: Optional[float] = None, b: float = 0.0) -> Dict[str, float]:
    """CEV (IIW) = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15 ; Pcm si Si fourni = C+Si/30+(Mn+Cu+Cr)/20+Ni/60+Mo/15+V/10+5B."""
    out = {"cev_iiw": round(c + mn / 6.0 + (cr + mo + v) / 5.0 + (ni + cu) / 15.0, 4)}
    if si is not None:
        out["pcm"] = round(c + si / 30.0 + (mn + cu + cr) / 20.0 + ni / 60.0 + mo / 15.0 + v / 10.0 + 5.0 * b, 4)
    return out
