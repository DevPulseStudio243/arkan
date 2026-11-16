# ============================================================
#  DEERFLOW LITE - Classification documentaire Oil & Gas
#  Classification par règles des documents techniques
# ============================================================

import re
import logging

logger = logging.getLogger(__name__)

# ── Disciplines Oil & Gas ───────────────────────────────────

DISCIPLINES = {
    "process": {
        "keywords": [
            "PFD", "P&ID", "PID", "process flow", "process description",
            "heat and material balance", "HMB", "simulation", "HYSYS",
            "operating conditions", "design basis", "process datasheet",
            "ligne de process", "schéma de procédé", "bilan matière",
            "conditions opératoires", "pression de design", "température",
        ],
        "doc_patterns": [
            r"D-\d{3}-13\d{2}",   # Process docs numbering
            r"PFD[-_]",
            r"PID[-_]",
        ],
    },
    "mechanical": {
        "keywords": [
            "equipment datasheet", "vessel", "heat exchanger", "pump",
            "compressor", "tank", "pressure vessel", "ASME", "TEMA",
            "mechanical design", "nozzle", "shell", "tube", "baffle",
            "fiche technique", "échangeur", "pompe", "compresseur",
            "ballon", "réservoir", "capacité",
        ],
        "doc_patterns": [
            r"D-\d{3}-12\d{2}",
            r"MDS[-_]",
        ],
    },
    "piping": {
        "keywords": [
            "piping", "pipeline", "isometric", "ISO", "line list",
            "pipe spec", "valve", "fitting", "flange", "gasket",
            "stress analysis", "Caesar", "tuyauterie", "robinet",
            "bride", "joint", "supportage", "classe de tuyauterie",
        ],
        "doc_patterns": [
            r"D-\d{3}-15\d{2}",
            r"ISO[-_]",
            r"PIPE[-_]",
        ],
    },
    "instrumentation": {
        "keywords": [
            "instrument", "control", "SIS", "SIF", "SIL", "P&ID",
            "DCS", "PLC", "instrument datasheet", "control valve",
            "transmitter", "sensor", "alarm", "trip", "interlock",
            "boucle de régulation", "vanne de contrôle", "capteur",
            "détecteur", "automate",
        ],
        "doc_patterns": [
            r"D-\d{3}-20\d{2}",
            r"INST[-_]",
        ],
    },
    "electrical": {
        "keywords": [
            "electrical", "power", "MCC", "switchgear", "transformer",
            "cable", "single line diagram", "SLD", "motor", "VFD",
            "hazardous area", "ATEX", "classification zone",
            "électrique", "puissance", "câble", "transformateur",
            "tableau électrique", "moteur",
        ],
        "doc_patterns": [
            r"D-\d{3}-21\d{2}",
            r"ELEC[-_]",
            r"SLD[-_]",
        ],
    },
    "civil": {
        "keywords": [
            "civil", "structural", "foundation", "concrete", "steel",
            "building", "layout", "plot plan", "génie civil",
            "fondation", "béton", "charpente", "structure",
            "implantation",
        ],
        "doc_patterns": [
            r"D-\d{3}-22\d{2}",
            r"CIV[-_]",
            r"STR[-_]",
        ],
    },
    "safety": {
        "keywords": [
            "safety", "HAZOP", "HAZID", "SIL", "LOPA", "fire",
            "explosion", "flare", "relief", "PSV", "rupture disc",
            "sécurité", "incendie", "explosion", "torche", "soupape",
            "étude de danger", "analyse de risque",
        ],
        "doc_patterns": [
            r"D-\d{3}-00\d{2}",
            r"HAZ[-_]",
            r"SAF[-_]",
        ],
    },
    "general": {
        "keywords": [
            "project", "schedule", "planning", "specification",
            "standard", "procedure", "scope of work", "ITB",
            "projet", "planning", "spécification", "norme",
            "procédure", "cahier des charges",
        ],
        "doc_patterns": [
            r"D-\d{3}-00\d{2}",
        ],
    },
}


def classify_document(text: str, filename: str = "") -> dict:
    """
    Classifie un document Oil & Gas par discipline.
    Retourne {discipline: str, confidence: float, matched_keywords: list}
    """
    text_lower = text.lower()
    filename_lower = filename.lower()
    scores = {}

    for discipline, config in DISCIPLINES.items():
        score = 0
        matched = []

        # Vérifier les mots-clés
        for kw in config["keywords"]:
            if kw.lower() in text_lower:
                score += 1
                matched.append(kw)

        # Vérifier les patterns de nom de document
        for pattern in config["doc_patterns"]:
            if re.search(pattern, filename, re.IGNORECASE):
                score += 3  # Bonus fort pour le pattern du nom
                matched.append(f"filename:{pattern}")
            if re.search(pattern, text[:500], re.IGNORECASE):
                score += 1
                matched.append(f"content:{pattern}")

        if score > 0:
            scores[discipline] = {"score": score, "matched": matched}

    if not scores:
        return {
            "discipline": "general",
            "confidence": 0.1,
            "matched_keywords": [],
        }

    # Trouver la discipline avec le meilleur score
    best = max(scores.items(), key=lambda x: x[1]["score"])
    total_possible = len(DISCIPLINES[best[0]]["keywords"]) + len(
        DISCIPLINES[best[0]]["doc_patterns"]
    ) * 3
    confidence = min(best[1]["score"] / max(total_possible * 0.3, 1), 1.0)

    return {
        "discipline": best[0],
        "confidence": round(confidence, 2),
        "matched_keywords": best[1]["matched"],
    }


def get_discipline_context(discipline: str) -> str:
    """Retourne le contexte de la discipline pour enrichir les prompts."""
    contexts = {
        "process": "Domaine: Procédé / Process. Focus sur les conditions opératoires, bilans matière, P&ID.",
        "mechanical": "Domaine: Mécanique / Équipements. Focus sur les datasheets, ASME, TEMA, dimensionnement.",
        "piping": "Domaine: Tuyauterie / Piping. Focus sur les specs, isométriques, stress analysis.",
        "instrumentation": "Domaine: Instrumentation & Contrôle. Focus sur les boucles, SIS/SIF, datasheets instruments.",
        "electrical": "Domaine: Électricité. Focus sur les SLD, classification de zone, dimensionnement câbles.",
        "civil": "Domaine: Génie Civil / Structure. Focus sur les fondations, structures, implantation.",
        "safety": "Domaine: Sécurité / HSE. Focus sur HAZOP, SIL, protection incendie, soupapes.",
        "general": "Domaine: Général projet. Documentation transverse.",
    }
    return contexts.get(discipline, contexts["general"])


# ── Classifieur ML (chargement automatique si modèle entraîné disponible) ──

import pickle as _pickle
import os as _os

_ML_CLASSIFIER = None
_ML_CLASSIFIER_PATH = _os.path.join(
    _os.environ.get("ARKAN_BASE_DIR", _os.environ.get("DEERFLOW_BASE_DIR", ".")),
    "models", "classifier_oil_gas", "classifier_model.pkl"
)
_ML_TRIED = False


def _load_ml_classifier():
    """Charge le classifieur ML si disponible (chargement paresseux thread-safe)."""
    global _ML_CLASSIFIER, _ML_TRIED
    if _ML_TRIED:
        return _ML_CLASSIFIER
    _ML_TRIED = True
    if _os.path.exists(_ML_CLASSIFIER_PATH):
        try:
            with open(_ML_CLASSIFIER_PATH, "rb") as _f:
                _ML_CLASSIFIER = _pickle.load(_f)
            logger.info("Classifieur ML Oil & Gas charge: %s", _ML_CLASSIFIER_PATH)
        except Exception as _e:
            logger.warning("Classifieur ML non disponible: %s", _e)
    return _ML_CLASSIFIER


def classify_document_ml(text: str, filename: str = "") -> dict:
    """
    Classifie un document en utilisant le modèle ML fine-tune si disponible,
    sinon bascule sur les regles (classify_document).

    Priorite : ML > regles.
    """
    import numpy as _np

    clf = _load_ml_classifier()
    if clf is None:
        return classify_document(text, filename)

    try:
        label = clf.predict([text[:2000]])[0]
        confidence = 0.75
        try:
            if hasattr(clf, "predict_proba"):
                proba = clf.predict_proba([text[:2000]])[0]
                confidence = float(max(proba))
            elif hasattr(clf, "decision_function"):
                decision = clf.decision_function([text[:2000]])[0]
                if hasattr(decision, "__len__"):
                    confidence = float(1.0 / (1.0 + _np.exp(-float(max(decision)))))
                else:
                    confidence = float(1.0 / (1.0 + _np.exp(-float(decision))))
        except Exception:
            pass
        return {
            "discipline": label,
            "confidence": round(confidence, 2),
            "matched_keywords": [],
            "method": "ml_classifier",
        }
    except Exception as e:
        logger.warning("Erreur classifieur ML: %s", e)
        return classify_document(text, filename)
