import fitz

d1 = fitz.open('arh_uploads/DOSSIER_ARH_26307CC5/C1124-AST-PPL-M01-PRC-0001_A0 Tée a bareau.pdf')
d2 = fitz.open('arh_uploads/DOSSIER_ARH_A034FE30/C1124-AST-PPL-M01-PRC-0001_A0 Tée a bareau.pdf')

for p in range(20, 28):
    t1 = d1[p-1].get_text().strip()
    t2 = d2[p-1].get_text().strip()
    same = (t1 == t2)
    print(f"Page {p}: same={same} | len(t1)={len(t1)}, len(t2)={len(t2)}")
    if not same:
        print(f"  t1[:50]: {repr(t1[:50])}")
        print(f"  t2[:50]: {repr(t2[:50])}")
