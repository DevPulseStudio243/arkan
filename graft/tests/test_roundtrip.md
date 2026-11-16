# tests/test_roundtrip.py

- make_dxf · function · L17-L42 — def make_dxf(path: Path) -> Path
- built · function · L46-L50 — def built(tmp_path_factory)
- test_coverage_sans_perte · function · L53-L59 — def test_coverage_sans_perte(built)
- test_bloc_en_miroir_positions_monde · function · L62-L68 — def test_bloc_en_miroir_positions_monde(built)
- test_bulge_arcs_et_angles_conserves · function · L71-L78 — def test_bulge_arcs_et_angles_conserves(built)
- test_parent_et_matrice_des_inserts · function · L81-L86 — def test_parent_et_matrice_des_inserts(built)
- test_aller_retour_exact · function · L89-L93 — def test_aller_retour_exact(built)
- test_aller_retour_detecte_une_perte · function · L96-L105 — def test_aller_retour_detecte_une_perte(built, tmp_path)
