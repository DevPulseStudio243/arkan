"""
DeerFlow Lite — conversation_memory.py v1.0
Mémoire conversationnelle persistante multi-sessions.

Fonctionnalités :
- Historique complet de toutes les conversations (persistent JSON)
- Résumé automatique des longues sessions pour ne pas surcharger le prompt
- Rappel de contexte pertinent sur demande
- Compatible avec api_enhanced.py via get_conversation_memory()
"""
import json
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ── Chemins ───────────────────────────────────────────────────
MEMORY_DIR = Path("conversation_memory")
MEMORY_DIR.mkdir(exist_ok=True)

SESSIONS_FILE = MEMORY_DIR / "sessions.json"
GLOBAL_HISTORY_FILE = MEMORY_DIR / "global_history.jsonl"   # toutes les questions posées
SUMMARIES_FILE = MEMORY_DIR / "summaries.json"              # résumés par session

_lock = threading.Lock()

MAX_HISTORY_IN_PROMPT = 8        # Nombre de messages à injecter dans le prompt
MAX_SESSION_MESSAGES = 200       # Avant résumé automatique
SUMMARY_TRIGGER = 50             # Résumer tous les 50 messages

# ─────────────────────────────────────────────────────────────
@dataclass
class ConversationTurn:
    """Un échange question/réponse."""
    question: str
    answer: str
    sources: List[str] = field(default_factory=list)
    query_type: str = ""
    grounding: float = 1.0
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    turn_id: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ConversationTurn":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ConversationMemory:
    """
    Moteur de mémoire conversationnelle DeerFlow.
    Stocke TOUTES les conversations dans global_history.jsonl.
    Charge la session courante en RAM pour un accès rapide.
    """

    def __init__(self):
        self._current_session_id: str = self._new_session_id()
        self._session_turns: List[ConversationTurn] = []
        self._sessions_meta: Dict[str, Any] = {}   # {session_id: {start, title, count}}
        self._summaries: Dict[str, str] = {}        # {session_id: résumé}
        self._total_turns: int = 0
        self._load_sessions_meta()
        self._load_summaries()
        logger.info("[Memory] Initialisé — session=%s, %d sessions existantes",
                    self._current_session_id, len(self._sessions_meta))

    # ── Gestion de session ────────────────────────────────────
    @staticmethod
    def _new_session_id() -> str:
        return f"s_{int(time.time())}"

    def new_session(self, title: str = "") -> str:
        """Crée une nouvelle session de conversation."""
        with _lock:
            if self._session_turns:
                self._auto_summarize_if_needed()
            self._current_session_id = self._new_session_id()
            self._session_turns = []
            self._sessions_meta[self._current_session_id] = {
                "start": time.time(),
                "title": title or f"Session {len(self._sessions_meta) + 1}",
                "count": 0,
            }
            self._save_sessions_meta()
            logger.info("[Memory] Nouvelle session: %s", self._current_session_id)
        return self._current_session_id

    def load_session(self, session_id: str) -> bool:
        """Charge une session existante comme session active. Crée la session si elle n'existe pas."""
        with _lock:
            if session_id == self._current_session_id:
                return True
            if session_id in self._sessions_meta:
                if self._session_turns:
                    self._auto_summarize_if_needed()
                self._current_session_id = session_id
                self._session_turns = self._load_turns_for_session(session_id, limit=200)
                logger.info("[Memory] Session active changée pour : %s", session_id)
                return True
            else:
                # Créer une nouvelle session avec cet ID personnalisé
                if self._session_turns:
                    self._auto_summarize_if_needed()
                self._current_session_id = session_id
                self._session_turns = []
                self._sessions_meta[self._current_session_id] = {
                    "start": time.time(),
                    "title": f"Session {len(self._sessions_meta) + 1}",
                    "count": 0,
                }
                self._save_sessions_meta()
                logger.info("[Memory] Session personnalisée créée : %s", session_id)
                return True

    @property
    def current_session_id(self) -> str:
        return self._current_session_id

    # ── Ajout d'un échange ────────────────────────────────────
    def add_turn(
        self,
        question: str,
        answer: str,
        sources: List[str] = None,
        query_type: str = "",
        grounding: float = 1.0,
    ) -> ConversationTurn:
        """Enregistre un échange dans la mémoire."""
        with _lock:
            self._total_turns += 1
            turn = ConversationTurn(
                question=question,
                answer=answer,
                sources=sources or [],
                query_type=query_type,
                grounding=grounding,
                session_id=self._current_session_id,
                turn_id=self._total_turns,
            )
            self._session_turns.append(turn)

            # Mettre à jour le méta session
            meta = self._sessions_meta.setdefault(self._current_session_id, {
                "start": time.time(),
                "title": f"Session {len(self._sessions_meta) + 1}",
                "count": 0,
            })
            meta["count"] = len(self._session_turns)
            # Titre auto = première question (tronquée à 60 car)
            if meta["count"] == 1:
                meta["title"] = question[:60]
            meta["last_activity"] = time.time()

            # Persister globalement (append-only)
            self._append_to_global_history(turn)
            self._save_sessions_meta()

            # Résumé automatique si session longue
            if len(self._session_turns) % SUMMARY_TRIGGER == 0:
                self._auto_summarize_if_needed()

        return turn

    # ── Récupération du contexte pour le prompt ───────────────
    def get_prompt_context(self, last_n: int = MAX_HISTORY_IN_PROMPT, query: str = "") -> str:
        """
        Retourne le contexte de conversation à injecter dans le prompt.
        Format : résumé de session (si long) + N derniers échanges.
        Si une query est fournie, ajoute aussi des résultats cross-sessions.
        """
        with _lock:
            parts = []

            # 1. Résumé de la session si disponible
            summary = self._summaries.get(self._current_session_id, "")
            if summary:
                parts.append(f"[RÉSUMÉ DE SESSION PRÉCÉDENTE]\n{summary}\n")

            # 2. Derniers échanges (les N plus récents)
            recent = self._session_turns[-last_n:] if len(self._session_turns) > last_n else self._session_turns
            if recent:
                parts.append("[HISTORIQUE RÉCENT DE LA CONVERSATION]")
                for turn in recent:
                    # Réponse tronquée à 400 car pour ne pas saturer le contexte
                    answer_short = turn.answer[:400].strip()
                    if len(turn.answer) > 400:
                        answer_short += "..."
                    parts.append(f"Utilisateur: {turn.question}")
                    parts.append(f"Assistant: {answer_short}")
                    parts.append("")

            # 3. Mémoire longue durée : recherche cross-sessions si query fournie
            if query:
                cross_results = self._cross_session_search(query, limit=3)
                if cross_results:
                    parts.append("[MÉMOIRE LONG TERME — Sessions passées pertinentes]")
                    for turn in cross_results:
                        parts.append(f"  (Session passée) Q: {turn.question[:80]}")
                        parts.append(f"  Réponse: {turn.answer[:200]}...")
                        parts.append("")

            return "\n".join(parts) if parts else ""

    def get_session_turns(self, session_id: str = None, limit: int = 50) -> List[ConversationTurn]:
        """Retourne les échanges d'une session."""
        with _lock:
            sid = session_id or self._current_session_id
            if sid == self._current_session_id:
                return list(self._session_turns[-limit:])
            # Session passée → charger depuis le fichier global
            return self._load_turns_for_session(sid, limit)

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Liste toutes les sessions avec leurs métadonnées."""
        with _lock:
            sessions = []
            for sid, meta in sorted(
                self._sessions_meta.items(),
                key=lambda x: x[1].get("start", 0),
                reverse=True,
            ):
                sessions.append({
                    "session_id": sid,
                    "title": meta.get("title", sid),
                    "start": meta.get("start", 0),
                    "count": meta.get("count", 0),
                    "last_activity": meta.get("last_activity", meta.get("start", 0)),
                    "is_current": sid == self._current_session_id,
                })
            return sessions

    def get_stats(self) -> dict:
        """Statistiques de la mémoire conversationnelle."""
        with _lock:
            return {
                "total_sessions": len(self._sessions_meta),
                "current_session_turns": len(self._session_turns),
                "total_turns_all_time": self._total_turns,
                "current_session_id": self._current_session_id,
                "has_summary": self._current_session_id in self._summaries,
            }

    # ── Recherche dans la mémoire ────────────────────────────
    def search_memory(self, query: str, limit: int = 5) -> List[ConversationTurn]:
        """
        Recherche simple par mots-clés dans toutes les conversations passées.
        Retourne les échanges les plus pertinents.
        """
        return self._cross_session_search(query, limit)

    def _cross_session_search(self, query: str, limit: int = 5) -> List[ConversationTurn]:
        """Mémoire longue durée : cherche dans TOUTES les sessions (courante + passées)."""
        stop_words = {
            "quels", "sont", "les", "du", "de", "le", "la", "un", "une", "des", 
            "pour", "dans", "en", "sur", "avec", "et", "ou", "est", "a", "au", "aux", 
            "projet", "equipement", "équipements", "equipements", "liste", "donne", 
            "moi", "quel", "quelle", "quelles", "comment", "pourquoi", "tous", "toutes"
        }
        query_words = set(w for w in query.lower().split() if w not in stop_words)
        if not query_words:
            return []
            
        scored = []

        # Chercher dans la session courante
        for turn in self._session_turns:
            score = self._score_relevance(turn, query_words)
            if score > 0:
                scored.append((score, turn))

        # Chercher dans l'historique global (dernières 1000 lignes pour la mémoire longue durée)
        try:
            if GLOBAL_HISTORY_FILE.exists():
                lines = GLOBAL_HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n")
                for line in lines[-1000:]:  # 1000 au lieu de 500 pour la mémoire longue durée
                    try:
                        d = json.loads(line)
                        turn = ConversationTurn.from_dict(d)
                        if turn.session_id != self._current_session_id:
                            score = self._score_relevance(turn, query_words)
                            if score > 0:
                                scored.append((score, turn))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("[Memory] cross_session_search global scan error: %s", e)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:limit]]

    @staticmethod
    def _score_relevance(turn: ConversationTurn, query_words: set) -> int:
        """Score de pertinence basé sur le nombre de mots en commun."""
        q_words = set(turn.question.lower().split())
        return len(query_words & q_words)

    # ── Résumé automatique ────────────────────────────────────
    def _auto_summarize_if_needed(self):
        """Génère un résumé textuel simple de la session si elle est longue."""
        if len(self._session_turns) < SUMMARY_TRIGGER:
            return
        try:
            turns_to_summarize = self._session_turns[:-MAX_HISTORY_IN_PROMPT]
            summary_lines = []
            for turn in turns_to_summarize:
                summary_lines.append(f"Q: {turn.question[:80]} → {turn.answer[:120]}")
            summary = f"Session commencée avec {len(turns_to_summarize)} échanges précédents:\n" + \
                      "\n".join(summary_lines[-20:])
            self._summaries[self._current_session_id] = summary
            self._save_summaries()
            logger.info("[Memory] Résumé automatique généré (%d échanges condensés)",
                        len(turns_to_summarize))
        except Exception as e:
            logger.debug("[Memory] Auto-summarize error: %s", e)

    # ── Persistance ──────────────────────────────────────────
    def _append_to_global_history(self, turn: ConversationTurn):
        """Ajoute l'échange à l'historique global (append-only JSONL)."""
        try:
            with open(GLOBAL_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("[Memory] append_to_global_history error: %s", e)

    def _load_sessions_meta(self):
        try:
            if SESSIONS_FILE.exists():
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    self._sessions_meta = json.load(f)
                # Compter le total des turns
                self._total_turns = sum(
                    v.get("count", 0) for v in self._sessions_meta.values()
                )
        except Exception as e:
            logger.debug("[Memory] load_sessions_meta error: %s", e)
            self._sessions_meta = {}

    def _save_sessions_meta(self):
        try:
            tmp = SESSIONS_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._sessions_meta, f, ensure_ascii=False, indent=2)
            tmp.replace(SESSIONS_FILE)
        except Exception as e:
            logger.debug("[Memory] save_sessions_meta error: %s", e)

    def _load_summaries(self):
        try:
            if SUMMARIES_FILE.exists():
                with open(SUMMARIES_FILE, "r", encoding="utf-8") as f:
                    self._summaries = json.load(f)
        except Exception as e:
            logger.debug("[Memory] load_summaries error: %s", e)
            self._summaries = {}

    def _save_summaries(self):
        try:
            tmp = SUMMARIES_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._summaries, f, ensure_ascii=False, indent=2)
            tmp.replace(SUMMARIES_FILE)
        except Exception as e:
            logger.debug("[Memory] save_summaries error: %s", e)

    def _load_turns_for_session(self, session_id: str, limit: int) -> List[ConversationTurn]:
        """Charge les turns d'une session passée depuis l'historique global."""
        turns = []
        try:
            if not GLOBAL_HISTORY_FILE.exists():
                return []
            lines = GLOBAL_HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n")
            for line in reversed(lines):
                try:
                    d = json.loads(line)
                    if d.get("session_id") == session_id:
                        turns.append(ConversationTurn.from_dict(d))
                        if len(turns) >= limit:
                            break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("[Memory] load_turns_for_session error: %s", e)
        return list(reversed(turns))


# ── Singleton ──────────────────────────────────────────────────
_memory: Optional[ConversationMemory] = None
_memory_lock = threading.Lock()


def get_conversation_memory() -> ConversationMemory:
    global _memory
    if _memory is None:
        with _memory_lock:
            if _memory is None:
                _memory = ConversationMemory()
    return _memory
