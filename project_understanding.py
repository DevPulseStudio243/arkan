"""
Project understanding module for Deerflow Lite RAG system (Oil & Gas).

Provides document analysis, semantic query understanding, context enrichment,
and completeness assessment tailored to Oil & Gas engineering projects.
"""

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Oil & Gas domain knowledge
# ---------------------------------------------------------------------------
DOC_TYPE_PATTERNS: dict[str, list[str]] = {
    "p&id": ["p&id", "piping and instrument", "piping & instrument"],
    "pfd": ["pfd", "process flow diagram"],
    "datasheet": ["datasheet", "data sheet", "spec sheet"],
    "line_list": ["line list", "piping schedule"],
    "equipment_list": ["equipment list", "equipment schedule", "tag register"],
    "hazop": ["hazop", "hazard and operability", "hazard & operability"],
    "cause_and_effect": ["cause and effect", "cause & effect", "c&e"],
    "sil_assessment": ["sil assessment", "sil study", "safety integrity level"],
    "isometric": ["isometric", "iso drawing", "pipe iso"],
    "specification": ["specification", "spec", "standard"],
    "procedure": ["procedure", "method statement", "work instruction"],
    "report": ["report", "study", "analysis", "assessment"],
    "drawing": ["drawing", "layout", "plot plan", "ga drawing"],
    "calculation": ["calculation", "calc note", "sizing"],
    "well_program": ["well program", "drilling program", "completion program"],
    "reservoir_model": ["reservoir model", "simulation model", "decline curve"],
    "production_report": ["production report", "daily report", "well test report"],
}

DISCIPLINE_KEYWORDS: dict[str, list[str]] = {
    "process": ["separator", "vessel", "heat exchanger", "pump", "compressor",
                 "column", "reactor", "p&id", "pfd", "mass balance", "process"],
    "mechanical": ["valve", "pipe", "flange", "gasket", "nozzle",
                    "pressure vessel", "rotating equipment", "stress", "mechanical"],
    "electrical": ["motor", "switchgear", "transformer", "cable", "vfd",
                    "mcc", "ups", "generator", "load list", "electrical"],
    "instrumentation": ["transmitter", "control valve", "analyzer", "plc",
                         "dcs", "scada", "loop diagram", "sil", "instrument"],
    "civil": ["foundation", "structural", "concrete", "steel", "piling",
              "grading", "drainage"],
    "piping": ["isometric", "line list", "pipe spec", "pipe support",
               "stress analysis", "tie-in", "piping"],
    "hse": ["hazop", "pha", "risk", "emergency", "safety", "environmental",
            "flare", "dispersion"],
    "drilling": ["bit", "mud", "casing", "bha", "directional", "mwd",
                  "lwd", "well plan", "drilling"],
    "reservoir": ["porosity", "permeability", "simulation", "decline",
                   "pore pressure", "pvt", "saturation", "reservoir"],
    "production": ["artificial lift", "well test", "allocation", "metering",
                    "flow assurance", "wax", "hydrate", "scale", "production"],
}

QUERY_INTENTS: dict[str, list[str]] = {
    "lookup": ["what is", "define", "describe", "show me", "find"],
    "comparison": ["compare", "difference", "versus", "vs", "better"],
    "troubleshooting": ["problem", "issue", "failure", "why does", "fix",
                         "cause", "root cause", "troubleshoot"],
    "design": ["design", "sizing", "calculate", "select", "specify",
               "requirement", "criteria"],
    "compliance": ["comply", "standard", "regulation", "code", "requirement",
                    "norsok", "api", "asme", "iec"],
    "operational": ["operate", "procedure", "startup", "shutdown", "maintain",
                     "inspect", "test"],
    "safety": ["hazard", "risk", "sil", "esd", "emergency", "flare",
               "relief", "overpressure"],
}

EQUIPMENT_TAG_PATTERN = re.compile(
    r"\b([A-Z]{1,4}[-/]?\d{3,6}[A-Z]?(?:[-/][A-Z0-9]+)?)\b"
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class DocumentInfo:
    """Metadata for a single project document."""
    discipline: str = "general"
    doc_type: str = "unknown"


@dataclass
class EquipmentInfo:
    """Metadata for a piece of equipment."""
    tag: str = ""
    type: str = ""
    description: str = ""
    system: str = ""
    specifications: dict[str, Any] = field(default_factory=dict)
    related_documents: list[str] = field(default_factory=list)
    connected_to: list[str] = field(default_factory=list)


@dataclass
class SystemInfo:
    """Metadata for an Oil & Gas process system."""
    name: str = ""
    description: str = ""
    equipment: list[str] = field(default_factory=list)
    operating_conditions: dict[str, Any] = field(default_factory=dict)
    input_streams: list[str] = field(default_factory=list)
    output_streams: list[str] = field(default_factory=list)


@dataclass
class PhaseInfo:
    """Project phase information."""
    name: str = ""
    status: str = "unknown"
    documents: list[str] = field(default_factory=list)


@dataclass
class QueryUnderstanding:
    """Result of semantic query analysis."""
    intent: str = "lookup"
    subjects: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    implicit_needs: list[str] = field(default_factory=list)
    recommended_sources: list[str] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)


@dataclass
class CompletenessAssessment:
    """Assessment of answer completeness."""
    completeness_score: float = 0.0
    missing_information: list[str] = field(default_factory=list)
    suggested_additional_sources: list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# ProjectModel
# ---------------------------------------------------------------------------
class ProjectModel:
    """In-memory model of an Oil & Gas project assembled from analysed documents."""

    def __init__(self) -> None:
        self.project_name: str = "Unnamed Project"
        self.project_type: str = "unknown"
        self.document_map: dict[str, DocumentInfo] = {}
        self.equipment_registry: dict[str, EquipmentInfo] = {}
        self.systems: list[SystemInfo] = []
        self.relationships: list[dict[str, Any]] = []
        self.phases: list[PhaseInfo] = []

    def save(self, path: str) -> None:
        """Persist the project model to a JSON file using atomic write."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            data = {
                "project_name": self.project_name,
                "project_type": self.project_type,
                "document_map": {
                    k: asdict(v) for k, v in self.document_map.items()
                },
                "equipment_registry": {
                    k: asdict(v) for k, v in self.equipment_registry.items()
                },
                "systems": [asdict(s) for s in self.systems],
                "relationships": self.relationships,
                "phases": [asdict(p) for p in self.phases],
            }
            dir_name = os.path.dirname(path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp_path, path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info("Project model saved to %s", path)
        except Exception as exc:
            logger.error("Failed to save project model: %s", exc)

    @classmethod
    def load(cls, path: str) -> "ProjectModel":
        """Load a project model from a JSON file."""
        model = cls()
        if not os.path.exists(path):
            logger.warning("Project model file not found: %s", path)
            return model
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            model.project_name = data.get("project_name", "Unnamed Project")
            model.project_type = data.get("project_type", "unknown")
            for key, val in data.get("document_map", {}).items():
                model.document_map[key] = DocumentInfo(**val)
            for key, val in data.get("equipment_registry", {}).items():
                model.equipment_registry[key] = EquipmentInfo(**val)
            model.systems = [SystemInfo(**s) for s in data.get("systems", [])]
            model.relationships = data.get("relationships", [])
            model.phases = [PhaseInfo(**p) for p in data.get("phases", [])]
            logger.info("Project model loaded from %s", path)
        except Exception as exc:
            logger.error("Failed to load project model: %s", exc)
        return model

# ---------------------------------------------------------------------------
# ProjectAnalyzer
# ---------------------------------------------------------------------------
class ProjectAnalyzer:
    """Analyses Oil & Gas documents and builds a project model."""

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path
        self._project_model = ProjectModel()
        if model_path and os.path.exists(model_path):
            self._project_model = ProjectModel.load(model_path)
        logger.info("ProjectAnalyzer initialised (model_path=%s)", model_path)

    @property
    def project_model(self) -> ProjectModel:
        return self._project_model

    # -- document analysis ---------------------------------------------------
    def analyze_document(
        self, text: str = "", source: str = "", discipline: str = "general",
        **kwargs,
    ) -> DocumentInfo:
        """Analyse a document and register it in the project model.

        Returns a DocumentInfo with detected doc_type and discipline.
        """
        try:
            doc_type = self._detect_doc_type(text, source)
            detected_discipline = self._detect_discipline(text) or discipline

            doc_info = DocumentInfo(
                discipline=detected_discipline,
                doc_type=doc_type,
            )
            self._project_model.document_map[source] = doc_info

            # extract equipment tags
            self._extract_equipment(text, source, detected_discipline)

            # infer project type if not yet set
            if self._project_model.project_type == "unknown":
                self._project_model.project_type = self._infer_project_type(text)

            # persist if path configured
            if self._model_path:
                self._project_model.save(self._model_path)

            logger.info(
                "Analysed document '%s': type=%s, discipline=%s",
                source, doc_type, detected_discipline,
            )
            return doc_info
        except Exception as exc:
            logger.error("Error analysing document '%s': %s", source, exc)
            return DocumentInfo(discipline=discipline, doc_type="unknown")

    # -- detection helpers ---------------------------------------------------
    def _detect_doc_type(self, text: str, source: str) -> str:
        combined = (text[:2000] + " " + source).lower()
        for doc_type, patterns in DOC_TYPE_PATTERNS.items():
            if any(p in combined for p in patterns):
                return doc_type
        return "general"

    def _detect_discipline(self, text: str) -> str | None:
        text_lower = text[:3000].lower()
        best: str | None = None
        best_score = 0
        for disc, keywords in DISCIPLINE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best = disc
        return best if best_score >= 2 else None

    def _infer_project_type(self, text: str) -> str:
        text_lower = text[:5000].lower()
        type_hints = {
            "upstream": ["wellhead", "drilling", "reservoir", "completion",
                          "artificial lift", "well test"],
            "midstream": ["pipeline", "gathering", "compression", "metering",
                           "custody transfer", "pig"],
            "downstream": ["refinery", "distillation", "cracking", "reforming",
                            "hydrotreater", "alkylation"],
            "lng": ["liquefaction", "lng", "regasification", "cryogenic",
                     "boil-off"],
            "fpso": ["fpso", "turret", "offloading", "marine", "subsea"],
            "petrochemical": ["ethylene", "polyethylene", "polypropylene",
                               "aromatics", "olefins"],
        }
        for ptype, hints in type_hints.items():
            if sum(1 for h in hints if h in text_lower) >= 2:
                return ptype
        return "general"

    def _extract_equipment(self, text: str, source: str, discipline: str) -> None:
        tags = EQUIPMENT_TAG_PATTERN.findall(text)
        for tag in tags:
            if tag not in self._project_model.equipment_registry:
                self._project_model.equipment_registry[tag] = EquipmentInfo(
                    tag=tag,
                    type=self._guess_equipment_type(tag),
                    description="",
                    system="",
                    related_documents=[source],
                )
            else:
                entry = self._project_model.equipment_registry[tag]
                if source not in entry.related_documents:
                    entry.related_documents.append(source)

    @staticmethod
    def _guess_equipment_type(tag: str) -> str:
        prefix = re.match(r"^[A-Z]+", tag)
        if not prefix:
            return "unknown"
        p = prefix.group().upper()
        mapping = {
            "P": "pump", "C": "compressor", "V": "vessel", "E": "exchanger",
            "T": "tower", "R": "reactor", "D": "drum", "F": "filter",
            "H": "heater", "K": "compressor", "L": "level", "FV": "valve",
            "XV": "valve", "PSV": "relief_valve", "TV": "valve",
        }
        return mapping.get(p, "equipment")

# ---------------------------------------------------------------------------
# SemanticQueryUnderstanding
# ---------------------------------------------------------------------------
class SemanticQueryUnderstanding:
    """Analyses user queries to determine intent, subjects, and context needs."""

    def __init__(self) -> None:
        logger.info("SemanticQueryUnderstanding initialised")

    def understand_query(
        self, question: str, project_model: ProjectModel
    ) -> QueryUnderstanding:
        """Analyse a question and return structured understanding."""
        try:
            q_lower = question.lower()
            intent = self._detect_intent(q_lower)
            subjects = self._extract_subjects(q_lower, project_model)
            constraints = self._extract_constraints(q_lower)
            implicit_needs = self._infer_implicit_needs(intent, subjects, project_model)
            recommended_sources = self._recommend_sources(
                subjects, intent, project_model
            )
            reasoning_chain = self._build_reasoning_chain(
                question, intent, subjects, constraints
            )

            return QueryUnderstanding(
                intent=intent,
                subjects=subjects,
                constraints=constraints,
                implicit_needs=implicit_needs,
                recommended_sources=recommended_sources,
                reasoning_chain=reasoning_chain,
            )
        except Exception as exc:
            logger.error("Error understanding query: %s", exc)
            return QueryUnderstanding(
                intent="lookup",
                subjects=[],
                reasoning_chain=[f"Fallback – error during analysis: {exc}"],
            )

    def decompose_complex_query(
        self, question: str, project_model: ProjectModel
    ) -> list[str]:
        """Break a complex question into simpler sub-questions."""
        try:
            steps: list[str] = []
            q_lower = question.lower()

            # Detect conjunctions / multi-part structure
            parts = re.split(r"\band\b|\balso\b|;|\?", question)
            parts = [p.strip() for p in parts if len(p.strip()) > 10]

            if len(parts) <= 1:
                # single question – decompose by aspect
                understanding = self.understand_query(question, project_model)
                steps.append(f"Identify relevant {understanding.intent} information")
                for subject in understanding.subjects:
                    steps.append(f"Retrieve details about '{subject}'")
                if understanding.constraints:
                    steps.append(
                        "Apply constraints: " + ", ".join(understanding.constraints)
                    )
                if understanding.implicit_needs:
                    steps.append(
                        "Address implicit needs: "
                        + ", ".join(understanding.implicit_needs)
                    )
                steps.append("Synthesise findings into a coherent answer")
            else:
                for i, part in enumerate(parts, 1):
                    steps.append(f"Step {i}: Answer – {part.strip('?, ')}")
                steps.append("Combine sub-answers into a unified response")

            return steps
        except Exception as exc:
            logger.error("Error decomposing query: %s", exc)
            return [f"Answer the question directly: {question}"]

    def generate_follow_up_questions(
        self, question: str, answer: str, project_model: ProjectModel
    ) -> list[str]:
        """Generate contextually relevant follow-up questions."""
        try:
            follow_ups: list[str] = []
            understanding = self.understand_query(question, project_model)

            # Discipline-based follow-ups
            for subject in understanding.subjects[:2]:
                for disc, kws in DISCIPLINE_KEYWORDS.items():
                    if any(kw in subject.lower() for kw in kws):
                        follow_ups.append(
                            f"What are the {disc} design considerations for {subject}?"
                        )
                        break

            # Intent-based follow-ups
            intent_follow_ups = {
                "design": [
                    "What codes and standards apply?",
                    "What are the material selection requirements?",
                ],
                "troubleshooting": [
                    "What are the potential root causes?",
                    "What corrective actions are recommended?",
                ],
                "safety": [
                    "What are the associated safety studies?",
                    "What are the emergency response procedures?",
                ],
                "operational": [
                    "What are the normal operating parameters?",
                    "What are the alarm and trip setpoints?",
                ],
                "compliance": [
                    "What documentation is required for compliance?",
                    "What are the inspection and testing requirements?",
                ],
            }
            follow_ups.extend(
                intent_follow_ups.get(understanding.intent, [
                    "Are there related documents that provide more detail?",
                ])
            )

            # Equipment-specific
            tags = EQUIPMENT_TAG_PATTERN.findall(question + " " + answer)
            for tag in tags[:2]:
                if tag in project_model.equipment_registry:
                    eq = project_model.equipment_registry[tag]
                    if eq.connected_to:
                        follow_ups.append(
                            f"How does {tag} interact with {', '.join(eq.connected_to[:2])}?"
                        )

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique: list[str] = []
            for q in follow_ups:
                if q not in seen:
                    seen.add(q)
                    unique.append(q)
            return unique[:5]
        except Exception as exc:
            logger.error("Error generating follow-up questions: %s", exc)
            return []

    # -- internal helpers ----------------------------------------------------
    @staticmethod
    def _detect_intent(q_lower: str) -> str:
        for intent, patterns in QUERY_INTENTS.items():
            if any(p in q_lower for p in patterns):
                return intent
        return "lookup"

    @staticmethod
    def _extract_subjects(q_lower: str, project_model: ProjectModel) -> list[str]:
        subjects: list[str] = []
        # known equipment tags
        tags = EQUIPMENT_TAG_PATTERN.findall(q_lower.upper())
        subjects.extend(tags)
        # known systems
        for sys in project_model.systems:
            if sys.name.lower() in q_lower:
                subjects.append(sys.name)
        # domain terms
        for disc, kws in DISCIPLINE_KEYWORDS.items():
            for kw in kws:
                if kw in q_lower and kw not in subjects:
                    subjects.append(kw)
        return subjects[:10]

    @staticmethod
    def _extract_constraints(q_lower: str) -> list[str]:
        constraints: list[str] = []
        # numeric constraints
        nums = re.findall(
            r"\d+\.?\d*\s*(?:psi[ag]?|bar[ag]?|deg[cf]?|mm|inch|kg|lb|mpa|kpa|"
            r"bopd|mcfd|m3/h|bbl|gpm|rpm|kw|hp|mw)",
            q_lower,
        )
        constraints.extend(nums)
        # temporal constraints
        for word in ["before", "after", "during", "phase", "stage"]:
            if word in q_lower:
                idx = q_lower.index(word)
                snippet = q_lower[idx: idx + 40].split(".")[0].strip()
                constraints.append(snippet)
                break
        return constraints

    @staticmethod
    def _infer_implicit_needs(
        intent: str, subjects: list[str], project_model: ProjectModel
    ) -> list[str]:
        needs: list[str] = []
        if intent == "design":
            needs.append("applicable codes and standards")
            needs.append("material compatibility")
        elif intent == "troubleshooting":
            needs.append("historical failure data")
            needs.append("operating envelope limits")
        elif intent == "safety":
            needs.append("risk assessment results")
            needs.append("SIL classification")
        for subj in subjects:
            if subj in project_model.equipment_registry:
                eq = project_model.equipment_registry[subj]
                if eq.system:
                    needs.append(f"system context for {eq.system}")
        return needs[:5]

    @staticmethod
    def _recommend_sources(
        subjects: list[str], intent: str, project_model: ProjectModel
    ) -> list[str]:
        sources: list[str] = []
        # documents referencing subjects
        for subj in subjects:
            if subj in project_model.equipment_registry:
                sources.extend(
                    project_model.equipment_registry[subj].related_documents
                )
        # discipline-relevant documents
        intent_to_docs = {
            "safety": ["hazop", "sil_assessment", "cause_and_effect"],
            "design": ["datasheet", "specification", "calculation"],
            "operational": ["procedure", "report"],
            "compliance": ["specification", "report"],
        }
        preferred_types = intent_to_docs.get(intent, [])
        for src, info in project_model.document_map.items():
            if info.doc_type in preferred_types and src not in sources:
                sources.append(src)
        # deduplicate
        return list(dict.fromkeys(sources))[:10]

    @staticmethod
    def _build_reasoning_chain(
        question: str, intent: str, subjects: list[str], constraints: list[str]
    ) -> list[str]:
        chain = [f"Query intent identified as '{intent}'"]
        if subjects:
            chain.append(f"Key subjects: {', '.join(subjects[:5])}")
        if constraints:
            chain.append(f"Constraints: {', '.join(constraints[:3])}")
        chain.append("Searching relevant project documents")
        chain.append("Synthesising answer from retrieved context")
        return chain

# ---------------------------------------------------------------------------
# ContextEnricher
# ---------------------------------------------------------------------------
class ContextEnricher:
    """Enriches retrieval results with project context and assesses completeness."""

    def __init__(self) -> None:
        logger.info("ContextEnricher initialised")

    def enrich(
        self,
        question: str,
        results: list[dict[str, Any]],
        project_model: ProjectModel,
    ) -> list[dict[str, Any]]:
        """Enrich each result dict with additional project context.

        Returns a new list of result dicts with added context fields.
        """
        try:
            enriched: list[dict[str, Any]] = []
            for result in results:
                enriched_result = dict(result) if isinstance(result, dict) else vars(result).copy()
                text = getattr(result, "content", None) or getattr(result, "text", None) or enriched_result.get("text", "") or enriched_result.get("content", "")
                source = getattr(result, "source", None) or enriched_result.get("source", "")

                # add document info
                if source in project_model.document_map:
                    doc_info = project_model.document_map[source]
                    enriched_result["discipline"] = doc_info.discipline
                    enriched_result["doc_type"] = doc_info.doc_type

                # add equipment context
                tags = EQUIPMENT_TAG_PATTERN.findall(text)
                eq_context: list[dict[str, Any]] = []
                for tag in tags:
                    if tag in project_model.equipment_registry:
                        eq = project_model.equipment_registry[tag]
                        eq_context.append({
                            "tag": eq.tag,
                            "type": eq.type,
                            "system": eq.system,
                            "connected_to": eq.connected_to,
                        })
                if eq_context:
                    enriched_result["equipment_context"] = eq_context

                # add system context
                sys_names: list[str] = []
                text_lower = text.lower()
                for sys in project_model.systems:
                    if sys.name.lower() in text_lower:
                        sys_names.append(sys.name)
                if sys_names:
                    enriched_result["system_context"] = sys_names

                # add cross-references
                cross_refs: list[str] = []
                for tag in tags:
                    if tag in project_model.equipment_registry:
                        for doc in project_model.equipment_registry[tag].related_documents:
                            if doc != source and doc not in cross_refs:
                                cross_refs.append(doc)
                if cross_refs:
                    enriched_result["cross_references"] = cross_refs[:5]

                enriched.append(enriched_result)

            return enriched
        except Exception as exc:
            logger.error("Error enriching context: %s", exc)
            return list(results)

    def assess_completeness(
        self,
        question: str,
        results: list[dict[str, Any]],
        project_model: ProjectModel,
    ) -> CompletenessAssessment:
        """Assess how completely the retrieved results answer the question."""
        try:
            q_lower = question.lower()
            score = 0.0
            missing: list[str] = []
            suggested_sources: list[str] = []

            if not results:
                return CompletenessAssessment(
                    completeness_score=0.0,
                    missing_information=["No results were retrieved"],
                    suggested_additional_sources=list(
                        project_model.document_map.keys()
                    )[:5],
                )

            # coverage check: how many query terms appear in results
            query_tokens = set(re.findall(r"[a-z0-9]+", q_lower))
            query_tokens -= {"the", "a", "an", "is", "are", "what", "how", "where",
                             "when", "why", "does", "do", "can", "could", "would"}
            if query_tokens:
                combined_results = " ".join(
                    (getattr(r, "content", None) or getattr(r, "text", None) or (r.get("text", "") if isinstance(r, dict) else "") or (r.get("content", "") if isinstance(r, dict) else "")).lower()
                    for r in results
                )
                covered = sum(
                    1 for t in query_tokens if t in combined_results
                )
                term_coverage = covered / len(query_tokens)
            else:
                term_coverage = 1.0

            # discipline coverage
            detected_disciplines: set[str] = set()
            for disc, kws in DISCIPLINE_KEYWORDS.items():
                if any(kw in q_lower for kw in kws):
                    detected_disciplines.add(disc)

            result_disciplines: set[str] = set()
            for r in results:
                src = getattr(r, "source", None) or (r.get("source", "") if isinstance(r, dict) else "")
                if src in project_model.document_map:
                    result_disciplines.add(
                        project_model.document_map[src].discipline
                    )

            if detected_disciplines:
                disc_missing = detected_disciplines - result_disciplines
                disc_coverage = 1.0 - len(disc_missing) / len(detected_disciplines)
                for dm in disc_missing:
                    missing.append(f"No results from {dm} discipline")
                    for src, info in project_model.document_map.items():
                        if info.discipline == dm and src not in suggested_sources:
                            suggested_sources.append(src)
            else:
                disc_coverage = 1.0

            # equipment coverage
            query_tags = EQUIPMENT_TAG_PATTERN.findall(question)
            if query_tags:
                found_tags = set()
                for r in results:
                    text = getattr(r, "content", None) or getattr(r, "text", None) or (r.get("text", "") if isinstance(r, dict) else "") or (r.get("content", "") if isinstance(r, dict) else "")
                    found_tags.update(EQUIPMENT_TAG_PATTERN.findall(text))
                eq_missing = set(query_tags) - found_tags
                eq_coverage = 1.0 - len(eq_missing) / len(query_tags)
                for tag in eq_missing:
                    missing.append(f"Missing information about equipment {tag}")
                    if tag in project_model.equipment_registry:
                        suggested_sources.extend(
                            project_model.equipment_registry[tag].related_documents
                        )
            else:
                eq_coverage = 1.0

            # source count factor
            source_factor = min(len(results) / 3.0, 1.0)

            # weighted score
            score = (
                0.40 * term_coverage
                + 0.25 * disc_coverage
                + 0.20 * eq_coverage
                + 0.15 * source_factor
            )
            score = round(min(max(score, 0.0), 1.0), 3)

            if score < 0.5:
                missing.append("Overall retrieval coverage is low")
            if not missing and score >= 0.8:
                missing = []  # nothing notable missing

            # deduplicate suggested sources
            suggested_sources = list(dict.fromkeys(suggested_sources))[:5]

            return CompletenessAssessment(
                completeness_score=score,
                missing_information=missing,
                suggested_additional_sources=suggested_sources,
            )
        except Exception as exc:
            logger.error("Error assessing completeness: %s", exc)
            return CompletenessAssessment(
                completeness_score=0.0,
                missing_information=[f"Assessment error: {exc}"],
            )
