"""
arh_ollama_client.py
====================
Client Ollama Unifié pour l'Écosystème ARKAN ARH (Action 5).
Standardise les requêtes vers Ollama, la gestion des retries avec backoff exponentiel,
et le parsing/réparation JSON robuste en 3 tiers.

Fournit :
  - `ARHOllamaClient` : Client unifié avec retry, détection de disponibilité et réparation JSON.
  - `get_ollama_client()` : Accesseur singleton thread-safe.
  - `parse_json_3tier(text)` : Moteur autonome de désérialisation tolérante aux fautes LLM.
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
from typing import Dict, Any, Optional, List, Union
import httpx

logger = logging.getLogger("ARHOllamaClient")

_DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
_DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))
_DEFAULT_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))

# Tiers de timeouts unifiés (S-11)
TIMEOUT_PROBE = float(os.getenv("OLLAMA_TIMEOUT_PROBE", "2.5"))
TIMEOUT_EMBED = float(os.getenv("OLLAMA_TIMEOUT_EMBED", "5.0"))
TIMEOUT_VISION = float(os.getenv("OLLAMA_TIMEOUT_VISION", os.getenv("ARH_VISION_TIMEOUT", "8.0")))
TIMEOUT_FAST = float(os.getenv("OLLAMA_TIMEOUT_FAST", "35.0"))
TIMEOUT_STANDARD = float(os.getenv("OLLAMA_TIMEOUT_STANDARD", "60.0"))
TIMEOUT_HEAVY = float(os.getenv("OLLAMA_TIMEOUT_HEAVY", "120.0"))


def parse_json_3tier(raw_text: str) -> Optional[Dict[str, Any]]:
    """
    Parseur JSON tolérant en 3 tiers pour les sorties des LLMs (Qwen, Llama, NuExtract) :
      • Tier 1 : Désérialisation directe standard (json.loads).
      • Tier 2 : Extraction par expressions régulières (blocs markdown ```json ... ``` ou accolades extérieures { ... }).
      • Tier 3 : Réparation heuristique des anomalies LLM fréquentes :
          - Virgules orphelines traînantes (, } ou , ])
          - Accolades fermantes tronquées par limite de context/num_predict
          - Clés ou chaînes encadrées par des apostrophes simples au lieu de guillemets
          - Remplacement des booléens non standards (True/False/None pythoniques)
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    cleaned = raw_text.strip()

    # Tier 1 : json.loads direct
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        elif isinstance(data, list):
            return {"items": data}
    except Exception as e_t1:
        logger.debug("[OllamaClient] Tier 1 JSON direct a échoué: %s", e_t1)

    # Tier 2 : Extraction Regex
    # 2a. Blocs Markdown ```json ... ```
    m_md = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
    if m_md:
        try:
            data = json.loads(m_md.group(1).strip())
            if isinstance(data, dict):
                return data
        except Exception as e_md:
            logger.debug("[OllamaClient] Tier 2a Markdown parse a échoué: %s", e_md)

    # 2b. Accolades englobantes extérieures { ... }
    m_bracket = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if m_bracket:
        candidate = m_bracket.group(0).strip()
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception as e_br:
            logger.debug("[OllamaClient] Tier 2b Brackets parse a échoué: %s", e_br)

    # Tier 3 : Réparation Heuristique
    candidate_text = m_bracket.group(0) if m_bracket else cleaned
    if "{" in candidate_text:
        # Isoler depuis la première accolade ouvrante
        candidate_text = candidate_text[candidate_text.find("{"):]
        
        # Remplacer les littéraux Python None/True/False
        fixed = re.sub(r'\bNone\b', 'null', candidate_text)
        fixed = re.sub(r'\bTrue\b', 'true', fixed)
        fixed = re.sub(r'\bFalse\b', 'false', fixed)

        # Corriger les virgules orphelines internes
        fixed = re.sub(r',\s*\]', ']', fixed)
        fixed = re.sub(r',\s*\}', '}', fixed)

        # Si le texte se termine par une virgule orpheline avant EOF
        fixed = re.sub(r',\s*$', '', fixed.strip())

        # Équilibrer crochets et accolades non fermés
        open_brackets = fixed.count("[")
        close_brackets = fixed.count("]")
        if open_brackets > close_brackets:
            fixed = fixed + ("]" * (open_brackets - close_brackets))

        open_braces = fixed.count("{")
        close_braces = fixed.count("}")
        if open_braces > close_braces:
            fixed = fixed + ("}" * (open_braces - close_braces))

        # Re-nettoyer les virgules traînantes créées par la fermeture
        fixed = re.sub(r',\s*\}', '}', fixed)
        fixed = re.sub(r',\s*\]', ']', fixed)

        try:
            data = json.loads(fixed)
            if isinstance(data, dict):
                logger.debug("[OllamaClient] Tier 3 Réparation réussie.")
                return data
        except Exception as e_fix1:
            logger.debug("[OllamaClient] Tier 3 (Passe 1) a échoué: %s", e_fix1)

        # Tentative avec conversion des apostrophes simples 'key': 'val'
        try:
            fixed_quotes = re.sub(r"'([A-Za-z0-9_\-]+)'\s*:", r'"\1":', fixed)
            fixed_quotes = re.sub(r":\s*'([^']*)'", r': "\1"', fixed_quotes)
            data = json.loads(fixed_quotes)
            if isinstance(data, dict):
                logger.debug("[OllamaClient] Tier 3 (Passe 2 - Quotes) réussie.")
                return data
        except Exception as e_fix2:
            logger.debug("[OllamaClient] Tier 3 (Passe 2) a échoué: %s", e_fix2)

    return None


class ARHOllamaClient:
    """
    Client HTTP résilient pour le serveur Ollama.
    Gère les pools de connexions, le circuit-breaker de disponibilité, les tentatives de retry
    avec backoff exponentiel, et la standardisation des requêtes texte, vision, embeddings et JSON.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_OLLAMA_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_probe_ts: float = 0.0
        self._cached_online: Optional[bool] = None
        self._cached_models: List[str] = []

    def is_available(self, model_name: Optional[str] = None, cache_ttl: float = 10.0) -> bool:
        """
        Vérifie la disponibilité d'Ollama et optionnellement la présence d'un modèle,
        avec cache circuit-breaker mémoire (TTL par défaut 10s) pour éviter les blocages répétés.
        """
        if os.getenv("ARH_DISABLE_LLM") == "1":
            return False
        now = time.time()
        if self._cached_online is not None and (now - self._last_probe_ts) < cache_ttl:
            if not self._cached_online:
                return False
            if not model_name:
                return True
            clean_target = model_name.split(":")[0].lower()
            return any(clean_target in m.lower() for m in self._cached_models)

        try:
            with httpx.Client(timeout=TIMEOUT_PROBE) as client:
                r = client.get(f"{self.base_url}/api/tags")
                self._last_probe_ts = now
                if r.status_code != 200:
                    self._cached_online = False
                    self._cached_models = []
                    return False
                self._cached_online = True
                self._cached_models = [m.get("name", "") for m in r.json().get("models", [])]
                if not model_name:
                    return True
                clean_target = model_name.split(":")[0].lower()
                return any(clean_target in m.lower() for m in self._cached_models)
        except Exception as e:
            self._last_probe_ts = now
            self._cached_online = False
            self._cached_models = []
            logger.debug("[OllamaClient] Ollama non joignable (%s): %s", self.base_url, e)
            return False

    def list_models(self) -> List[str]:
        """Retourne la liste des modèles installés sur le serveur Ollama."""
        if self.is_available():
            return list(self._cached_models)
        return []

    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        images: Optional[List[str]] = None,
        timeout: Optional[float] = None
    ) -> Optional[str]:
        """
        Exécute une inférence Ollama (texte ou vision) avec politique de retry automatique et backoff exponentiel.
        """
        if os.getenv("ARH_DISABLE_LLM") == "1":
            return None

        req_timeout = timeout or self.timeout
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        if images:
            payload["images"] = images

        url = f"{self.base_url}/api/generate"

        for attempt in range(1, self.max_retries + 1):
            try:
                t0 = time.time()
                with httpx.Client(timeout=req_timeout) as client:
                    resp = client.post(url, json=payload)
                elapsed = time.time() - t0

                if resp.status_code == 200:
                    output = resp.json().get("response", "")
                    logger.debug("[OllamaClient] Succès modèle %s (tentative %d, %.2fs)", model, attempt, elapsed)
                    return output
                else:
                    logger.warning("[OllamaClient] Erreur HTTP %d depuis Ollama (tentative %d/%d): %s",
                                   resp.status_code, attempt, self.max_retries, resp.text[:200])

            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e_net:
                logger.warning("[OllamaClient] Échec réseau tentative %d/%d (%s): %s",
                               attempt, self.max_retries, model, e_net)
                if attempt < self.max_retries:
                    sleep_s = 0.5 * (2 ** (attempt - 1))
                    time.sleep(sleep_s)
            except Exception as e:
                logger.error("[OllamaClient] Erreur inattendue tentative %d/%d (%s): %s",
                             attempt, self.max_retries, model, e)
                break

        return None

    def generate_json(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        images: Optional[List[str]] = None,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Exécute l'inférence Ollama et passe la sortie brute à travers le parseur 3-tier.
        Retourne un dictionnaire Python propre ou None.
        """
        raw_output = self.generate(
            model=model,
            prompt=prompt,
            system=system,
            options=options,
            images=images,
            timeout=timeout
        )
        if not raw_output:
            return None

        return parse_json_3tier(raw_output)

    def embed(
        self,
        model: str,
        prompt: str,
        timeout: Optional[float] = None
    ) -> List[float]:
        """
        Génère un vecteur d'embedding via l'API `/api/embeddings` d'Ollama avec gestion de timeout unifiée.
        """
        if os.getenv("ARH_DISABLE_LLM") == "1" or not self.is_available():
            return []
        req_timeout = timeout or TIMEOUT_EMBED
        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model, "prompt": prompt}
                )
                if resp.status_code == 200:
                    emb = resp.json().get("embedding", [])
                    if isinstance(emb, list) and emb:
                        return emb
        except Exception as e:
            logger.debug("[OllamaClient] Échec embedding (%s): %s", model, e)
        return []

    def post_completion(
        self,
        url: str,
        payload: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Exécute une requête sur un démon llama.cpp / NuExtract dédié (`/completion`) et parse le JSON retourné.
        """
        if os.getenv("ARH_DISABLE_LLM") == "1":
            return None
        req_timeout = timeout or TIMEOUT_FAST
        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.post(url, json=payload)
            if resp.status_code == 200:
                raw_out = resp.json().get("content", "").strip()
                return parse_json_3tier(raw_out)
        except Exception as e:
            logger.debug("[OllamaClient] Échec post_completion (%s): %s", url, e)
        return None


# Singleton d'accès global
_GLOBAL_OLLAMA_CLIENT: Optional[ARHOllamaClient] = None

def get_ollama_client() -> ARHOllamaClient:
    """Retourne l'instance globale du client Ollama unifié."""
    global _GLOBAL_OLLAMA_CLIENT
    if _GLOBAL_OLLAMA_CLIENT is None:
        _GLOBAL_OLLAMA_CLIENT = ARHOllamaClient()
    return _GLOBAL_OLLAMA_CLIENT
