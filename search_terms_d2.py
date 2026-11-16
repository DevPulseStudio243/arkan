import fitz

d2 = fitz.open('arh_uploads/DOSSIER_ARH_A034FE30/C1124-AST-PPL-M01-PRC-0001_A0 Tée a bareau.pdf')

queries = [
    "TEE STRENGTH CALCULATION",
    "B31.8",
    "21-315",
    "WPHY60",
    "BARRED TEE",
    "PQR",
    "WPS",
    "HYDROSTATIC",
    "CONSULAT",
    "SURÉPAISSEUR",
    "CORROSION",
    "ÉTAT DESCRIPTIF"
]

print("=== SEARCHING IN D2 (USER UPLOAD) ===")
for q in queries:
    hits = []
    for p_idx in range(len(d2)):
        txt = d2[p_idx].get_text().upper()
        if q.upper() in txt:
            hits.append(p_idx + 1)
    print(f"'{q}': found on pages {hits}")
