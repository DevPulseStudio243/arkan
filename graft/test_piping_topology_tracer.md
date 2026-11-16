# test_piping_topology_tracer.py

- test_parse_line_tag · function · L4-L28 — def test_parse_line_tag(): # Valid P&ID line tags
- test_basic_path_merging · function · L31-L43 — def test_basic_path_merging(): # Two connected segments: (0,0)->(10,0) and (10,0)->(20,0)
- test_micro_coupure_merging · function · L46-L58 — def test_micro_coupure_merging(): # Two segments with a tiny gap of 2.0: (0,0)->(10,0) and (12,0)->(22,0) # The gap is under the tolerance of 5.0
- test_crossing_without_connection · function · L61-L76 — def test_crossing_without_connection(): # A horizontal line (0, 10) -> (20, 10) # A vertical line (10, 0) -> (10, 20) # They intersect in their middle, but their endpoints are 10.0 units away from each other. # Since 10.0 > tolerance (5.0), they should NOT be merged!
- test_tag_association · function · L79-L96 — def test_tag_association()
- test_nozzle_port_connection · function · L99-L133 — def test_nozzle_port_connection(): # Line starting at (10, 50) and ending at (90, 50)
- test_fallback_box_connection · function · L136-L174 — def test_fallback_box_connection(): # Line starting at (15, 50) and ending at (85, 50) # The endpoints do not match ports, but are close to the blocks bounding boxes
- test_flow_direction_reversal · function · L177-L215 — def test_flow_direction_reversal(): # Line starting at (10, 50) and ending at (90, 50) # Left end is P-101A, Right end is V-102 # Flow arrow points to the left (ux = -1.0, uy = 0.0)
- test_project_stitching_with_opc · function · L218-L276 — def test_project_stitching_with_opc(): # Drawing 1: Pump to OPC
