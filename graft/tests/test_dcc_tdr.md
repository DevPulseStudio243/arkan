# tests/test_dcc_tdr.py

- test_validate_iec82045_codification · function · L16-L39 — def test_validate_iec82045_codification(): # Codes valides selon IEC 82045 / EPC standard
- test_dot09_business_logic · function · L41-L73 — def test_dot09_business_logic()
- test_dot09_batch_audit · function · L75-L86 — def test_dot09_batch_audit()
- test_transmittal_number_generation · function · L88-L95 — def test_transmittal_number_generation(): # Tester l'endpoint fonctionnel get_next_transmittal_number # Utiliser un dossier fictif
- test_database_iec_column · function · L97-L104 — def test_database_iec_column(): # Vérifier que la colonne iec_82045_valid existe bien dans tdr_documents
- test_audit_tdr_compliance_endpoint · function · L107-L113 — async def test_audit_tdr_compliance_endpoint(): # Tester l'audit de conformité sur un dossier existant ou vide
