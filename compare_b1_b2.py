import fitz
from arh_document_slicer import arh_slicer

d1 = fitz.open('arh_uploads/DOSSIER_ARH_26307CC5/C1124-AST-PPL-M01-PRC-0001_A0 Tée a bareau.pdf')
d2 = fitz.open('arh_uploads/DOSSIER_ARH_A034FE30/C1124-AST-PPL-M01-PRC-0001_A0 Tée a bareau.pdf')

b1 = arh_slicer.identify_boundaries(d1)
b2 = arh_slicer.identify_boundaries(d2)

print("=== B1 (26307CC5) ===")
for x in b1:
    print(x['spec']['code'], "start:", x['start'], "end:", x['end'])

print("\n=== B2 (A034FE30) ===")
for x in b2:
    print(x['spec']['code'], "start:", x['start'], "end:", x['end'])
