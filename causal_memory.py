"""
SENTINEL-OG — Couche 1 : Memoire Causale
=========================================
Indexe les incidents passes et retrouve les chaines causales
similaires a la situation courante.

Architecture :
  - Stockage : SQLite (knowledge_graph.db existant)
  - Recherche : hybride texte + similarite causal
  - Sorties   : incidents similaires + chaine causale + probabilites
"""

import re
import time
import json
import sqlite3
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("causal_memory")

DB_PATH = Path(__file__).parent / "knowledge_graph.db"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sentinel_incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    situation   TEXT NOT NULL,
    symptomes   TEXT NOT NULL,
    causes      TEXT NOT NULL,
    resolution  TEXT NOT NULL,
    severite    TEXT DEFAULT 'MOYEN',
    duree_h     REAL DEFAULT 0,
    equipement  TEXT DEFAULT '',
    created_at  REAL DEFAULT (unixepoch()),
    confirmed   INTEGER DEFAULT 0
);
"""

SEED_INCIDENTS = [
    {
        "situation":  "Pression differentielle haute sur separateur triphasique",
        "symptomes":  "DP monte progressivement, debit stable, temperature normale",
        "causes":     "Colmatage panier filtrant inlet, accumulation de paraffine",
        "resolution": "Arret planifie, demontage et nettoyage du panier filtrant, inspection interne",
        "severite":   "MOYEN",
        "duree_h":    4.0,
        "equipement": "T-201 separateur triphasique",
    },
    {
        "situation":  "Pompe centrifuge en vibration excessive avec cavitation",
        "symptomes":  "Vibration >7 mm/s, bruit de cavitation, pression aspiration basse",
        "causes":     "NPSH insuffisant, vanne aspiration partiellement fermee, debit trop eleve",
        "resolution": "Reduire debit, verifier vanne aspiration, controler niveau bac aspiration",
        "severite":   "ELEVE",
        "duree_h":    1.5,
        "equipement": "P-101 pompe centrifuge",
    },
    {
        "situation":  "Surchauffe palier moteur electrique",
        "symptomes":  "Temperature palier >85C, vibration legere, consommation electrique stable",
        "causes":     "Manque de graisse, contamination roulement, mauvais alignement",
        "resolution": "Graissage d urgence, controle alignement laser, remplacement roulement si necessaire",
        "severite":   "ELEVE",
        "duree_h":    2.0,
        "equipement": "Moteur electrique pompe",
    },
    {
        "situation":  "Vanne de controle de pression en oscillation (hunting)",
        "symptomes":  "PCV en mode auto oscille, debit instable, pression fluctuante +/-0.3 bar",
        "causes":     "Gain PID trop eleve, actuateur pneumatique use, signal positionneur derive",
        "resolution": "Passer en mode manuel, ajuster PID, calibrer positionneur",
        "severite":   "MOYEN",
        "duree_h":    0.5,
        "equipement": "PCV-101 vanne de controle",
    },
    {
        "situation":  "Perte d etancheite joint mecanique pompe",
        "symptomes":  "Fuite visible au joint mecanique, alarme temperature palier, odeur HC",
        "causes":     "Usure faces joint, cavitation prolongee, contamination fluide",
        "resolution": "Arret d urgence pompe, isolation LOTO, remplacement joint mecanique",
        "severite":   "CRITIQUE",
        "duree_h":    8.0,
        "equipement": "P-101 P-102 pompes process",
    },
    {
        "situation":  "Alarme haute temperature echangeur de chaleur",
        "symptomes":  "T sortie >design +15%, efficacite thermique chutee, DP augmentee",
        "causes":     "Encrassement faisceaux tubulaires, debit eau de refroidissement insuffisant",
        "resolution": "Nettoyage chimique ou mecanique des faisceaux, controle debit eau froide",
        "severite":   "MOYEN",
        "duree_h":    6.0,
        "equipement": "E-201 E-202 echangeurs",
    },
]


@dataclass
class Incident:
    id:          int
    situation:   str
    symptomes:   str
    causes:      str
    resolution:  str
    severite:    str
    duree_h:     float
    equipement:  str
    similarite:  float = 0.0

    def to_text(self) -> str:
        return (
            f"- **Situation** : {self.situation}\n"
            f"  **Symptomes** : {self.symptomes}\n"
            f"  **Cause** : {self.causes}\n"
            f"  **Resolution** : {self.resolution}  "
            f"[Severite: {self.severite} | Duree: {self.duree_h}h]"
        )


class CausalMemory:
    """
    Memoire causale de Sentinel-OG.
    Retrouve les incidents similaires et construit la chaine causale.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._conn   = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.execute(CREATE_TABLE)
        self._conn.commit()
        # Inserer les incidents de seed si la table est vide
        count = self._conn.execute("SELECT COUNT(*) FROM sentinel_incidents").fetchone()[0]
        if count == 0:
            logger.info("[CausalMemory] Insertion des incidents de reference...")
            for inc in SEED_INCIDENTS:
                self._conn.execute(
                    "INSERT INTO sentinel_incidents (situation,symptomes,causes,resolution,severite,duree_h,equipement,confirmed) VALUES (?,?,?,?,?,?,?,1)",
                    (inc["situation"], inc["symptomes"], inc["causes"], inc["resolution"],
                     inc["severite"], inc["duree_h"], inc["equipement"])
                )
            self._conn.commit()
            logger.info(f"[CausalMemory] {len(SEED_INCIDENTS)} incidents de reference inseres.")

    def _tokenize(self, text: str) -> set:
        """Tokenisation simple pour similarite lexicale."""
        tokens = re.findall(r"[a-zA-Z0-9\-]+", text.lower())
        stopwords = {"le","la","les","de","du","des","un","une","et","ou","en","sur","avec",
                     "pour","par","est","sont","dans","au","aux","ce","se","si"}
        return {t for t in tokens if t not in stopwords and len(t) > 2}

    def _jaccard(self, a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def find_similar_incidents(self, query: str, top_k: int = 3) -> list[Incident]:
        """
        Retrouve les incidents les plus similaires a la situation courante.
        Utilise une similarite hybride : Jaccard sur mots-cles + bonus severite.
        """
        query_tokens = self._tokenize(query)
        rows = self._conn.execute(
            "SELECT id,situation,symptomes,causes,resolution,severite,duree_h,equipement FROM sentinel_incidents"
        ).fetchall()

        scored = []
        for row in rows:
            id_, sit, sym, cau, res, sev, dur, eq = row
            combined_tokens = self._tokenize(f"{sit} {sym} {cau} {eq}")
            score = self._jaccard(query_tokens, combined_tokens)
            scored.append((score, Incident(id=id_, situation=sit, symptomes=sym,
                                           causes=cau, resolution=res, severite=sev,
                                           duree_h=dur, equipement=eq, similarite=round(score,3))))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [inc for score, inc in scored[:top_k] if score > 0.05]

    def build_causal_context(self, query: str, top_k: int = 3) -> str:
        """
        Construit le texte de contexte causal pour injection dans sentinel_core.
        Retourne une chaine vide si aucun incident similaire n est trouve.
        """
        incidents = self.find_similar_incidents(query, top_k=top_k)
        if not incidents:
            return ""
        lines = [f"**{len(incidents)} incident(s) similaire(s) dans la base** :"]
        for i, inc in enumerate(incidents, 1):
            lines.append(f"\n**Incident {i}** (similarite: {inc.similarite:.0%}) :")
            lines.append(inc.to_text())
        return "\n".join(lines)

    def store_incident(self, situation: str, symptomes: str, causes: str,
                       resolution: str, severite: str = "MOYEN",
                       duree_h: float = 0.0, equipement: str = "") -> int:
        """Enregistre un nouvel incident dans la base causale."""
        cur = self._conn.execute(
            "INSERT INTO sentinel_incidents (situation,symptomes,causes,resolution,severite,duree_h,equipement) VALUES (?,?,?,?,?,?,?)",
            (situation, symptomes, causes, resolution, severite, duree_h, equipement)
        )
        self._conn.commit()
        logger.info(f"[CausalMemory] Incident {cur.lastrowid} enregistre.")
        return cur.lastrowid

    def get_all_incidents(self) -> list[Incident]:
        rows = self._conn.execute(
            "SELECT id,situation,symptomes,causes,resolution,severite,duree_h,equipement FROM sentinel_incidents ORDER BY created_at DESC"
        ).fetchall()
        return [Incident(id=r[0], situation=r[1], symptomes=r[2], causes=r[3],
                         resolution=r[4], severite=r[5], duree_h=r[6], equipement=r[7])
                for r in rows]

    def close(self):
        self._conn.close()


_causal_instance: Optional[CausalMemory] = None

def get_causal_memory() -> CausalMemory:
    global _causal_instance
    if _causal_instance is None:
        _causal_instance = CausalMemory()
    return _causal_instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cm = CausalMemory()
    test = "Pression differentielle haute sur T-201, debit stable"
    ctx  = cm.build_causal_context(test)
    print("=== CONTEXTE CAUSAL GENERE ===")
    print(ctx if ctx else "(aucun incident similaire trouve)")
    all_inc = cm.get_all_incidents()
    print(f"\n{len(all_inc)} incidents dans la base.")
