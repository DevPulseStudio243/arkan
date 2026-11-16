"""Pipeline modernisé : unités (pint) + garde-fous + concordance inter-documents.
Lancer :  python test_modernized_arh_pipeline.py   ou   pytest test_modernized_arh_pipeline.py"""
from arh_dimensional_engine import dimensional_engine
from arh_assertion_guards import assertion_guard
from arh_concordance_graph import MultiDocumentConcordanceGraph


def test_concordance_detects_pressure_discordance_and_ignores_unit_difference():
    g = MultiDocumentConcordanceGraph()
    g.add_assertion("PLAN.pdf", "V-101", "pression", 20, "bar", page="1")
    g.add_assertion("NOTE_CALCUL.pdf", "V-101", "pression", 290.075, "psi", page="4")   # ≈ 20 bar : concordant
    g.add_assertion("FICHE_ANNEXE_E.pdf", "V-101", "pression", 25, "bar", page="2")     # discordant
    found = g.detect_discrepancies(tolerance_pct=2.0)
    docs = {d["doc1"] for d in found} | {d["doc2"] for d in found}
    assert "FICHE_ANNEXE_E.pdf" in docs
    assert not any({d["doc1"], d["doc2"]} == {"PLAN.pdf", "NOTE_CALCUL.pdf"} for d in found)


def test_guard_pipeline_keeps_valid_finding():
    f = {"title": "Épaisseur insuffisante", "observation": "t=9 mm < 11.2 mm requis", "document_concerned": "NOTE.pdf", "page": 5}
    assert assertion_guard.validate_and_sanitize_findings([f], "PRESSURE_VESSEL", "") == [f]


if __name__ == "__main__":
    test_concordance_detects_pressure_discordance_and_ignores_unit_difference()
    test_guard_pipeline_keeps_valid_finding()
    print("OK")
