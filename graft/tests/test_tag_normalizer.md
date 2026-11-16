# tests/test_tag_normalizer.py

- tn · function · L8-L9 — def tn()
- test_distinct_equipment_never_match · function · L17-L19 — def test_distinct_equipment_never_match(tn, a, b)
- test_legitimate_matches · function · L29-L31 — def test_legitimate_matches(tn, a, b, kind)
- test_unit_prefix_preserved · function · L33-L37 — def test_unit_prefix_preserved(tn)
- test_compressors_not_mistaken_for_cables · function · L39-L41 — def test_compressors_not_mistaken_for_cables(tn)
- test_cable_tag_resolves_to_equipment · function · L43-L47 — def test_cable_tag_resolves_to_equipment(tn)
- test_aliases_come_from_config_only · function · L49-L53 — def test_aliases_come_from_config_only()
- test_config_does_not_remove_instrument_types · function · L55-L57 — def test_config_does_not_remove_instrument_types()
- test_fuzzy_never_when_digits_differ · function · L59-L61 — def test_fuzzy_never_when_digits_differ(tn)
- test_extract_tags_from_label · function · L63-L65 — def test_extract_tags_from_label(tn)
- test_empty_and_none · function · L67-L69 — def test_empty_and_none(tn)
