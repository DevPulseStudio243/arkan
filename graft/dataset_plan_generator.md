# dataset_plan_generator.py

- draw_valve · function · L67-L84 — def draw_valve(draw, x, y, size=30, vtype="gate")
- draw_instrument · function · L86-L92 — def draw_instrument(draw, x, y, tag_text="PT-101", radius=16)
- draw_equipment_pump · function · L94-L99 — def draw_equipment_pump(draw, x, y, r=28)
- draw_steel_beam · function · L101-L106 — def draw_steel_beam(draw, x, y, w=160, h=40, btype="IPE")
- draw_civil_footing · function · L108-L113 — def draw_civil_footing(draw, x, y, w=100, h=60)
- draw_elec_transformer · function · L115-L119 — def draw_elec_transformer(draw, x, y, r=20)
- generate_plan · function · L121-L307 — def generate_plan(img_id: int, discipline: str, split="train")
- add_box · function · L143-L162 — def add_box(class_name, x0, y0, x1, y1, tag="", meta=None): # Clip coordinates
- build_complete_dataset · function · L309-L351 — def build_complete_dataset()
