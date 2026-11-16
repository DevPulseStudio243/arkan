"""
DEERFLOW LITE — Engineering Catalog (ASME B16.5 / B16.9 / B16.11 / B36.10)
Provides comprehensive dimensional and weight catalog for O&G piping components.
"""
import logging

logger = logging.getLogger(__name__)

# ==============================================================================
#  1. ASME B36.10 — Tubes en acier (Seamless Pipe Outer Diameters, Thickness & Weights)
# ==============================================================================
# Format: size -> { schedule -> (outer_diameter_mm, thickness_mm, weight_kg_m) }
PIPE_CATALOG = {
    '1/2"': {
        '40':  (21.3, 2.77, 1.27),
        '80':  (21.3, 3.73, 1.62),
        'XS':  (21.3, 3.73, 1.62),
        '160': (21.3, 4.78, 1.95)
    },
    '3/4"': {
        '40':  (26.7, 2.87, 1.69),
        '80':  (26.7, 3.91, 2.20),
        'XS':  (26.7, 3.91, 2.20),
        '160': (26.7, 5.56, 2.90)
    },
    '1"': {
        '40':  (33.4, 3.38, 2.50),
        '80':  (33.4, 4.55, 3.24),
        'XS':  (33.4, 4.55, 3.24),
        '160': (33.4, 6.35, 4.24)
    },
    '1.5"': {
        '40':  (48.3, 3.68, 4.05),
        '80':  (48.3, 5.08, 5.41),
        'XS':  (48.3, 5.08, 5.41),
        '160': (48.3, 7.14, 7.25)
    },
    '2"': {
        '40':  (60.3, 3.91, 5.44),
        '80':  (60.3, 5.54, 7.48),
        'XS':  (60.3, 5.54, 7.48),
        '160': (60.3, 8.74, 11.11)
    },
    '3"': {
        '40':  (88.9, 5.49, 11.29),
        '80':  (88.9, 7.62, 15.27),
        'XS':  (88.9, 7.62, 15.27),
        '160': (88.9, 11.13, 21.35)
    },
    '4"': {
        '40':  (114.3, 6.02, 16.07),
        '80':  (114.3, 8.56, 22.32),
        'XS':  (114.3, 8.56, 22.32),
        '160': (114.3, 13.49, 33.54)
    },
    '6"': {
        '40':  (168.3, 7.11, 28.26),
        '80':  (168.3, 10.97, 42.56),
        'XS':  (168.3, 10.97, 42.56),
        '160': (168.3, 18.26, 67.56)
    },
    '8"': {
        '40':  (219.1, 8.18, 42.55),
        '80':  (219.1, 12.70, 64.64),
        'XS':  (219.1, 12.70, 64.64),
        '160': (219.1, 23.01, 111.27)
    },
    '10"': {
        '40':  (273.0, 9.27, 60.31),
        '80':  (273.0, 15.09, 95.97),
        'XS':  (273.0, 12.70, 81.55),
        '160': (273.0, 28.58, 172.26)
    },
    '12"': {
        '40':  (323.8, 10.31, 79.73),
        '80':  (323.8, 17.48, 132.04),
        'XS':  (323.8, 12.70, 97.46),
        '160': (323.8, 33.32, 238.76)
    }
}

# ==============================================================================
#  2. ASME B16.5 — Brides (Flanges Class 150#, 300#, 600#)
# ==============================================================================
# Format: size -> { rating -> { 'weight_kg': x, 'bolt_count': y, 'bolt_size': z, 'bolt_length': w } }
FLANGE_CATALOG = {
    '1/2"': {
        '150': {'weight_kg': 0.7, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 60},
        '300': {'weight_kg': 1.1, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 65},
        '600': {'weight_kg': 1.2, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 75}
    },
    '3/4"': {
        '150': {'weight_kg': 0.9, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 65},
        '300': {'weight_kg': 1.5, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 75},
        '600': {'weight_kg': 1.6, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 85}
    },
    '1"': {
        '150': {'weight_kg': 1.1, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 65},
        '300': {'weight_kg': 2.0, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 80},
        '600': {'weight_kg': 2.1, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 90}
    },
    '1.5"': {
        '150': {'weight_kg': 1.8, 'bolt_count': 4, 'bolt_size': 'M14', 'bolt_length': 70},
        '300': {'weight_kg': 3.2, 'bolt_count': 4, 'bolt_size': 'M20', 'bolt_length': 90},
        '600': {'weight_kg': 3.6, 'bolt_count': 4, 'bolt_size': 'M20', 'bolt_length': 110}
    },
    '2"': {
        '150': {'weight_kg': 2.7, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 80},
        '300': {'weight_kg': 3.7, 'bolt_count': 8, 'bolt_size': 'M16', 'bolt_length': 85},
        '600': {'weight_kg': 4.2, 'bolt_count': 8, 'bolt_size': 'M16', 'bolt_length': 110}
    },
    '3"': {
        '150': {'weight_kg': 4.3, 'bolt_count': 4, 'bolt_size': 'M16', 'bolt_length': 85},
        '300': {'weight_kg': 6.3, 'bolt_count': 8, 'bolt_size': 'M20', 'bolt_length': 95},
        '600': {'weight_kg': 8.2, 'bolt_count': 8, 'bolt_size': 'M20', 'bolt_length': 120}
    },
    '4"': {
        '150': {'weight_kg': 6.1, 'bolt_count': 8, 'bolt_size': 'M16', 'bolt_length': 85},
        '300': {'weight_kg': 10.4, 'bolt_count': 8, 'bolt_size': 'M20', 'bolt_length': 100},
        '600': {'weight_kg': 15.2, 'bolt_count': 8, 'bolt_size': 'M24', 'bolt_length': 145}
    },
    '6"': {
        '150': {'weight_kg': 8.6, 'bolt_count': 8, 'bolt_size': 'M20', 'bolt_length': 95},
        '300': {'weight_kg': 17.5, 'bolt_count': 12, 'bolt_size': 'M20', 'bolt_length': 110},
        '600': {'weight_kg': 26.5, 'bolt_count': 12, 'bolt_size': 'M27', 'bolt_length': 170}
    },
    '8"': {
        '150': {'weight_kg': 13.5, 'bolt_count': 8, 'bolt_size': 'M20', 'bolt_length': 100},
        '300': {'weight_kg': 28.0, 'bolt_count': 12, 'bolt_size': 'M22', 'bolt_length': 120},
        '600': {'weight_kg': 41.5, 'bolt_count': 12, 'bolt_size': 'M30', 'bolt_length': 190}
    },
    '10"': {
        '150': {'weight_kg': 19.5, 'bolt_count': 12, 'bolt_size': 'M22', 'bolt_length': 110},
        '300': {'weight_kg': 40.5, 'bolt_count': 16, 'bolt_size': 'M27', 'bolt_length': 145},
        '600': {'weight_kg': 65.0, 'bolt_count': 16, 'bolt_size': 'M33', 'bolt_length': 215}
    },
    '12"': {
        '150': {'weight_kg': 29.5, 'bolt_count': 12, 'bolt_size': 'M22', 'bolt_length': 115},
        '300': {'weight_kg': 56.5, 'bolt_count': 16, 'bolt_size': 'M30', 'bolt_length': 160},
        '600': {'weight_kg': 88.0, 'bolt_count': 20, 'bolt_size': 'M33', 'bolt_length': 225}
    }
}

# ==============================================================================
#  3. ASME B16.9 — Coudes (Elbows 90° LR, 45° LR)
# ==============================================================================
# Format: size -> { '90LR': (weight_kg, face_to_face_mm), '45LR': (weight_kg, face_to_face_mm) }
ELBOW_CATALOG = {
    '1/2"':  {'90LR': (0.08, 38.0),  '45LR': (0.05, 16.0)},
    '3/4"':  {'90LR': (0.12, 38.0),  '45LR': (0.07, 19.0)},
    '1"':    {'90LR': (0.19, 38.0),  '45LR': (0.10, 22.0)},
    '1.5"':  {'90LR': (0.37, 57.0),  '45LR': (0.19, 29.0)},
    '2"':    {'90LR': (0.52, 76.0),  '45LR': (0.27, 35.0)},
    '3"':    {'90LR': (1.16, 114.0), '45LR': (0.60, 51.0)},
    '4"':    {'90LR': (1.94, 152.0), '45LR': (1.00, 64.0)},
    '6"':    {'90LR': (4.90, 229.0), '45LR': (2.50, 95.0)},
    '8"':    {'90LR': (9.50, 305.0), '45LR': (4.80, 127.0)},
    '10"':   {'90LR': (16.5, 381.0), '45LR': (8.50, 159.0)},
    '12"':   {'90LR': (24.2, 457.0), '45LR': (12.5, 190.0)}
}

# ==============================================================================
#  4. ASME B16.9 — Réductions (Reducers Concentric / Eccentric) & Tés (Tees)
# ==============================================================================
# Reducers weights (approximate mean Concentric/Eccentric weight)
REDUCER_CATALOG = {
    ('3"', '2"'):   (0.72, 89.0),
    ('4"', '3"'):   (1.10, 102.0),
    ('4"', '2"'):   (1.25, 102.0),
    ('6"', '4"'):   (2.45, 140.0),
    ('6"', '3"'):   (2.60, 140.0),
    ('8"', '6"'):   (4.50, 152.0),
    ('10"', '8"'):  (7.20, 178.0),
    ('12"', '10"'): (10.5, 203.0)
}

# Equal Tees B16.9: size -> (weight_kg, center_to_face_mm)
TEE_CATALOG = {
    '1/2"':  (0.12, 25.0),
    '3/4"':  (0.18, 29.0),
    '1"':    (0.31, 38.0),
    '1.5"':  (0.65, 48.0),
    '2"':    (1.10, 64.0),
    '3"':    (2.80, 86.0),
    '4"':    (4.50, 105.0),
    '6"':    (11.2, 143.0),
    '8"':    (22.0, 178.0),
    '10"':   (35.5, 216.0),
    '12"':   (52.0, 254.0)
}

# ==============================================================================
#  5. API / ASME Valves catalog (Gate, Globe, Check, Ball Valves Cl.150)
# ==============================================================================
VALVE_CATALOG = {
    'gate': {
        '1/2"': 1.4, '3/4"': 1.6, '1"': 2.0, '1.5"': 3.2, '2"': 4.5,
        '3"': 9.5, '4"': 14.5, '6"': 28.0, '8"': 48.0, '10"': 82.0, '12"': 125.0
    },
    'check': {
        '1/2"': 0.9, '3/4"': 1.1, '1"': 1.4, '1.5"': 2.2, '2"': 3.6,
        '3"': 7.5, '4"': 12.0, '6"': 22.5, '8"': 38.0, '10"': 65.0, '12"': 100.0
    },
    'globe': {
        '1/2"': 1.2, '3/4"': 1.4, '1"': 1.8, '1.5"': 2.8, '2"': 4.0,
        '3"': 8.5, '4"': 13.0, '6"': 25.0, '8"': 43.0
    },
    'ball': {
        '1/2"': 0.6, '3/4"': 0.8, '1"': 1.1, '1.5"': 2.0, '2"': 3.2,
        '3"': 6.8, '4"': 12.5, '6"': 25.0
    }
}

# ==============================================================================
#  Access API
# ==============================================================================

def get_pipe_spec(size: str, schedule: str = "40") -> dict:
    """Returns Outer Diameter (mm), Thickness (mm), and Weight (kg/m)."""
    sz = size.strip()
    sch = schedule.strip()
    if sz in PIPE_CATALOG and sch in PIPE_CATALOG[sz]:
        od, thk, wt = PIPE_CATALOG[sz][sch]
        return {"outer_diameter_mm": od, "thickness_mm": thk, "weight_kg_m": wt}
    # Fallback default values
    return {"outer_diameter_mm": 88.9, "thickness_mm": 5.49, "weight_kg_m": 7.48}

def get_flange_spec(size: str, rating: str = "150") -> dict:
    """Returns weight, bolt count, bolt size, and length."""
    sz = size.strip()
    rt = rating.strip()
    if sz in FLANGE_CATALOG and rt in FLANGE_CATALOG[sz]:
        return FLANGE_CATALOG[sz][rt]
    return {"weight_kg": 3.18, "bolt_count": 8, "bolt_size": "M16", "bolt_length": 80}

def get_elbow_spec(size: str, angle: str = "90", type: str = "LR") -> dict:
    """Returns weight and face-to-face dimension."""
    sz = size.strip()
    key = f"{angle}{type}"
    if sz in ELBOW_CATALOG and key in ELBOW_CATALOG[sz]:
        wt, f2f = ELBOW_CATALOG[sz][key]
        return {"weight_kg": wt, "face_to_face_mm": f2f}
    return {"weight_kg": 1.16, "face_to_face_mm": 114.0}

def get_reducer_spec(size_large: str, size_small: str) -> dict:
    """Returns weight and face-to-face length of Concentric/Eccentric reducer."""
    sl = size_large.strip()
    ss = size_small.strip()
    if (sl, ss) in REDUCER_CATALOG:
        wt, length = REDUCER_CATALOG[(sl, ss)]
        return {"weight_kg": wt, "length_mm": length}
    return {"weight_kg": 0.72, "length_mm": 89.0}

def get_tee_spec(size: str) -> dict:
    """Returns weight and center-to-face length of Tee."""
    sz = size.strip()
    if sz in TEE_CATALOG:
        wt, c2f = TEE_CATALOG[sz]
        return {"weight_kg": wt, "center_to_face_mm": c2f}
    return {"weight_kg": 2.80, "center_to_face_mm": 86.0}

def get_valve_weight(valve_type: str, size: str) -> float:
    """Returns standard weight in kg for a given valve type and size."""
    vt = valve_type.lower().strip()
    sz = size.strip()
    if vt in VALVE_CATALOG and sz in VALVE_CATALOG[vt]:
        return VALVE_CATALOG[vt][sz]
    return 9.5
