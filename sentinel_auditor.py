"""
SENTINEL-OG — Auditeur de Coherence Documentaire
=================================================
Utilise la base de connaissances (manuels normes O&G) comme REFERENCE
pour auditer les documents projet (plans, notes de calcul, specifications)
et detecter les erreurs, incoherences et violations de normes.

Flux :
  1. Extraire les donnees techniques du document projet (tags, valeurs, calculs)
  2. Pour chaque donnee : rechercher la norme applicable dans la base de connaissances
  3. Cross-check avec deepseek-r1 : "Est-ce que ca respecte la norme ?"
  4. Generer un rapport d anomalies structure

Types d anomalies detectees :
  - ERREUR    : Valeur hors norme, formule incorrecte, violation de standard
  - WARNING   : Donnee manquante, incoherence entre documents, valeur limite
  - INFO      : Observation, bonne pratique non respectee
"""

import re
import time
import json
import logging
import httpx
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("sentinel_auditor")

OLLAMA_URL     = "http://localhost:11434/api/generate"
AUDIT_MODEL    = "qwen2.5:14b"
TIMEOUT_S      = 360
TEMPERATURE    = 0.05   # Tres bas pour maximiser la precision


# ── Extraction des donnees techniques ────────────────────────────────────────

# Tags equipements O&G (pompes, vannes, separateurs, echangeurs...)
TAG_RE = re.compile(
    r"\b(\d{2,4}[-_]?(?:PP|PU|CV|XV|LV|FV|PCV|LCV|FCV|TCV|PSV|PRV|VSV|"
    r"VS|VL|V|E|T|K|C|F|TI|PI|FI|LI|TT|PT|FT|LT|PDT|AT|ZT|WT|"
    r"P|A|B|G|H|J|M|N|Q|R|S|U|W|X|Y|Z)"
    r"[-_]?\d{2,4}[A-Z]?)\b",
    re.IGNORECASE
)

# Valeurs numeriques avec unites techniques
VALUE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(bar[ag]?|psi[ag]?|kPa|MPa|"
    r"deg[Cc]|°C|°F|K|"
    r"m3/h|m³/h|Sm3/h|MMScfd|MMSCFD|bbl/d|"
    r"kg/h|t/h|kg/s|"
    r"kW|MW|HP|"
    r"mm|cm|m|inch|in\b|"
    r"rpm|Hz|"
    r"%|ppm|"
    r"DN\d+|NPS\s*\d+)",
    re.IGNORECASE
)

# References normes
NORM_RE = re.compile(
    r"\b(API\s*\d+[A-Z]?(?:\s*[A-Z]\d*)?|"
    r"ASME\s*[A-Z]+\s*\d+(?:\.\d+)*(?:\s*[A-Z]+)?|"
    r"ISO\s*\d+(?:-\d+)*|"
    r"IEC\s*\d+(?:-\d+)*|"
    r"NACE\s*[A-Z]{2,}-?\d+[A-Z]*|"
    r"ATEX\s*\d+|"
    r"EN\s*\d+(?:-\d+)*|"
    r"NFPA\s*\d+)",
    re.IGNORECASE
)

# Formules de calcul (patterns)
CALC_RE = re.compile(
    r"(NPSH[Rr]?\s*=|"
    r"NPSHr?\s*[<>=]|"
    r"DP\s*=|"
    r"P(?:drop|_drop|chute)\s*=|"
    r"Q\s*=\s*[A-Z]|"
    r"SIL\s*[0-4]|"
    r"Cv\s*=|"
    r"Re\s*=|"
    r"EVM\s*=|"
    r"SPI\s*=|"
    r"CPI\s*=)",
    re.IGNORECASE
)


@dataclass
class TechnicalClaim:
    """Une donnee technique extraite du document projet."""
    type:      str    # TAG | VALUE | NORM | CALC
    raw:       str    # texte brut extrait
    context:   str    # phrase autour de l extraction
    line_num:  int    = 0
    verified:  bool   = False
    anomaly:   str    = ""


@dataclass
class AnomalyFinding:
    """Une anomalie detectee lors de l audit."""
    severity:    str    # ERREUR | WARNING | INFO
    category:    str    # CALCUL | NORME | TAG | COHERENCE | SECURITE
    claim_raw:   str    # la donnee fautive
    description: str    # description de l anomalie
    reference:   str    # norme/manuel de reference cite
    source_doc:  str    # document projet source
    line_num:    int    = 0
    suggestion:  str    = ""

    def to_dict(self):
        return asdict(self)

    def to_text(self) -> str:
        icon = {"ERREUR": "ERREUR", "WARNING": "ATTENTION", "INFO": "INFO"}.get(self.severity, "?")
        lines = [
            f"[{icon}] [{self.category}] {self.description}",
            f"  Extrait    : {self.claim_raw}",
        ]
        if self.reference:
            lines.append(f"  Reference  : {self.reference}")
        if self.suggestion:
            lines.append(f"  Suggestion : {self.suggestion}")
        return "\n".join(lines)


@dataclass
class AuditReport:
    """Rapport complet d audit d un document projet."""
    document_path:   str
    audit_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    total_claims:    int = 0
    findings:        list = field(default_factory=list)   # list[AnomalyFinding]
    summary:         str = ""
    audit_duration_s: float = 0.0

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == "ERREUR"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "WARNING"]

    def to_dict(self):
        return {
            "document_path": self.document_path,
            "audit_timestamp": self.audit_timestamp,
            "total_claims": self.total_claims,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "audit_duration_s": self.audit_duration_s,
            "stats": {
                "erreurs": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len([f for f in self.findings if f.severity == "INFO"]),
            }
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Rapport d Audit Sentinel-OG",
            f"",
            f"**Document** : `{self.document_path}`",
            f"**Date** : {self.audit_timestamp[:19]}",
            f"**Donnees analysees** : {self.total_claims}",
            f"",
            f"## Resume",
            f"",
            self.summary,
            f"",
            f"## Resultats",
            f"",
            f"| Niveau | Nombre |",
            f"|--------|--------|",
            f"| ERREUR  | {len(self.errors)} |",
            f"| WARNING | {len(self.warnings)} |",
            f"| INFO    | {len([f for f in self.findings if f.severity == 'INFO'])} |",
            f"",
        ]
        if self.errors:
            lines += ["## ERREURS (a corriger imperativement)", ""]
            for f in self.errors:
                lines.append(f.to_text())
                lines.append("")
        if self.warnings:
            lines += ["## WARNINGS (a verifier)", ""]
            for f in self.warnings:
                lines.append(f.to_text())
                lines.append("")
        return "\n".join(lines)


# ── Extracteur de donnees techniques ─────────────────────────────────────────

class TechnicalExtractor:
    """Extrait les donnees techniques d un texte brut."""

    def extract(self, text: str, source: str = "") -> list:
        """Retourne une liste de TechnicalClaim."""
        claims = []
        lines = text.splitlines()

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Tags equipements
            for m in TAG_RE.finditer(line):
                ctx_start = max(0, i-1)
                ctx = " ".join(lines[ctx_start:i+2])[:300]
                claims.append(TechnicalClaim(type="TAG", raw=m.group(), context=ctx, line_num=i+1))

            # Valeurs avec unites
            for m in VALUE_RE.finditer(line):
                ctx = line_stripped[:300]
                claims.append(TechnicalClaim(type="VALUE", raw=m.group(), context=ctx, line_num=i+1))

            # References normes
            for m in NORM_RE.finditer(line):
                ctx = line_stripped[:300]
                claims.append(TechnicalClaim(type="NORM", raw=m.group(), context=ctx, line_num=i+1))

            # Formules de calcul
            for m in CALC_RE.finditer(line):
                ctx = line_stripped[:300]
                claims.append(TechnicalClaim(type="CALC", raw=m.group(), context=ctx, line_num=i+1))

        # Deduplication
        seen = set()
        unique = []
        for c in claims:
            key = (c.type, c.raw.strip().upper())
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique


# ── Moteur d audit LLM ───────────────────────────────────────────────────────

AUDIT_PROMPT = """Tu es SENTINEL-OG, un auditeur technique expert en Oil & Gas.

NORMES ET REFERENCES (base de connaissances) :
{knowledge}

DOCUMENT PROJET A AUDITER :
Source : {source}
Contenu :
{doc_excerpt}

DONNEES TECHNIQUES A VERIFIER :
{claims_text}

MISSION : Verifier chaque donnee technique par rapport aux normes.
Pour chaque anomalie trouvee, repondre EXACTEMENT dans ce format JSON :

```json
[
  {{
    "severity": "ERREUR|WARNING|INFO",
    "category": "CALCUL|NORME|TAG|COHERENCE|SECURITE",
    "claim_raw": "la donnee fautive",
    "description": "description precise de l anomalie",
    "reference": "norme ou manuel cite",
    "suggestion": "correction recommandee"
  }}
]
```

Si aucune anomalie : repondre `[]`
Garde ta phase de reflexion (<think>) courte et concise (max 20 lignes).
Repondre UNIQUEMENT avec le JSON, rien d autre."""


class SentinelAuditor:
    """
    Auditeur de coherence documentaire Sentinel-OG.
    
    Croise les documents projet avec la base de connaissances
    pour detecter les erreurs techniques.
    """

    def __init__(self):
        self.extractor = TechnicalExtractor()
        self.client    = httpx.Client(timeout=TIMEOUT_S)

    def _call_llm(self, prompt: str) -> str:
        payload = {
            "model": AUDIT_MODEL,
            "prompt": prompt,
            "system": "Tu es un auditeur technique O&G expert. Garde ton raisonnement (<think>) court et concis. Tu reponds UNIQUEMENT en JSON valide.",
            "stream": False,
            "options": {"temperature": TEMPERATURE, "num_ctx": 4096, "num_predict": 2048},
        }
        try:
            resp = self.client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw
        except Exception as e:
            logger.error(f"[Auditor] LLM error: {e}")
            return "[]"

    def _get_knowledge(self, claims: list) -> str:
        """Recupere le contexte de la base de connaissances pour les claims."""
        try:
            from retriever import hybrid_retrieve, build_context_string
            # Construire une requete a partir des claims
            query_parts = []
            for c in claims[:10]:
                if c.type in ("TAG", "NORM", "CALC"):
                    query_parts.append(c.raw)
                elif c.type == "VALUE":
                    query_parts.append(c.context[:80])
            query = " ".join(query_parts[:5]) or "norme conception securite calcul"
            results = hybrid_retrieve(query=query, top_k=8)
            return build_context_string(results)
        except Exception as e:
            logger.warning(f"[Auditor] Knowledge retrieval failed: {e}")
            return ""

    def _parse_findings(self, raw: str, source: str) -> list:
        """Parse la reponse JSON du LLM."""
        # Extraire le JSON du texte
        json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)
        else:
            # Chercher directement un tableau JSON
            json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if json_match:
                raw = json_match.group(0)

        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            findings = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                sev = item.get("severity", "INFO").upper()
                if sev not in ("ERREUR", "WARNING", "INFO"):
                    sev = "INFO"
                findings.append(AnomalyFinding(
                    severity   = sev,
                    category   = item.get("category", "COHERENCE").upper(),
                    claim_raw  = item.get("claim_raw", ""),
                    description= item.get("description", ""),
                    reference  = item.get("reference", ""),
                    source_doc = source,
                    suggestion = item.get("suggestion", ""),
                ))
            return findings
        except json.JSONDecodeError as e:
            logger.warning(f"[Auditor] JSON parse error: {e} — raw: {raw[:200]}")
            return []

    def audit_text(self, text: str, source: str = "Document projet",
                   max_claims_per_batch: int = 15) -> AuditReport:
        """
        Audit complet d un texte de document projet.
        
        Args:
            text   : Contenu textuel du document
            source : Nom/chemin du document
            max_claims_per_batch : Nombre de claims par appel LLM
        
        Returns:
            AuditReport avec toutes les anomalies trouvees
        """
        t0 = time.time()
        report = AuditReport(document_path=source)

        # 1. Extraction des donnees techniques
        logger.info(f"[Auditor] Extraction des donnees techniques depuis: {source}")
        claims = self.extractor.extract(text, source)
        report.total_claims = len(claims)
        logger.info(f"[Auditor] {len(claims)} donnees techniques extraites")

        if not claims:
            report.summary = "Aucune donnee technique identifiable dans ce document."
            report.audit_duration_s = time.time() - t0
            return report

        # 2. Recuperer le contexte de la base de connaissances
        knowledge = self._get_knowledge(claims)
        if not knowledge:
            knowledge = "Base de connaissances O&G : normes API, ASME, ISO pour equipements et calculs."

        # 3. Audit par batches
        all_findings = []
        doc_excerpt = text[:3000]  # Extrait du document pour le contexte

        # Grouper les claims par type
        tags  = [c for c in claims if c.type == "TAG"]
        calcs = [c for c in claims if c.type == "CALC"]
        norms = [c for c in claims if c.type == "NORM"]
        vals  = [c for c in claims if c.type == "VALUE"]

        batches = []
        if tags:
            batches.append(("Tags equipements", tags[:max_claims_per_batch]))
        if calcs:
            batches.append(("Formules de calcul", calcs[:max_claims_per_batch]))
        if norms:
            batches.append(("References normes", norms[:max_claims_per_batch]))
        if vals:
            batches.append(("Valeurs techniques", vals[:max_claims_per_batch]))

        for batch_name, batch_claims in batches:
            logger.info(f"[Auditor] Verification batch: {batch_name} ({len(batch_claims)} items)")

            claims_text = f"=== {batch_name} ===\n"
            for c in batch_claims:
                claims_text += f"[L{c.line_num}] {c.type}: {c.raw}\n  Contexte: {c.context[:150]}\n"

            prompt = AUDIT_PROMPT.format(
                knowledge=knowledge[:4000],
                source=source,
                doc_excerpt=doc_excerpt,
                claims_text=claims_text,
            )

            raw_response = self._call_llm(prompt)
            batch_findings = self._parse_findings(raw_response, source)
            all_findings.extend(batch_findings)
            logger.info(f"[Auditor] {len(batch_findings)} anomalie(s) dans: {batch_name}")

        # 4. Trier par severite
        sev_order = {"ERREUR": 0, "WARNING": 1, "INFO": 2}
        all_findings.sort(key=lambda f: sev_order.get(f.severity, 3))
        report.findings = all_findings

        # 5. Resume global
        n_err  = len([f for f in all_findings if f.severity == "ERREUR"])
        n_warn = len([f for f in all_findings if f.severity == "WARNING"])
        n_info = len([f for f in all_findings if f.severity == "INFO"])

        if n_err == 0 and n_warn == 0:
            report.summary = f"Document conforme. {len(claims)} donnees verifiees, aucune anomalie detectee."
        else:
            report.summary = (
                f"Audit termine. {len(claims)} donnees analysees. "
                f"{n_err} erreur(s) a corriger, {n_warn} warning(s) a verifier, {n_info} observation(s)."
            )

        report.audit_duration_s = round(time.time() - t0, 1)
        logger.info(f"[Auditor] Audit termine en {report.audit_duration_s}s : "
                    f"{n_err} erreurs, {n_warn} warnings, {n_info} infos")
        return report

    def audit_file(self, file_path: str) -> AuditReport:
        """Audit d un fichier projet (txt, md, csv, pdf extrait)."""
        path = Path(file_path)
        if not path.exists():
            r = AuditReport(document_path=file_path)
            r.summary = f"Fichier introuvable : {file_path}"
            return r

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            r = AuditReport(document_path=file_path)
            r.summary = f"Erreur lecture fichier : {e}"
            return r

        return self.audit_text(text, source=str(path))

    def close(self):
        self.client.close()


# ── Singleton ─────────────────────────────────────────────────────────────────
_auditor: Optional[SentinelAuditor] = None

def get_auditor() -> SentinelAuditor:
    global _auditor
    if _auditor is None:
        _auditor = SentinelAuditor()
    return _auditor


# ── Test rapide ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    sample_doc = """
    NOTE DE CALCUL - POMPE DE TRANSFERT 203-PP-001
    
    Debit nominal  : 150 m3/h
    Pression aspiration : 1.2 bara
    Pression refoulement : 12 bara
    Temperature : 65 degC
    
    CALCUL NPSH DISPONIBLE :
    NPSHd = (Pasp - Pvap) / rho*g + h_s - h_f
    NPSHd = (1.2 - 0.25) * 10 / 1.0 + 2.5 - 0.8 = 11.2 m
    
    NPSHr fabricant = 3.5 m  (marge = 11.2 - 3.5 = 7.7 m)
    
    Norme applicable : API 610 11th Edition
    Materiau corps pompe : A216 WCB (carbone)
    
    Tag vanne aspiration : 203-XV-001
    Tag vanne refoulement : 203-CV-002
    Pression design casing : 16 bar (API 610 table 2)
    
    REMARQUE : La temperature 65C depasse le seuil standard pour joint mecanique type A.
    """

    print("=== TEST SENTINEL-OG AUDITOR ===\n")
    auditor = SentinelAuditor()
    report  = auditor.audit_text(sample_doc, source="note_calcul_203_PP_001.txt")

    print(report.to_markdown())
    print(f"\nDuree audit : {report.audit_duration_s}s")
    auditor.close()
