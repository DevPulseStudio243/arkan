from arh_document_slicer import arh_slicer

pieces = arh_slicer.slice_dossier("DOSSIER_ARH_A034FE30")
for p in pieces:
    print(f"{p['piece_code']}: p.{p['page_start']}-{p['page_end']} (count={p['page_count']}) -> {p['file_name']}")
