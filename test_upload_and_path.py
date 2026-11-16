import requests
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

# Real drawings from Desktop
dwg_file1 = Path(r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-300-ELC -DW-300010- Chemin Atelier de maintenance\Rev 0\C3421-ROK1-300-ELC-DW-300010-0.dwg")
dwg_file2 = Path(r"C:\Users\MSI\Desktop\Electricite\04.EXECUTION\C3421-ROK1-000-ELC-DW-300001 typique malt\Rev 0\C3421-ROK1-000-ELC-DW-300001-0.dwg")

def test_ie_mto_upload():
    print(f"\n--- TEST 1: POST /ie-mto/calculate with Multipart Upload ({dwg_file1.name}) ---")
    assert dwg_file1.exists(), f"File not found: {dwg_file1}"
    with open(dwg_file1, "rb") as f:
        files = {"file": (dwg_file1.name, f, "application/octet-stream")}
        res = requests.post(f"{BASE_URL}/ie-mto/calculate", files=files)
    print(f"Status: {res.status_code}")
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    items = data.get('items', [])
    print(f"Items extracted: {len(items)}")
    for it in items[:3]:
        print(f"  - [{it.get('category')}] {it.get('description')} ({it.get('quantity')} {it.get('unit')})")
    print(f"Excel generated: {data.get('excel_filename')}")
    print("PASS: /ie-mto/calculate with multipart upload")

def test_ie_mto_local_path():
    print(f"\n--- TEST 2: POST /ie-mto/calculate with Direct Local Path ({dwg_file1.name}) ---")
    assert dwg_file1.exists(), f"File not found: {dwg_file1}"
    data_payload = {"file_path": str(dwg_file1)}
    res = requests.post(f"{BASE_URL}/ie-mto/calculate", data=data_payload)
    print(f"Status: {res.status_code}")
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    items = data.get('items', [])
    print(f"Items extracted: {len(items)}")
    print(f"Excel generated: {data.get('excel_filename')}")
    print("PASS: /ie-mto/calculate with direct local path")

def test_mto_calculate_auto_routing_upload():
    print(f"\n--- TEST 3: POST /mto/calculate with Electrical DWG Upload ({dwg_file2.name}) ---")
    assert dwg_file2.exists(), f"File not found: {dwg_file2}"
    with open(dwg_file2, "rb") as f:
        files = {"file": (dwg_file2.name, f, "application/octet-stream")}
        res = requests.post(f"{BASE_URL}/mto/calculate", files=files)
    print(f"Status: {res.status_code}")
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    print(f"is_electrical: {data.get('is_electrical')}")
    items = data.get('mto', [])
    print(f"Items extracted: {len(items)}")
    for it in items[:3]:
        print(f"  - [{it.get('category')}] {it.get('description')} ({it.get('quantity')} {it.get('unit')})")
    print(f"Excel generated: {data.get('excel_filename')}")
    print("PASS: /mto/calculate auto-routing with upload")

def test_mto_calculate_auto_routing_path():
    print(f"\n--- TEST 4: POST /mto/calculate with Direct Path ({dwg_file2.name}) ---")
    assert dwg_file2.exists(), f"File not found: {dwg_file2}"
    data_payload = {"file_path": str(dwg_file2)}
    res = requests.post(f"{BASE_URL}/mto/calculate", data=data_payload)
    print(f"Status: {res.status_code}")
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    print(f"is_electrical: {data.get('is_electrical')}")
    items = data.get('mto', [])
    print(f"Items extracted: {len(items)}")
    print(f"Excel generated: {data.get('excel_filename')}")
    print("PASS: /mto/calculate auto-routing with direct path")

if __name__ == "__main__":
    test_ie_mto_upload()
    test_ie_mto_local_path()
    test_mto_calculate_auto_routing_upload()
    test_mto_calculate_auto_routing_path()
    print("\n=== ALL 4 INTEGRATION TESTS PASSED 100% ===")
