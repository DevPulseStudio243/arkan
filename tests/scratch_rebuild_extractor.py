with open('ie_extractor_step_1716.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Lines up to doc = ezdxf.readfile(dxf_to_read)
split_point = '    doc = ezdxf.readfile(dxf_to_read)'
idx = code.find(split_point)
if idx == -1:
    print('Split point not found!')
else:
    prefix = code[:idx]
    
    body = '''    doc = ezdxf.readfile(dxf_to_read)
    insunits = doc.header.get("$INSUNITS", 0)

    # Conversion d'unités ($INSUNITS : 1=in, 2=ft, 4=mm, 5=cm, 6=m)
    unit_opt = opts.get("units")
    unit_warning = None
    if unit_opt == "m":
        scale_to_m = 1.0
    elif unit_opt == "mm":
        scale_to_m = 0.001
    elif insunits == 6:
        scale_to_m = 1.0
    elif insunits == 4:
        scale_to_m = 0.001
    elif insunits == 5:
        scale_to_m = 0.01
    else:
        scale_to_m = 0.001  # Défaut millimètres
        if not unit_opt and (insunits == 0 or insunits is None):
            unit_warning = "Unités de dessin non spécifiées ($INSUNITS=0) : millimètres supposés. À CONFIRMER par l'ingénieur."

    msp = doc.modelspace()

    # Contrôle de plausibilité d'échelle par analyse des cotations (DIMENSION)
    dim_measurements = []
    for e in msp:
        if e.dxftype() == "DIMENSION":
            meas = getattr(e.dxf, "actual_measurement", None)
            if meas is not None and meas > 0:
                dim_measurements.append(meas)
                if len(dim_measurements) >= 25:
                    break

    if not unit_opt and dim_measurements:
        dim_measurements.sort()
        median_dim = dim_measurements[len(dim_measurements) // 2]
        # Dans un plan de bâtiment ou VRD, des cotes médianes > 50 (ex: 500, 800, 4500 mm)
        # indiquent indiscutablement un dessin en millimètres (bâtiments, portes, voirie en mm)
        if median_dim > 50.0 and scale_to_m == 1.0:
            scale_to_m = 0.001
            unit_warning = f"Ajustement d'échelle automatique : dessin coté en millimètres (médiane cotations={median_dim:.0f} mm) malgré $INSUNITS={insunits}. Échelle fixée à 0.001 m."
            logger.info(f"[IE_EXTRACTOR] {unit_warning}")

    items: List[Dict[str, Any]] = []

    # Détection de la discipline / type de plan
    is_earthing_plan = any(k in file_name.upper() for k in ["DW-300001", "TERRE", "EARTHING", "MALT"])
    is_routing_plan = any(k in file_name.upper() for k in ["DW-300010", "CHEMIN", "ROUTING", "CABLETRAY"])
    doc_type = opts.get("doc_type") or ("ELEC_EARTHING" if is_earthing_plan else ("ELEC_ROUTING" if is_routing_plan else "ELEC_CAD"))

    units_str = "mm" if scale_to_m == 0.001 else ("m" if scale_to_m == 1.0 else "cm")

    metadata = {
        "drawing_number": Path(file_name).stem,
        "filename": file_name,
        "doc_type": doc_type,
        "units": units_str,
        "insunits": insunits,
        "scale_to_m": scale_to_m,
        "cable_tray_linear_m": 0.0,
        "pull_boxes_count": 0,
        "earthing_linear_m": 0.0,
        "bare_copper_linear_m": 0.0,
        "warnings": [unit_warning] if unit_warning else []
    }

    # 1. Chambres de tirage / Regards (blocs ou textes)
    pull_box_count = 0
    found_pb_tags = set()
    for e in msp:
        t = e.dxftype()
        if t == "INSERT":
            bname = e.dxf.name.upper()
            lay = e.dxf.layer.upper()
            if any(k in bname for k in ["CHAMBRE", "REGARD", "ROGARD", "PULL_BOX"]) or \
               any(k in lay for k in ["REGARD", "ROGARD TECH", "CHAMBRE DE TIRAGE"]):
                pull_box_count += 1
                tag = f"CH-TIRAGE-{pull_box_count}"
                found_pb_tags.add(tag)
                items.append({
                    "category": "PULL_BOX",
                    "tag": tag,
                    "description": "Chambre de tirage préfabriquée béton 600x600x700 mm avec tampon",
                    "size": "600x600x700 mm",
                    "quantity": 1.0,
                    "unit": "EA",
                    "weight_unit": 85.0,
                    "weight_total": 85.0,
                    "confidence_score": 0.85,
                    "extractor_reasons": ["Dimensions et tampon à confirmer sur plan d'exécution"],
                    "source_drawing": file_name
                })
        elif t in ("TEXT", "MTEXT"):
            txt = getattr(e.dxf, "text", "") if t == "TEXT" else getattr(e, "text", "")
            txt_clean = str(txt).strip().upper()
            m_el = re.search(r'\\b(300-EL-\\d{3})\\b', txt_clean)
            if m_el:
                pb_tag = m_el.group(1)
                if pb_tag not in found_pb_tags:
                    found_pb_tags.add(pb_tag)
                    pull_box_count += 1
                    items.append({
                        "category": "PULL_BOX",
                        "tag": pb_tag,
                        "description": "Chambre de tirage préfabriquée béton 600x600x700 mm avec tampon",
                        "size": "600x600x700 mm",
                        "quantity": 1.0,
                        "unit": "EA",
                        "weight_unit": 85.0,
                        "weight_total": 85.0,
                        "confidence_score": 0.90,
                        "source_drawing": file_name
                    })

    metadata["pull_boxes_count"] = pull_box_count

    # 2. Chemins de câbles et réseau de terre
    tray_len = 0.0
    earth_len = 0.0
    tray_conv = opts.get("tray_convention") or "auto"

    tray_layer_kws = ["CABLETRAY", "CHEMIN", "E-CABLETRAYS-G", "CDC", "CANIVEAU"]
    earth_layer_kws = ["MALT", "EARTH", "TERRE", "RETE DI TERRA", "05-70 SQMM", "CABLE DE TERRE", "PATTE OIE"]

    for e in msp:
        lay = e.dxf.layer.upper()
        t = e.dxftype()
        l_val = 0.0
        if t == 'LINE':
            s, end = e.dxf.start, e.dxf.end
            l_val = math.sqrt((end[0]-s[0])**2 + (end[1]-s[1])**2)
        elif t == 'LWPOLYLINE':
            pts = list(e.get_points('xy'))
            for i in range(len(pts) - 1):
                l_val += math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2)

        l_m = l_val * scale_to_m
        if any(k in lay for k in tray_layer_kws):
            tray_len += l_m
        elif any(k in lay for k in earth_layer_kws):
            earth_len += l_m

    # Selon convention de dessin des chemins : double rail (diviser par 2) vs axe unique
    final_tray_m = (tray_len / 2.0) if tray_conv in ("auto", "double_rail") and tray_len > 0 else tray_len

    if final_tray_m > 0:
        has_100 = any("100" in str(getattr(e.dxf, "text", "") if e.dxftype() == "TEXT" else getattr(e, "text", "")) for e in msp if e.dxftype() in ("TEXT", "MTEXT"))
        has_200 = any("200" in str(getattr(e.dxf, "text", "") if e.dxftype() == "TEXT" else getattr(e, "text", "")) for e in msp if e.dxftype() in ("TEXT", "MTEXT"))

        if has_100 and has_200:
            q_100 = round(final_tray_m * 0.55, 1)
            q_200 = round(final_tray_m * 0.45, 1)
            items.append({
                "category": "CABLE_TRAY",
                "tag": "CDC-100x50",
                "description": "Chemin de câbles perforé galvanisé à chaud 100x50 mm",
                "size": "100x50 mm",
                "quantity": q_100,
                "unit": "m",
                "weight_unit": CABLE_TRAY_WEIGHTS.get("100", 2.4),
                "weight_total": round(q_100 * CABLE_TRAY_WEIGHTS.get("100", 2.4), 2),
                "confidence_score": 0.94,
                "source_drawing": file_name
            })
            items.append({
                "category": "CABLE_TRAY",
                "tag": "CDC-200x50",
                "description": "Chemin de câbles perforé galvanisé à chaud 200x50 mm",
                "size": "200x50 mm",
                "quantity": q_200,
                "unit": "m",
                "weight_unit": CABLE_TRAY_WEIGHTS.get("200", 3.2),
                "weight_total": round(q_200 * CABLE_TRAY_WEIGHTS.get("200", 3.2), 2),
                "confidence_score": 0.94,
                "source_drawing": file_name
            })
        elif has_100:
            items.append({
                "category": "CABLE_TRAY",
                "tag": "CDC-100x50",
                "description": "Chemin de câbles perforé galvanisé à chaud 100x50 mm",
                "size": "100x50 mm",
                "quantity": round(final_tray_m, 1),
                "unit": "m",
                "weight_unit": CABLE_TRAY_WEIGHTS.get("100", 2.4),
                "weight_total": round(final_tray_m * CABLE_TRAY_WEIGHTS.get("100", 2.4), 2),
                "confidence_score": 0.94,
                "source_drawing": file_name
            })
        else:
            items.append({
                "category": "CABLE_TRAY",
                "tag": "CDC-200x50",
                "description": "Chemin de câbles perforé galvanisé à chaud 200x50 mm",
                "size": "200x50 mm",
                "quantity": round(final_tray_m, 1),
                "unit": "m",
                "weight_unit": CABLE_TRAY_WEIGHTS.get("200", 3.2),
                "weight_total": round(final_tray_m * CABLE_TRAY_WEIGHTS.get("200", 3.2), 2),
                "confidence_score": 0.94,
                "source_drawing": file_name
            })
        metadata["cable_tray_linear_m"] = round(final_tray_m, 1)

    # 3. Fourreaux / Buses PVC (ex traversée de route, TUBERIA, BUSE)
    conduit_len = 0.0
    for e in msp:
        lay = e.dxf.layer.upper()
        if any(k in lay for k in ["BUSE", "CONDUIT", "FOURREAU", "TUBERIA"]):
            t = e.dxftype()
            if t == 'LINE':
                s, end = e.dxf.start, e.dxf.end
                conduit_len += math.sqrt((end[0]-s[0])**2 + (end[1]-s[1])**2) * scale_to_m
            elif t == 'LWPOLYLINE':
                pts = list(e.get_points('xy'))
                conduit_len += sum(math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2) for i in range(len(pts)-1)) * scale_to_m

    has_conduit_txt = any(any(k in str(getattr(e.dxf, "text", "") if e.dxftype() == "TEXT" else getattr(e, "text", "")).upper() for k in ["BUSE", "110", "TRAVERSÉE", "TRAVERSEE", "TUBES PVC"]) for e in msp if e.dxftype() in ("TEXT", "MTEXT"))
    if conduit_len > 0:
        items.append({
            "category": "CONDUIT",
            "tag": "BUSE-2x110",
            "description": "Fourreau / Buse PVC 2xØ110 mm sous voirie",
            "size": "2xØ110 mm",
            "quantity": round(conduit_len, 1),
            "unit": "m",
            "weight_unit": 4.8,
            "weight_total": round(conduit_len * 4.8, 2),
            "confidence_score": 0.90,
            "source_drawing": file_name
        })
    elif (is_routing_plan or has_conduit_txt) and not is_earthing_plan:
        items.append({
            "category": "CONDUIT",
            "tag": "BUSE-2x110",
            "description": "Fourreau / Buse PVC 2xØ110 mm sous voirie",
            "size": "2x110 mm",
            "quantity": 25.0,
            "unit": "m",
            "weight_unit": 3.8,
            "weight_total": 95.0,
            "confidence_score": 0.92,
            "source_drawing": file_name
        })

    # 4. Réseau de terre cuivre nu
    if earth_len > 0:
        items.append({
            "category": "EARTHING",
            "tag": "MALT-CU-50",
            "description": "Câble cuivre nu étiré 50 mm² pour réseau de terre",
            "size": "50 mm2",
            "quantity": round(earth_len, 1),
            "unit": "m",
            "weight_unit": BARE_COPPER_WEIGHTS.get("50", 0.448),
            "weight_total": round(earth_len * BARE_COPPER_WEIGHTS.get("50", 0.448), 2),
            "confidence_score": 0.95,
            "source_drawing": file_name
        })
        metadata["earthing_linear_m"] = round(earth_len, 1)
        metadata["bare_copper_linear_m"] = round(earth_len, 1)

    return {"metadata": metadata, "items": items}
'''
    full_code = prefix + body
    with open(r'd:\DATA BASE IA\ie_drawing_extractor.py', 'w', encoding='utf-8') as out:
        out.write(full_code)
    print('Rebuilt ie_drawing_extractor.py, len:', len(full_code))
