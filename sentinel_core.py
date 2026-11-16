"""
SENTINEL-OG — Couche 2 : Raisonnement Contradictoire (Chain-of-Doubt)
======================================================================
1. Reponse initiale via deepseek-r1
2. Challenge actif : le modele tente de refuter sa propre reponse
3. Verdict final avec score de confiance calibre
"""

import re
import time
import json
import logging
import httpx
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("sentinel_core")

OLLAMA_URL     = "http://localhost:11434/api/generate"
SENTINEL_MODEL = "deepseek-r1:latest"
TIMEOUT_S      = 180
TEMPERATURE    = 0.15

@dataclass
class SentinelResponse:
    question:          str
    reponse_initiale:  str
    challenge_trouve:  str
    verdict:           str        # CONFIRMEE | REVISEE | INCERTAINE
    reponse_finale:    str
    confidence:        float      # 0.0 -> 1.0
    alerte_niveau:     str        # FAIBLE | MOYEN | ELEVE | CRITIQUE
    sources_utilisees: list       = field(default_factory=list)
    action_immediate:  str        = ""
    raisonnement_ms:   int        = 0
    causal_context:    str        = ""

    def to_dict(self):
        return asdict(self)

    def to_display(self):
        lines = [
            "## Analyse Sentinel-OG",
            "",
            f"**Reponse** : {self.reponse_finale}",
            "",
            f"**Confiance** : {int(self.confidence * 100)}%  |  **Alerte** : {self.alerte_niveau}",
        ]
        if self.causal_context:
            lines += ["", "**Incidents similaires (memoire causale)** :", self.causal_context]
        if self.action_immediate:
            lines += ["", f"**Action immediate** : {self.action_immediate}"]
        if self.sources_utilisees:
            lines += ["", "**Sources** : " + " | ".join(self.sources_utilisees[:4])]
        return "\n".join(lines)


SYSTEM_PROMPT = """Tu es SENTINEL-OG, un ingenieur senior Oil & Gas.
Tu es PRECIS, CONCIS et tu cites toujours tes sources.
Tu travailles uniquement avec les informations fournies dans le contexte.
Si une information n est pas dans le contexte, tu dis clairement que tu ne sais pas."""

INITIAL_PROMPT = """CONTEXTE TECHNIQUE :
{context}

QUESTION : {question}

Reponds precisement en t appuyant UNIQUEMENT sur le contexte fourni.
Format :
REPONSE: [ta reponse technique precise]
ACTION: [action immediate recommandee ou Aucune]
ALERTE: [FAIBLE|MOYEN|ELEVE|CRITIQUE]"""

CHALLENGE_PROMPT = """Tu viens de repondre a la question "{question}" :

REPONSE INITIALE : {initial_answer}

Maintenant joue le role d un ingenieur critique.
Essaie ACTIVEMENT de trouver pourquoi cette reponse pourrait etre FAUSSE ou INCOMPLETE.

Format :
CHALLENGE: [le meilleur argument contre ta reponse initiale]
VERDICT: [CONFIRMEE|REVISEE|INCERTAINE]
CORRECTION: [version corrigee si REVISEE, sinon reproduis la reponse initiale]"""


class SentinelCore:
    """Moteur Chain-of-Doubt : genere une reponse puis tente de la refuter."""

    def __init__(self, model: str = SENTINEL_MODEL):
        self.model  = model
        self.client = httpx.Client(timeout=TIMEOUT_S)

    def _call_llm(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": TEMPERATURE, "num_ctx": 8192, "num_predict": 1024},
        }
        try:
            resp = self.client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        except Exception as e:
            logger.error(f"[SentinelCore] LLM error: {e}")
            return ""

    def _parse_initial(self, raw):
        answer, action, alerte = "", "Aucune", "FAIBLE"
        for line in raw.splitlines():
            if line.startswith("REPONSE:"):
                answer = line.split(":", 1)[1].strip()
            elif line.startswith("ACTION:"):
                action = line.split(":", 1)[1].strip()
            elif line.startswith("ALERTE:"):
                a = line.split(":", 1)[1].strip().upper()
                if a in ("FAIBLE", "MOYEN", "ELEVE", "CRITIQUE"):
                    alerte = a
        return answer or raw[:1500].strip(), action, alerte

    def _parse_challenge(self, raw, initial_answer):
        challenge, verdict, correction = "", "INCERTAINE", initial_answer
        for line in raw.splitlines():
            if line.startswith("CHALLENGE:"):
                challenge = line.split(":", 1)[1].strip()
            elif line.startswith("VERDICT:"):
                v = line.split(":", 1)[1].strip().upper()
                if v in ("CONFIRMEE", "REVISEE", "INCERTAINE"):
                    verdict = v
            elif line.startswith("CORRECTION:"):
                correction = line.split(":", 1)[1].strip()
        return challenge or raw[:500].strip(), verdict, correction or initial_answer

    def _confidence(self, verdict, alerte):
        base    = {"CONFIRMEE": 0.87, "REVISEE": 0.68, "INCERTAINE": 0.45}.get(verdict, 0.50)
        penalty = {"CRITIQUE": 0.10, "ELEVE": 0.05, "MOYEN": 0.02, "FAIBLE": 0.0}.get(alerte, 0.0)
        return round(max(0.10, min(0.99, base - penalty)), 2)

    def reason(self, question: str, context: str, sources=None, causal_context: str = "") -> SentinelResponse:
        """Raisonnement complet Chain-of-Doubt."""
        t0      = time.time()
        sources = sources or []
        full_ctx = context
        if causal_context:
            full_ctx = f"INCIDENTS SIMILAIRES :\n{causal_context}\n\n---\n\nDOCUMENTS TECHNIQUES :\n{context}"

        logger.info("[Sentinel] Etape 1 : reponse initiale...")
        raw1 = self._call_llm(INITIAL_PROMPT.format(context=full_ctx[:6000], question=question))
        initial, action, alerte = self._parse_initial(raw1)

        logger.info("[Sentinel] Etape 2 : chain-of-doubt...")
        raw2 = self._call_llm(CHALLENGE_PROMPT.format(question=question, initial_answer=initial))
        challenge, verdict, final = self._parse_challenge(raw2, initial)

        confidence = self._confidence(verdict, alerte)
        elapsed_ms = int((time.time() - t0) * 1000)
        logger.info(f"[Sentinel] Verdict={verdict} | Confiance={confidence:.0%} | {elapsed_ms}ms")

        return SentinelResponse(
            question=question, reponse_initiale=initial,
            challenge_trouve=challenge, verdict=verdict,
            reponse_finale=final, confidence=confidence,
            alerte_niveau=alerte, sources_utilisees=sources,
            action_immediate=action if action.lower() != "aucune" else "",
            raisonnement_ms=elapsed_ms, causal_context=causal_context,
        )

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


_instance: Optional[SentinelCore] = None

def get_sentinel() -> SentinelCore:
    global _instance
    if _instance is None:
        _instance = SentinelCore()
    return _instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    ctx = """
    La pression differentielle maximale sur le separateur T-201 est de 2.5 bar.
    En cas de depassement, la vanne PCV-101 doit s ouvrir automatiquement.
    Si la pression continue, declencher la procedure LOTO-T201.
    Cause frequente : colmatage du panier filtrant (ref : PM-T201-04).
    """
    q = "La pression differentielle sur T-201 est a 3.1 bar. Que faire ?"
    with SentinelCore() as s:
        r = s.reason(question=q, context=ctx,
                     sources=["Manuel T-201", "Procedure LOTO"],
                     causal_context="Incident 2022-03 : dP 2.9 bar -> colmatage -> nettoyage 4h")
        print(r.to_display())
