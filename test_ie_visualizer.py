import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

dwg_file = Path(r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC -DW-300010- Chemin Atelier de maintenance\Rev 0\C3421-ROK1-300-ELC-DW-300010-0.dwg")
pdf_file = Path(r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC-DN-300004. TGBT\Rev 1\C3421-ROK1-300-ELC-DN-300004_1.pdf")

def test_dwg_visualization():
    print(f"\n--- TEST 1: DWG Visualization in E&I ({dwg_file.name}) ---")
    assert dwg_file.exists(), f"DWG file not found: {dwg_file}"
    res = requests.post(f"{BASE_URL}/ie-mto/calculate", data={"file_path": str(dwg_file)})
    assert res.status_code == 200, f"Request failed: {res.text}"
    data = res.json()
    
    print(f"Status: {data.get('status')}")
    print(f"Items extracted: {len(data.get('items', []))}")
    print(f"Visual URL: {data.get('visual_url')}")
    print(f"Preview image present: {bool(data.get('preview_image'))}")
    print(f"Pages count: {data.get('page_count')}")
    
    assert data.get('visual_url'), "visual_url should not be empty for DWG"
    vis_res = requests.get(f"{BASE_URL}{data['visual_url']}")
    assert vis_res.status_code == 200, f"Cannot fetch visual image: {vis_res.status_code}"
    print(f"Visual image fetched successfully! Size: {len(vis_res.content)} bytes (HTTP 200)")
    print("PASS: DWG Visualization in E&I verified!")

def test_pdf_multipage_visualization():
    print(f"\n--- TEST 2: Multi-Page PDF SLD Visualization in E&I ({pdf_file.name}) ---")
    assert pdf_file.exists(), f"PDF file not found: {pdf_file}"
    res = requests.post(f"{BASE_URL}/ie-mto/calculate", data={"file_path": str(pdf_file)})
    assert res.status_code == 200, f"Request failed: {res.text}"
    data = res.json()
    
    print(f"Status: {data.get('status')}")
    print(f"Items extracted: {len(data.get('items', []))}")
    print(f"Visual URL: {data.get('visual_url')}")
    pages = data.get('plan_preview_pages', [])
    print(f"Total preview pages: {len(pages)}")
    print(f"Reported page_count: {data.get('page_count')}")
    
    assert len(pages) > 1, f"Multi-page PDF should return multiple preview pages, got {len(pages)}"
    assert data.get('visual_url'), "visual_url should not be empty for PDF"
    vis_res = requests.get(f"{BASE_URL}{data['visual_url']}")
    assert vis_res.status_code == 200, f"Cannot fetch PDF visual image: {vis_res.status_code}"
    print(f"PDF visual image fetched successfully! Size: {len(vis_res.content)} bytes (HTTP 200)")
    print("PASS: Multi-page PDF SLD Visualization in E&I verified!")

if __name__ == "__main__":
    test_dwg_visualization()
    test_pdf_multipage_visualization()
    print("\n=== ALL E&I VISUALIZER TESTS PASSED 100% ===")
