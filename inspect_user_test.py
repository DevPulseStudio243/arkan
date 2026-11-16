from dwg_iso_extractor import extract_iso_from_pdf
import json

def inspect_file(pdf_path):
    print("=" * 60)
    print(f"ANALYSE DE : {pdf_path}")
    print("=" * 60)
    r = extract_iso_from_pdf(pdf_path)
    print("=== BOM ITEMS ===")
    for it in r.get("bom_items", []):
        no = it.get("item_no")
        cat = it.get("category")
        qte = it.get("quantity")
        unit = it.get("unit")
        desc = it.get("description")
        print(f"Item {no} [{cat}]: {qte} {unit} -> {desc}")

    print("\n=== SPOOLS ===")
    spools = r.get("spools", [])
    print(f"Total spools: {len(spools)}")
    tot_cut = sum(s.get("cut_length_mm", 0) for s in spools) / 1000.0
    print(f"Total cut length: {tot_cut:.3f} m")
    for s in spools:
        print(f"  {s.get('piece')}: {s.get('cut_length_mm')} mm (NS {s.get('ns')})")

    print("\n=== CAD TOPOLOGY ===")
    val = r.get("validation", {})
    cad = val.get("cad_topology", {})
    for k, v in cad.items():
        print(f"  {k}: {v}")

    print(f"\n=== ANOMALIES DETECTEES ({len(r.get('anomalies', []))}) ===")
    for a in r.get("anomalies", []):
        sev = a.get("severity")
        code = a.get("code")
        title = a.get("title")
        desc = a.get("description")
        print(f" * [{sev}] {code}: {title}")
        print(f"   -> {desc}")

if __name__ == "__main__":
    inspect_file(r"C:\Users\MSI\Desktop\test007.pdf")
