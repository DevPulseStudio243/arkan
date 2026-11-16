import fitz

doc = fitz.open(r"C:\Users\MSI\Desktop\1\C2723-GCB-000-ELE-PLA-006 Plan de cheminement.pdf")
for i, page in enumerate(doc):
    print(f"\n================ PAGE {i+1} ================")
    blocks = page.get_text("blocks")
    for b in blocks:
        text = b[4].strip().replace("\n", " ")
        safe_t = text.encode("ascii", errors="replace").decode()
        print(f"  [y={b[1]:.0f}] {safe_t}")
