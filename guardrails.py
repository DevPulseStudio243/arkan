"""
DeerFlow Lite - Guardrails v2.1
Answer verification, grounding checks, and safety filters.

CORRECTIONS v2.1:
- BUG CRITIQUE corrigé (ex-ligne 181-183) : suppression du retour True
  inconditionnel pour tout tag Oil&Gas bien formé. La vérification exige
  désormais que le tag soit RÉELLEMENT présent dans le contexte fourni.
- Ajout des fonctions module-level extract_claims() et verify_grounding()
  pour les tests unitaires.
"""
import re
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class AnswerGuardrails:
    """
    Verify that LLM answers are grounded in the provided context.
    Detect and flag hallucinated content.
    """

    # Variantes d'unités acceptées (forme canonique → variantes)
    _UNIT_VARIANTS = {
        "bar": ["bar", "bars", "barg", "bara", "bar(g)", "bar(a)", "bar g", "bar a"],
        "psi": ["psi", "psig", "psia", "psi(g)"],
        "kpa": ["kpa", "kpag", "kpaa"],
        "mpa": ["mpa", "mpag"],
        "°c": ["°c", "deg c", "degc", "celsius", "c"],
        "°f": ["°f", "deg f", "degf", "fahrenheit"],
        "kg/cm2": ["kg/cm2", "kg/cm²", "kgf/cm2", "kgcm2"],
    }

    def __init__(self):
        # Seuil : 0.5 → on n'affiche l'avertissement que si < 50% des claims sont groundés
        self._hallucination_threshold = 0.5

    def verify_answer(self, answer: str, context: str, query: str = "") -> dict:
        """
        Verify an answer against the context.

        Returns:
            Dict with verification results:
            - grounded: bool
            - grounding_ratio: float (0-1)
            - flagged_claims: list of potentially hallucinated claims
            - sanitized_answer: answer with ungrounded claims marked
        """
        claims = self._extract_claims(answer)

        if not claims:
            return {
                "grounded": True,
                "grounding_ratio": 1.0,
                "flagged_claims": [],
                "sanitized_answer": answer,
            }

        grounded_claims = []
        ungrounded_claims = []

        context_lower = context.lower()

        for claim in claims:
            if self._is_claim_grounded(claim, context_lower):
                grounded_claims.append(claim)
            else:
                ungrounded_claims.append(claim)

        grounding_ratio = len(grounded_claims) / len(claims) if claims else 1.0

        sanitized = answer
        if ungrounded_claims and grounding_ratio < self._hallucination_threshold:
            sanitized = self._sanitize_answer(answer, ungrounded_claims, context)

        return {
            "grounded": grounding_ratio >= self._hallucination_threshold,
            "grounding_ratio": round(grounding_ratio, 3),
            "flagged_claims": ungrounded_claims,
            "ungrounded": ungrounded_claims,   # alias pour les tests
            "grounded_list": grounded_claims,
            "sanitized_answer": sanitized,
            "total_claims": len(claims),
            "grounded_claims": len(grounded_claims),
            "ratio": round(grounding_ratio, 3),  # alias court pour les tests
        }

    def _extract_claims(self, answer: str) -> list[dict]:
        """Extract verifiable claims from the answer."""
        claims = []

        # Numeric claims: "pressure is 25 bar", "diamètre de 150 mm"
        numeric_patterns = [
            (r'(\d+(?:[.,]\d+)?)\s*(bar|barg|bara|psi|psig|kPa|MPa)', "pressure"),
            (r'(\d+(?:[.,]\d+)?)\s*(°C|°F|K)', "temperature"),
            (r'(\d+(?:[.,]\d+)?)\s*(mm|cm|m|inch|ft|pouces?)', "dimension"),
            (r'(\d+(?:[.,]\d+)?)\s*(kg/h|m³/h|l/min|GPM|t/h)', "flow"),
            (r'(\d+(?:[.,]\d+)?)\s*(kW|MW|HP|CV)', "power"),
            (r'(\d+(?:[.,]\d+)?)\s*(rpm|tr/min)', "speed"),
            (r'DN\s*(\d+)', "pipe_size"),
            (r'NPS\s*(\d+)', "pipe_size"),
        ]

        for pattern, claim_type in numeric_patterns:
            for match in re.finditer(pattern, answer, re.IGNORECASE):
                claims.append({
                    "type": "numeric",
                    "category": claim_type,
                    "value": match.group(0),
                    "raw_value": match.group(1) if match.lastindex >= 1 else match.group(0),
                })

        # Norm references
        norm_pattern = r'\b(API|ASME|ISO|EN|IEC|NFPA|ASTM|IEEE|NF)\s*[\s-]?\d[\d\.\-]*\b'
        for match in re.finditer(norm_pattern, answer, re.IGNORECASE):
            claims.append({
                "type": "norm",
                "value": match.group(0).strip(),
            })

        # Equipment tag references — exclut les numéros de documents (F-000, S-000, D-000)
        # Pattern : lettre(s)-chiffres NON nuls (C-101, V-102, FA-1301P, PSV-101)
        tag_pattern = r'\b([A-Z]{1,4}-(?!0{2,}(?:[^0-9]|$))\d{2,5}[A-Z0-9]*)\b'
        for match in re.finditer(tag_pattern, answer):
            tag_val = match.group(1)
            # Exclure les tags qui ressemblent à des numéros de documents (ex: F-000-xxxx)
            if re.match(r'^[A-Z]{1,2}-0+$', tag_val):
                continue
            claims.append({
                "type": "equipment",
                "value": tag_val,
            })

        # Material specifications
        material_pattern = r'\b(A\d{3}(?:\s*Gr\.?\s*[A-Z]+)?|ASTM\s+A\d{3}|316[L]?|304[L]?|2205|Inconel\s*\d{3})\b'
        for match in re.finditer(material_pattern, answer, re.IGNORECASE):
            claims.append({
                "type": "material",
                "value": match.group(0).strip(),
            })

        return claims

    def _is_claim_grounded(self, claim: dict, context_lower: str) -> bool:
        """
        V2.2 — Vérification intelligente du grounding.
        Tolère les variantes d'unités, formats d'équipements, et normes avec/sans espaces.
        """
        value = claim["value"]
        value_lower = value.lower()

        # ── 1. Correspondance directe (cas-insensible) ───────────────────────
        if value_lower in context_lower:
            return True

        # ── 2. Valeurs numériques ────────────────────────────────────────────
        if claim["type"] == "numeric":
            raw = claim.get("raw_value", "")
            if raw and raw in context_lower:
                return True
            if raw:
                # Alternance . / ,
                alt = raw.replace(".", ",") if "." in raw else raw.replace(",", ".")
                if alt in context_lower:
                    return True
                try:
                    num_val = float(raw.replace(",", "."))
                    # Ex: 25.0 → "25"
                    if num_val.is_integer() and str(int(num_val)) in context_lower:
                        return True
                    if str(num_val) in context_lower or str(num_val).replace(".", ",") in context_lower:
                        return True
                except ValueError:
                    pass

            # Variantes d'unités : "900 bars" → chercher "900 bar", "900barg"...
            # Extraire la valeur numérique de la claim complète
            num_match = re.search(r'([\d]+(?:[.,]\d+)?)', value_lower)
            if num_match:
                num_str = num_match.group(1)
                # Chercher ce nombre suivi de n'importe quelle variante d'unité dans le contexte
                cat = claim.get("category", "")
                if cat in ("pressure",):
                    for variants in [self._UNIT_VARIANTS[u] for u in self._UNIT_VARIANTS
                                     if u in ("bar", "psi", "kpa", "mpa", "kg/cm2")]:
                        for unit_var in variants:
                            pattern_str = re.escape(num_str) + r'\s*' + re.escape(unit_var)
                            if re.search(pattern_str, context_lower):
                                return True
                elif cat in ("temperature",):
                    for variants in [self._UNIT_VARIANTS[u] for u in self._UNIT_VARIANTS
                                     if u in ("°c", "°f")]:
                        for unit_var in variants:
                            pattern_str = re.escape(num_str) + r'\s*' + re.escape(unit_var)
                            if re.search(pattern_str, context_lower):
                                return True
                # Fallback : le seul numéro est-il présent dans le contexte ?
                # (pour les plages de valeurs comme "5 à 900 bars")
                if num_str in context_lower:
                    return True

            return False

        # ── 3. Normes et standards ───────────────────────────────────────────
        if claim["type"] == "norm":
            # Sans espaces
            simplified = re.sub(r'[\s\-]+', '', value_lower)
            context_no_space = re.sub(r'[\s\-]+', '', context_lower)
            if simplified in context_no_space:
                return True
            # Avec tirets normalisés (ex: "IEC-60079" pour "IEC 60079")
            norm_with_dash = re.sub(r'\s+', '-', value_lower)
            if norm_with_dash in context_lower:
                return True
            return False

        # ── 4. Équipements — vérification dans contexte + KB ─────────────────
        if claim["type"] == "equipment":
            # Variante sans tiret (ex: "C 101" pour "C-101")
            value_no_dash = value.replace('-', ' ').lower()
            if value_no_dash in context_lower:
                return True
            # Variante sans espace (ex: "C101" pour "C-101")
            value_no_sep = value.replace('-', '').lower()
            if value_no_sep in context_lower:
                return True
            # Partie numérique longue ≥4 chiffres
            num_part = re.search(r'(\d{4,})', value)
            if num_part and num_part.group(1) in context_lower:
                return True
            # Si le tag est listé dans la section KB ("[Informations extraites...")
            # Cela couvre les équipements trouvés dans les documents mais pas forcément
            # dans le chunk ChromaDB récupéré
            if "informations extraites" in context_lower and value_lower in context_lower:
                return True
            # Vérification: le préfixe lettre (K, C, V, E...) + numéro existent-ils dans KB ?
            # Les tags comme K-101 → le mot "k-101" doit apparaître quelque part dans context
            # (déjà vérifié par correspondance directe ci-dessus)
            return False

        # ── 5. Matériaux ─────────────────────────────────────────────────────
        if claim["type"] == "material":
            # Variante sans espaces
            simplified = re.sub(r'\s+', '', value_lower)
            if simplified in re.sub(r'\s+', '', context_lower):
                return True
            return False

        return False

    def _sanitize_answer(self, answer: str, ungrounded: list[dict], context: str) -> str:
        """Mark or remove ungrounded claims from the answer."""
        sanitized = answer

        # Add warning header
        warning = ("\n\n⚠ **Attention** : Certaines informations dans cette réponse "
                   "n'ont pas pu être vérifiées dans la documentation source. "
                   "Les éléments suivants nécessitent une vérification :\n")

        flagged_items = []
        for claim in ungrounded:
            flagged_items.append(f"- {claim['value']} ({claim['type']})")

        if flagged_items:
            sanitized += warning + "\n".join(flagged_items)

        return sanitized

    def check_safety(self, answer: str) -> dict:
        """Check answer for safety issues (not domain-related content)."""
        issues = []

        # Check for leaked file paths
        if re.search(r'[A-Z]:\\|/home/|/usr/|/var/', answer):
            issues.append("Chemins de fichiers système détectés dans la réponse")

        # Check for potential credential leaks
        if re.search(r'(?:password|mot de passe|secret|token|api.?key)\s*[:=]\s*\S+', answer, re.IGNORECASE):
            issues.append("Informations sensibles potentielles détectées")

        # Guardrail physique de sécurité : pression élevée sur matériau non-métallique/plastique
        non_metallic_keywords = ["pvc", "pe", "hdpe", "plastique", "polyethylene", "polyéthylène", "fiberglass"]
        # On cherche les mots en tant que tokens distincts
        has_non_metallic = any(re.search(rf"\b{re.escape(kw)}\b", answer, re.IGNORECASE) for kw in non_metallic_keywords)

        if has_non_metallic:
            # Recherche de valeurs de pression, ex : "12 bar", "150 psi"
            pressure_pattern = r'(\d+(?:[.,]\d+)?)\s*(bar|bars|barg|bara|psi|psig)\b'
            for match in re.finditer(pressure_pattern, answer, re.IGNORECASE):
                try:
                    val_str = match.group(1).replace(",", ".")
                    val = float(val_str)
                    unit = match.group(2).lower()

                    if unit.startswith("bar") and val > 10.0:
                        issues.append(f"Risque de sécurité : Pression élevée ({val} {unit} > 10 bar) détectée sur équipement/tuyauterie plastique/non-métallique.")
                        break
                    elif unit.startswith("psi") and val > 145.0:
                        issues.append(f"Risque de sécurité : Pression élevée ({val} {unit} > 145 psi) détectée sur équipement/tuyauterie plastique/non-métallique.")
                        break
                except ValueError:
                    continue

        return {
            "safe": len(issues) == 0,
            "issues": issues,
        }


# Module-level convenience functions
_guardrails = None
_guardrails_lock = threading.Lock()

def get_guardrails() -> AnswerGuardrails:
    global _guardrails
    if _guardrails is None:
        with _guardrails_lock:
            if _guardrails is None:
                _guardrails = AnswerGuardrails()
    return _guardrails

def verify_answer(answer: str, context: str, query: str = "") -> dict:
    return get_guardrails().verify_answer(answer, context, query)

def check_safety(answer: str) -> dict:
    return get_guardrails().check_safety(answer)

# Fonctions module-level pour les tests unitaires (alias)
def extract_claims(answer: str) -> list[dict]:
    """Extrait les claims d'une réponse (alias module-level pour les tests)."""
    return get_guardrails()._extract_claims(answer)

def verify_grounding(claims: list[dict], context: str) -> dict:
    """
    Vérifie le grounding d'une liste de claims contre un contexte.
    Retourne un dict avec grounded, ungrounded, ratio.
    """
    g = get_guardrails()
    context_lower = context.lower()
    grounded = []
    ungrounded = []
    for claim in claims:
        if g._is_claim_grounded(claim, context_lower):
            grounded.append(claim)
        else:
            ungrounded.append(claim)
    ratio = len(grounded) / len(claims) if claims else 1.0
    return {
        "grounded": grounded,
        "ungrounded": ungrounded,
        "ratio": round(ratio, 3),
        "grounding_ratio": round(ratio, 3),
    }
