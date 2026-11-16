import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

iso_dwg = Path(r"uploads\1-DC-1ACX1PN-313-N.dwg")
elec_dwg = Path(r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC -DW-300010- Chemin Atelier de maintenance\Rev 0\C3421-ROK1-300-ELC-DW-300010-0.dwg")

def test_iso_in_mto_tuyauterie_stays_in_tuyauterie():
    print("\n--- TEST 1: Piping ISO DWG uploaded to /mto/calculate ---")
    if not iso_dwg.exists():
        print(f"[SKIP] ISO DWG file {iso_dwg} not found.")
        return
        
    res = requests.post(f"{BASE_URL}/mto/calculate", data={"file_path": str(iso_dwg.resolve())})
    assert res.status_code == 200, f"Request failed: {res.text}"
    data = res.json()
    
    print(f"Status: {data.get('status')}")
    print(f"Is electrical: {data.get('is_electrical')}")
    print(f"BOM items count: {len(data.get('bom_items', data.get('mto', [])))}")
    
    # Critical invariant: must NOT return is_electrical: True
    assert not data.get("is_electrical"), "CRITICAL ERROR: /mto/calculate returned is_electrical: True!"
    print("PASS: Piping ISO DWG in /mto/calculate remains strictly in Tuyauterie (no is_electrical flag)!")

def test_elec_in_ie_mto_stays_in_ie():
    print("\n--- TEST 2: Electrical DWG uploaded to /ie-mto/calculate ---")
    if not elec_dwg.exists():
        print(f"[SKIP] Elec DWG file {elec_dwg} not found.")
        return
        
    res = requests.post(f"{BASE_URL}/ie-mto/calculate", data={"file_path": str(elec_dwg.resolve())})
    assert res.status_code == 200, f"Request failed: {res.text}"
    data = res.json()
    
    print(f"Status: {data.get('status')}")
    print(f"Items extracted: {len(data.get('items', []))}")
    print(f"Visual URL: {data.get('visual_url')}")
    
    assert len(data.get("items", [])) > 0, "No items extracted in /ie-mto/calculate"
    assert data.get("visual_url"), "Visual URL missing in /ie-mto/calculate"
    print("PASS: Electrical DWG in /ie-mto/calculate processed with success and HD visualizer!")

def test_elec_dwg_in_mto_tuyauterie_does_not_hijack_view():
    print("\n--- TEST 3: Electrical DWG sent to /mto/calculate (Tab Isolation check) ---")
    if not elec_dwg.exists():
        print(f"[SKIP] Elec DWG file {elec_dwg} not found.")
        return
        
    res = requests.post(f"{BASE_URL}/mto/calculate", data={"file_path": str(elec_dwg.resolve())})
    assert res.status_code == 200, f"Request failed: {res.text}"
    data = res.json()
    
    print(f"Status: {data.get('status')}")
    print(f"Is electrical: {data.get('is_electrical')}")
    
    # Must never return is_electrical: True to prevent frontend switchView
    assert not data.get("is_electrical"), "CRITICAL ERROR: /mto/calculate hijacked tab with is_electrical: True!"
    print("PASS: /mto/calculate does NOT hijack tab to I&E even if non-piping DWG is uploaded!")

if __name__ == "__main__":
    test_iso_in_mto_tuyauterie_stays_in_tuyauterie()
    test_elec_in_ie_mto_stays_in_ie()
    test_elec_dwg_in_mto_tuyauterie_does_not_hijack_view()
    print("\n=== ALL TAB ISOLATION TESTS PASSED 100% ===")
