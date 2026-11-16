import openpyxl

wb = openpyxl.load_workbook("generated_visuals/ie_mto_batch_C2723-GCB-000-ELE-PLA-006_Plan_de_chemin_3271aac99d5c1df7.xlsx", data_only=True)
for sname in wb.sheetnames:
    ws = wb[sname]
    print(f"\n================ SHEET: {sname} ================")
    for row in ws.iter_rows(values_only=True):
        if any(c is not None for c in row):
            print("  ", [str(c) if c is not None else "" for c in row])
