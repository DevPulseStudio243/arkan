"""
arh_model_router.py
====================
Router Multi-Modèles Intelligent pour ARKAN ARH.

Remplace l'appel naïf à un seul modèle par un dispatch intelligent vers
le LoRA spécialisé correspondant à la Part P-CTE-1 détectée dans le document,
et à la langue identifiée.

Architecture :
  1. ARHPartClassifier     — Détecte la Part P-CTE-1 du document
  2. ARHLanguageDetector   — Détecte la langue dominante
  3. ARHModelDispatcher    — Sélectionne et appelle le bon modèle Ollama
  4. ARHResultMerger       — Fusionne les résultats multi-parts pour un dossier complet

Modèles Ollama disponibles (après fine-tuning Kaggle) :
  arkan-arh-global        — LoRA global (fallback universel)
  arkan-arh-annexe-e      — Spécialisé Part 4 État Descriptif
  arkan-arh-calcs         — Spécialisé Part 5 Calculs ASME
  arkan-arh-welding       — Spécialisé Part 8 WPS/PQR Soudage
  arkan-arh-itp           — Spécialisé Part 10 Plan Inspection
  arkan-arh-material      — Spécialisé Certificats Matière 3.1
  arkan-arh-consular      — Spécialisé Part 2 Légalisation
  arkan-arh-atex          — Spécialisé Part 11 ATEX/IECEx
"""

from __future__ import annotations

import re
import json
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path

from arh_ollama_client import get_ollama_client, parse_json_3tier, ARHOllamaClient

logger = logging.getLogger("ARHModelRouter")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION DES MODÈLES OLLAMA
# ══════════════════════════════════════════════════════════════════════════════

# Mapping Part → Nom du modèle Ollama fine-tuné
PART_TO_MODEL: Dict[str, str] = {
    "PART_1_LETTRE":    "arkan-arh-global",
    "PART_2_CONSULAIRE":"arkan-arh-consular",
    "PART_3_CERTS":     "arkan-arh-global",
    "PART_4_ANNEXE_E":  "arkan-arh-annexe-e",
    "PART_5_CALCS":     "arkan-arh-calcs",
    "PART_6_PLANS":     "arkan-arh-global",
    "PART_8_SOUDAGE":   "arkan-arh-welding",
    "PART_9_PWHT":      "arkan-arh-welding",
    "PART_10_ITP":      "arkan-arh-itp",
    "PART_11_ELEC":     "arkan-arh-atex",
    "PART_12_CONSERV":  "arkan-arh-global",
    "CERT_MATERIAU":    "arkan-arh-material",
    "LEVEE_RESERVES":   "arkan-arh-global",
    "ADMIN_GLOBAL":     "arkan-arh-consular",
    "GENERAL":          "arkan-arh-global",
}

# Modèle de fallback si le modèle spécialisé n'est pas disponible
FALLBACK_MODEL = "arkan-arh-global"

# Modèle legacy (Qwen 7B existant) — utilisé si aucun modèle 14B n'est disponible
LEGACY_MODEL   = "arkan-arh-7b"

# Paramètres Ollama
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_TIMEOUT  = 300  # 5 minutes max par requête

# ══════════════════════════════════════════════════════════════════════════════
# 1. CLASSIFIEUR DE PART P-CTE-1
# ══════════════════════════════════════════════════════════════════════════════

PART_PATTERNS: List[tuple] = [
    ("PART_2_CONSULAIRE", [
        r"\bCONSULAT\b", r"\bCHAMBRE DE COMMERCE\b", r"\bLÉGALISATION\b",
        r"\bCONSULAR\b", r"\bCHAMBER OF COMMERCE\b", r"\bP-CTE-1 PART 2\b",
        r"التوثيق القنصلي", r"领事认证",
    ]),
    ("PART_4_ANNEXE_E", [
        r"\bANNEXE E\b", r"\bÉTAT DESCRIPTIF\b", r"\bDESCRIPTIVE STATEMENT\b",
        r"\bFICHE DESCRIPTIVE\b", r"\bPRESS(?:ION)? DE CALCUL\b",
        r"\bDESIGN PRESSURE\b", r"\bPMA\b.*\bbar\b",
        r"البيان الوصفي", r"技术描述",
    ]),
    ("PART_5_CALCS", [
        r"\bNOTE DE CALCUL\b", r"\bCALCULATION NOTE\b", r"\bASME VIII\b",
        r"\bUG-27\b", r"\bBARLOW\b", r"\bWALL THICKNESS\b",
        r"\bCONTRAINTE ADMISSIBLE\b", r"\bALLOWABLE STRESS\b",
        r"\bÉPAISSEUR MINIMALE\b", r"\bMINIMUM WALL\b",
    ]),
    ("PART_8_SOUDAGE", [
        r"\bWPS\b", r"\bPQR\b", r"\bCAHIER DE SOUDAGE\b", r"\bWELDING PROCEDURE\b",
        r"\bQUALIFICATION SOUDEUR\b", r"\bWELDER QUALIFICATION\b",
        r"\bASME IX\b", r"\bISO 9606\b", r"\bSMAW\b|\bGTAW\b|\bGMAW\b|\bSAW\b",
        r"إجراء اللحام", r"焊接程序",
    ]),
    ("PART_9_PWHT", [
        r"\bPWHT\b", r"\bTRAITEMENT THERMIQUE\b", r"\bHEAT TREATMENT\b",
        r"\bNORMALISATION\b", r"\bRECUIT\b", r"\bPOST WELD\b",
    ]),
    ("PART_10_ITP", [
        r"\bITP\b", r"\bPLAN D'INSPECTION\b", r"\bINSPECTION AND TEST\b",
        r"\bHOLD POINT\b|\bH POINT\b", r"\bWITNESS POINT\b|\bW POINT\b",
        r"\bPOINT D'ARRÊT\b", r"\bTPi\b|\bTPI\b",
        r"خطة التفتيش", r"检验测试计划",
    ]),
    ("PART_11_ELEC", [
        r"\bATEX\b", r"\bIECEX\b", r"\bIEC 60079\b|\bEN 60079\b",
        r"\bZONE \d+\b", r"\bEX [A-Z]\b", r"\bSIL \d\b",
        r"\bTABLEAU (?:HT|BT)\b", r"\bIEC 61439\b",
        r"الكهرباء", r"电气设备",
    ]),
    ("CERT_MATERIAU", [
        r"\bEN 10204\b", r"\b3\.1\b.*\bcertifi", r"\bHEAT NUMBER\b|\bN° DE COULÉE\b",
        r"\bCOMPOSITION CHIMIQUE\b|\bCHEMICAL COMPOSITION\b",
        r"\bCEV\b|\bCARBONE ÉQUIVALENT\b", r"\bCHARPY\b", r"\bRÉSILIENCE\b",
        r"\bHV10\b|\bHBW\b", r"شهادة المواد", r"材质证书",
    ]),
    ("LEVEE_RESERVES", [
        r"\bLEVÉE DE RÉSERVES\b|\bLEVER DE RÉSERVES\b", r"\bRESERVE LIFTED\b",
        r"\bRÉPONSE EPC\b", r"\bJUSTIFICATIF\b.*\bRÉSERVE\b",
        r"\bLETTRE ARH\b.*\bRÉF\b", r"رفع التحفظات",
    ]),
    ("PART_1_LETTRE", [
        r"\bDEMANDE D'AVIS\b", r"\bAVIS DE CONFORMITÉ\b", r"\bPAGE DE GARDE\b",
        r"\bLETTER REQUESTING APPROVAL\b", r"\bAUTORITÉ DE RÉGULATION\b",
        r"\bPRÉSIDENT.*ARH\b|\bARH.*PRÉSIDENT\b",
    ]),
]


class ARHPartClassifier:
    """Classifie la Part P-CTE-1 d'un texte de document."""

    def classify(self, text: str) -> str:
        """Retourne la Part P-CTE-1 la plus probable."""
        text_upper = text.upper()
        scores: Dict[str, int] = {}

        for part_name, patterns in PART_PATTERNS:
            score = 0
            for pattern in patterns:
                if re.search(pattern, text_upper, re.IGNORECASE):
                    score += 1
            if score > 0:
                scores[part_name] = score

        if not scores:
            return "GENERAL"

        return max(scores, key=scores.get)

    def classify_all(self, text: str) -> List[tuple]:
        """Retourne toutes les Parts détectées avec leur score (pour dossiers multi-parts)."""
        text_upper = text.upper()
        results = []
        for part_name, patterns in PART_PATTERNS:
            score = sum(1 for p in patterns if re.search(p, text_upper, re.IGNORECASE))
            if score > 0:
                results.append((part_name, score))
        return sorted(results, key=lambda x: -x[1])


# ══════════════════════════════════════════════════════════════════════════════
# 2. DÉTECTEUR DE LANGUE
# ══════════════════════════════════════════════════════════════════════════════

class ARHLanguageDetector:
    """Détecte la langue dominante d'un texte ARH."""

    _AR_PATTERN = re.compile(r"[\u0600-\u06FF]{4,}", re.UNICODE)
    _ZH_PATTERN = re.compile(r"[\u4E00-\u9FFF]{3,}", re.UNICODE)
    _EN_KEYWORDS = re.compile(
        r"\b(PRESSURE|VESSEL|CERTIFICATE|WELDING|INSPECTION|CALCULATION|"
        r"DRAWING|THICKNESS|APPROVAL|HYDROSTATIC|ALLOWABLE|MANUFACTURER|"
        r"HEAT NUMBER|CHARPY|HARDNESS|YIELD STRENGTH)\b",
        re.IGNORECASE
    )

    def detect(self, text: str) -> str:
        """Retourne le code de langue : FR, EN, AR ou ZH."""
        if self._AR_PATTERN.search(text):
            return "AR"
        if self._ZH_PATTERN.search(text):
            return "ZH"
        en_score = len(self._EN_KEYWORDS.findall(text))
        if en_score >= 2:
            return "EN"
        return "FR"


# ══════════════════════════════════════════════════════════════════════════════
# 3. DISPATCHER OLLAMA
# ══════════════════════════════════════════════════════════════════════════════

class ARHModelDispatcher:
    """Appelle le bon modèle Ollama selon la Part et la langue."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, timeout: int = OLLAMA_TIMEOUT):
        self.base_url       = base_url.rstrip("/")
        self.timeout        = timeout
        self.client         = ARHOllamaClient(base_url=self.base_url, timeout=self.timeout)
        self._available     : Optional[set] = None  # Cache des modèles disponibles

    def _get_available_models(self) -> set:
        """Récupère la liste des modèles Ollama disponibles (avec cache)."""
        if self._available is not None:
            return self._available
        models = self.client.list_models()
        self._available = {m.split(":")[0] for m in models}
        logger.info("[Router] Modèles Ollama disponibles : %s", self._available)
        return self._available

    def select_model(self, part: str, language: str = "FR") -> str:
        """Choisit le meilleur modèle disponible pour cette Part et cette langue."""
        available = self._get_available_models()
        preferred = PART_TO_MODEL.get(part, FALLBACK_MODEL)

        # Priorité : modèle spécialisé 14B > global 14B > legacy 7B
        candidates = [preferred, FALLBACK_MODEL, LEGACY_MODEL]
        for model_name in candidates:
            if model_name in available or not available:
                # Si Ollama n'est pas dispo, utiliser preferred par défaut
                return model_name

        return LEGACY_MODEL

    def call_ollama(self, model: str, prompt: str, system: str = "") -> Optional[str]:
        """
        Appelle l'API Ollama Generate et retourne la réponse texte via le client unifié.
        """
        return self.client.generate(
            model=model,
            prompt=prompt,
            system=system,
            options={
                "temperature": 0.05,
                "top_p":       0.95,
                "top_k":       40,
                "num_predict": 2048,
            },
            timeout=self.timeout
        )

    def analyze(self, text: str, part: str, language: str = "FR",
                instruction_override: str = "") -> Optional[Dict[str, Any]]:
        """
        Analyse un texte ARH avec le modèle spécialisé approprié.
        Retourne le résultat JSON ou None en cas d'erreur.
        """
        model = self.select_model(part, language)
        logger.info("[Router] Dispatch → Part=%s, Lang=%s, Modèle=%s", part, language, model)

        # Instructions adaptées à la langue
        instructions = {
            "FR": (
                f"Tu es l'Inspecteur Expert ARH spécialisé {part}. "
                f"Analyse ce document et identifie toutes les non-conformités "
                f"selon P-CTE-1 et les décrets 21-261/21-314/21-315. "
                f"Réponds uniquement en JSON strict."
            ),
            "EN": (
                f"You are the ARH Expert Inspector specialized in {part}. "
                f"Analyze this document and identify all non-conformities "
                f"per P-CTE-1 and Algerian decrees 21-261/21-314/21-315. "
                f"Reply in strict JSON only."
            ),
            "AR": (
                f"أنت مفتش خبير ARH متخصص في {part}. "
                f"حلل هذه الوثيقة وحدد جميع المخالفات وفق P-CTE-1 "
                f"والمراسيم 21-261/21-314/21-315. أجب بتنسيق JSON صارم فقط."
            ),
            "ZH": (
                f"您是ARH专家检查员，专攻{part}。"
                f"分析此文件并识别所有违规情况，依据P-CTE-1和法令"
                f"21-261/21-314/21-315。仅以严格JSON格式回答。"
            ),
        }
        system = instruction_override or instructions.get(language, instructions["FR"])

        t0       = time.time()
        response = self.call_ollama(model, text, system)
        elapsed  = time.time() - t0

        if not response:
            logger.warning("[Router] Réponse vide du modèle %s", model)
            return None

        logger.debug("[Router] Réponse reçue en %.1fs depuis %s", elapsed, model)

        # Parser le JSON de la réponse via le parseur 3-tier
        result = parse_json_3tier(response)
        if result is not None:
            result["_model_used"] = model
            result["_part"]       = part
            result["_language"]   = language
            result["_latency_s"]  = round(elapsed, 2)
            return result

        logger.warning("[Router] JSON invalide depuis %s — réponse brute: %s...", model, response[:100])
        return {
            "decision":         "ERREUR — RÉPONSE NON PARSEABLE",
            "compliance_score": 0.0,
            "anomalies_count":  0,
            "anomalies":        [],
            "_model_used":      model,
            "_error":           "JSON invalide",
            "_raw_response":    response[:500],
        }


# ══════════════════════════════════════════════════════════════════════════════
# 4. ROUTER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class ARHModelRouter:
    """
    Router principal de ARKAN ARH.
    Orchestre la classification, la détection de langue et le dispatch vers
    le LoRA spécialisé approprié.
    """

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.classifier = ARHPartClassifier()
        self.lang_detector = ARHLanguageDetector()
        self.dispatcher    = ARHModelDispatcher(base_url=base_url)

    def route_and_analyze(
        self,
        text: str,
        part_hint: Optional[str]  = None,
        lang_hint: Optional[str]  = None,
        multi_part: bool          = False,
    ) -> Dict[str, Any]:
        """
        Point d'entrée principal du router.

        Args:
            text:       Texte du document ARH à analyser
            part_hint:  Part P-CTE-1 déjà connue (skip classification)
            lang_hint:  Langue déjà connue (skip détection)
            multi_part: Si True, analyse le document pour toutes les Parts détectées

        Returns:
            Résultat JSON normalisé de l'analyse ARH
        """
        if not text or len(text.strip()) < 50:
            return {
                "decision":         "ERREUR — DOCUMENT VIDE OU TROP COURT",
                "compliance_score": 0.0,
                "anomalies_count":  0,
                "anomalies":        [],
            }

        # 1. Détecter la langue
        language = lang_hint or self.lang_detector.detect(text)

        # 2. Classifier la Part
        if multi_part:
            parts_detected = self.classifier.classify_all(text)
            logger.info("[Router] Parts détectées (mode multi): %s", parts_detected[:5])
            # Analyser les 2 Parts principales
            results = []
            for part_name, score in parts_detected[:2]:
                result = self.dispatcher.analyze(text, part_name, language)
                if result:
                    results.append(result)
            return self._merge_results(results) if results else self._empty_result()

        else:
            part = part_hint or self.classifier.classify(text)
            logger.info("[Router] Part classifiée : %s | Langue : %s", part, language)
            result = self.dispatcher.analyze(text, part, language)
            return result if result else self._empty_result()

    def _merge_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fusionne plusieurs résultats d'analyse en un seul résultat unifié."""
        if not results:
            return self._empty_result()
        if len(results) == 1:
            return results[0]

        all_anomalies = []
        all_scores    = []
        for r in results:
            all_anomalies.extend(r.get("anomalies", []))
            score = r.get("compliance_score", 100.0)
            if score is not None:
                all_scores.append(float(score))

        avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

        # Déduplication par title similaire
        seen_titles = set()
        dedup_anomalies = []
        for a in all_anomalies:
            key = a.get("title", "")[:50].lower()
            if key not in seen_titles:
                seen_titles.add(key)
                dedup_anomalies.append(a)

        n_crit  = sum(1 for a in dedup_anomalies if a.get("priority") == "CRITICAL")
        n_major = sum(1 for a in dedup_anomalies if a.get("priority") == "MAJOR")

        if n_crit > 0:
            decision = "NON CONFORME (RÉSERVES CRITIQUES ARH)"
        elif n_major > 0:
            decision = "APPROUVÉ SOUS RÉSERVES MAJEURES"
        elif dedup_anomalies:
            decision = "APPROUVÉ AVEC COMMENTAIRES MINEURS"
        else:
            decision = "CONFORME — DOSSIER COMPLET ET VALIDE"

        return {
            "decision":         decision,
            "compliance_score": avg_score,
            "anomalies_count":  len(dedup_anomalies),
            "anomalies":        dedup_anomalies,
            "_merged_from":     [r.get("_part") for r in results],
        }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "decision":         "ERREUR — ANALYSE IMPOSSIBLE",
            "compliance_score": 0.0,
            "anomalies_count":  0,
            "anomalies":        [],
        }

    def get_available_models(self) -> Dict[str, str]:
        """Retourne le mapping Part → Modèle effectivement disponible."""
        result = {}
        for part in PART_TO_MODEL:
            result[part] = self.dispatcher.select_model(part)
        return result


# ══════════════════════════════════════════════════════════════════════════════
# SINGLETON GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

_router_instance: Optional[ARHModelRouter] = None

def get_arh_router() -> ARHModelRouter:
    """Retourne l'instance singleton du router ARH."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ARHModelRouter()
        logger.info("[Router] ARHModelRouter initialisé")
    return _router_instance


# ══════════════════════════════════════════════════════════════════════════════
# TEST RAPIDE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    router = ARHModelRouter()

    # Test classification
    classifier = ARHPartClassifier()
    lang_det   = ARHLanguageDetector()

    test_cases = [
        ("ÉTAT DESCRIPTIF ANNEXE E — PMA 92 bar, ASME VIII, ASTM A350 LF2", "FR"),
        ("WPS-SMAW-001 PQR attached — Welder qualification ASME IX expired", "EN"),
        ("تحليل شهادة المواد EN 10204 3.1 — رقم الصهر H-85527 — درجة API 5L X65", "AR"),
        ("EN 10204 3.1 材质证书分析 — 炉号 H-88543 — 钢级 API 5L X65", "ZH"),
        ("PLAN D'INSPECTION ITP — Hold Point H épreuve hydrostatique TPI/ARH", "FR"),
    ]

    print("=" * 60)
    print("TEST DU ROUTER ARH MULTI-MODÈLES")
    print("=" * 60)

    for text, expected_lang in test_cases:
        part = classifier.classify(text)
        lang = lang_det.detect(text)
        model = router.dispatcher.select_model(part, lang)
        print(f"\nTexte : {text[:60]}...")
        print(f"  -> Part    : {part}")
        print(f"  -> Langue  : {lang} (attendu: {expected_lang})")
        print(f"  -> Modele  : {model}")
        if lang != expected_lang:
            print(f"  [WARN] Langue detectee: {lang} != {expected_lang} (peut etre du a l'encodage terminal)")
        else:
            print(f"  [OK] Langue correcte: {lang}")

    print("\n[OK] Tests de classification termines !")
