import os
import sys
import json
import sqlite3
import fitz  # PyMuPDF
import urllib.request
import urllib.parse

sys.path.insert(0, r"d:\DATA BASE IA")

from arh_regulatory_engine import ARHRegulatoryEngine, EQUIPMENT_TYPES
from arh_document_processor import ARHDocumentProcessor
from arh_report_generator import ARHReportGenerator

def test_deep_arh_suite():
    print("=" * 80)
    print("      DEEP SUITE TEST - ARKAN ARH MANAGEMENT MODULE (v5.0 ULTRA-DEEP)")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # TEST 1: Verification of Regulatory Engine Checklists & Decrees Catalog
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Verifying ARH Regulatory Engine & Equipment Checklists...")
    engine = ARHRegulatoryEngine()
    
    for eq_type, eq_info in EQUIPMENT_TYPES.items():
        prelim_check = engine.generate_mandatory_checklist(eq_type, dossier_stage="PRELIMINARY")
        final_check = engine.generate_mandatory_checklist(eq_type, dossier_stage="FINAL_RECEPTION")
        
        print(f"  [OK] Equipment: {eq_type:<16} | Label: {eq_info['label'][:35]:<35} | Prelim Items: {len(prelim_check)} | Final Items: {len(final_check)}")
        assert len(prelim_check) >= 5, f"Checklist for {eq_type} too small!"
        assert len(final_check) >= 5, f"Checklist for {eq_type} too small!"

    # -------------------------------------------------------------------------
    # TEST 2: Testing Document Processor on Pressure Vessel (ESP) with Scanned Visa
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Testing Pressure Vessel (ESP) Audit with ALGERAC / BV Visa Detection...")
    processor = ARHDocumentProcessor()
    
    esp_pdf = r"d:\DATA BASE IA\scratch\test_esp_dossier.pdf"
    doc = fitz.open()
    
    # Page 1: Data Sheet
    p1 = doc.new_page()
    p1.insert_text((50, 50), "FICHE TECHNIQUE APPAREIL SOUS PRESSION ESP-201\nPRESSION DE DESIGN: 20.0 BAR\nTEMPERATURE DESIGN: 120 C\nMATERIAU VIROLE: SA-516 GR 70\nRAYON INTERIEUR: 800 MM\nEPAISSEUR VIROLE: 18.0 MM\nCORROSION ALLOWANCE: 3.0 MM")
    
    # Page 2: Note de Calcul ASME VIII
    p2 = doc.new_page()
    p2.insert_text((50, 50), "NOTE DE CALCUL DE STRUCTURE ESP-201 ASME VIII DIV 1\nPRESSION DE CALCUL: 20.0 BAR\nRAYON INTERIEUR R = 800 MM\nEPAISSEUR DE VIROLE CALCUL: 18.5 MM")
    
    # Page 3: PV Hydrotest avec Stamp Bureau Veritas
    p3 = doc.new_page()
    p3.insert_text((50, 50), "PROCES VERBAL D EPREUVE HYDROSTATIQUE USINE\nEQUIPEMENT: ESP-201\nPRESSION D EPREUVE EFFECTUEE: 26.0 BAR\nORGANISME TIERS HABILITE: BUREAU VERITAS (ALGERAC AGREE)\nVISA INSPECTEUR: APPROUVE SANS RESERVE STAMP BV-2026")
    
    doc.save(esp_pdf)
    doc.close()
    
    res_esp = processor.process_dossier_batch(
        file_paths=[esp_pdf],
        project_name="PROJET CS-02 RAFFINERIE",
        unit_name="UNIT-200",
        dossier_stage="PRELIMINARY"
    )
    
    print(f"  [OK] ESP Equipment Identified : {res_esp['equipment_type']}")
    print(f"  [OK] ESP Tag Extracted       : {res_esp['equipment_tag']}")
    print(f"  [OK] ARH Decision            : {res_esp['arh_decision']}")
    print(f"  [OK] Compliance Score        : {res_esp['compliance_score']}%")
    print(f"  [OK] Missing Documents Count : {len(res_esp['missing_documents'])}")
    
    # Because 3 files were supplied out of ~10 mandatory files, status MUST be REJECTED!
    assert res_esp['status'] == "REJECTED", "Strict missing doc policy failed for ESP!"
    assert "NON CONFORME" in res_esp['arh_decision']
    
    # Clean up test pdf
    if os.path.exists(esp_pdf): os.remove(esp_pdf)

    # -------------------------------------------------------------------------
    # TEST 3: Testing Engineering Calculation Recalculation (Linepipe Under-Thickness)
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Testing Calculation Engine (Linepipe Wall Thickness Recalculation)...")
    pipe_pdf = r"d:\DATA BASE IA\scratch\test_linepipe_underthick.pdf"
    doc2 = fitz.open()
    
    # Under-dimensioned pipe: P=100 bar, D=508 mm, SMYS=450 MPa (X65), Zone D (F=0.72)
    # Required calc thickness = (100 * 508) / (2 * 4500 * 0.72) = 7.84 mm + 1.5 CA = 9.34 mm.
    # We declare 6.0 mm (severely under-dimensioned).
    p1 = doc2.new_page()
    p1.insert_text((50, 50), "SPECIFICATION CANALISATION GAZ PIPELINE 20 INCH\nPRESSION DE DESIGN: 100 BAR\nDIAMETRE NOMINAL: 508 MM\nGRADE MATERIAU: API 5L X65\nEPAISSEUR NOMINALE: 6.0 MM\nCORROSION ALLOWANCE: 1.5 MM\nZONE A")
    
    doc2.save(pipe_pdf)
    doc2.close()
    
    res_pipe = processor.process_dossier_batch(
        file_paths=[pipe_pdf],
        project_name="PROJET PIPELINE SKIKDA",
        unit_name="UNIT-300",
        dossier_stage="PRELIMINARY"
    )
    
    calc_anomalies = [c for c in res_pipe['comments'] if "Calcul" in c['title'] or "Dimensionn" in c['title']]
    print(f"  [OK] Calculation Anomalies Found: {len(calc_anomalies)}")
    if calc_anomalies:
        print("  [OK] Detected Calculation Error successfully!")
    assert len(calc_anomalies) > 0, "Failed to detect pipe under-thickness calculation error!"
    
    if os.path.exists(pipe_pdf): os.remove(pipe_pdf)

    # -------------------------------------------------------------------------
    # TEST 4: Testing Cross-Document Inconsistency Engine (Pressure Mismatch)
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Testing Cross-Document Inconsistency Engine (Data Sheet 15 bar vs Calc 30 bar)...")
    import uuid
    uid = uuid.uuid4().hex[:6]
    doc_ds = fr"d:\DATA BASE IA\scratch\test_ds_{uid}.pdf"
    doc_calc = fr"d:\DATA BASE IA\scratch\test_calc_{uid}.pdf"
    
    d1 = fitz.open(); p = d1.new_page(); p.insert_text((50,50), "DATA SHEET APPAREIL V-101 PRESSION DE DESIGN: 15 BAR SA-516 GR 70"); d1.save(doc_ds); d1.close()
    d2 = fitz.open(); p = d2.new_page(); p.insert_text((50,50), "NOTE DE CALCUL V-101 PRESSION DE DESIGN: 30 BAR SA-516 GR 70"); d2.save(doc_calc); d2.close()
    
    res_cross = processor.process_dossier_batch(
        file_paths=[doc_ds, doc_calc],
        project_name="PROJET CS-02",
        unit_name="UNIT-100",
        dossier_stage="PRELIMINARY"
    )
    
    inconsistent_comments = [c for c in res_cross['comments'] if "Pression" in c['title'] or "CROSS-DOCUMENTS" in c.get('category', '').upper()]
    print(f"  [OK] Cross-Document Inconsistencies Found: {len(inconsistent_comments)}")
    assert len(inconsistent_comments) > 0, "Failed to detect cross-document pressure mismatch!"
    
    if os.path.exists(doc_ds):
        try: os.remove(doc_ds)
        except: pass
    if os.path.exists(doc_calc):
        try: os.remove(doc_calc)
        except: pass

    # -------------------------------------------------------------------------
    # TEST 5: PDF Regulatory Report Generation
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Testing ARH PDF Report Generator...")
    report_gen = ARHReportGenerator()
    report_path = report_gen.generate_pdf_report(res_cross)
    print(f"  [OK] PDF Report Successfully Generated: {os.path.basename(report_path)}")
    assert os.path.exists(report_path), "PDF report file not found on disk!"

    # -------------------------------------------------------------------------
    # TEST 6: Testing Backend API Endpoints (Projects, Dossiers, Dashboard)
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Testing Live HTTP API Endpoints...")
    base_url = "http://127.0.0.1:8000"
    
    # GET /api/arh/projects
    req = urllib.request.urlopen(f"{base_url}/api/arh/projects")
    data_proj = json.loads(req.read().decode())
    print(f"  [OK] GET /api/arh/projects -> Status: {data_proj['status']} | Count: {data_proj['count']}")
    
    # GET /api/arh/dossiers
    req_d = urllib.request.urlopen(f"{base_url}/api/arh/dossiers")
    data_d = json.loads(req_d.read().decode())
    print(f"  [OK] GET /api/arh/dossiers -> Total Saved Dossiers: {len(data_d['dossiers'])}")
    
    # GET /api/arh/dashboard
    req_dash = urllib.request.urlopen(f"{base_url}/api/arh/dashboard")
    data_dash = json.loads(req_dash.read().decode())
    kpis = data_dash.get("kpis", data_dash)
    print(f"  [OK] GET /api/arh/dashboard -> Total: {kpis.get('total_dossiers', 0)} | Approved: {kpis.get('approved', 0)} | Rejected: {kpis.get('rejected', 0)}")

    print("\n" + "=" * 80)
    print("      SUCCESS: ALL DEEP SUITE TESTS PASSED 100% WITH ZERO ERRORS!")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    test_deep_arh_suite()
