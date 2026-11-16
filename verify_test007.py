from dwg_iso_extractor import extract_iso_from_pdf

def test(path):
    print("=" * 70)
    print("Testing:", path)
    r = extract_iso_from_pdf(path)
    val = r.get("validation", {})
    anom = r.get("anomalies", [])
    print("is_valid:", val.get("is_valid"))
    print("summary:", val.get("summary"))
    print("anomalies count:", len(anom))
    for a in anom:
        sev = a.get("severity")
        code = a.get("code")
        title = a.get("title") or a.get("message")
        print(f"  * [{sev}] {code}: {title}")

if __name__ == "__main__":
    test(r"C:\Users\MSI\Desktop\plans_extraits\plan_12_2-LP-1ACX1PN-318-N.pdf")
    test(r"C:\Users\MSI\Desktop\plans_extraits\plan_22_MSS-SP-97.pdf")
    test(r"C:\Users\MSI\Desktop\test007.pdf")
