import shutil

shutil.copy(r'd:\DATA BASE IA\temp_zip_inspect\arh_document_processor (2).py', r'd:\DATA BASE IA\arh_document_processor.py')
with open(r'd:\DATA BASE IA\arh_document_processor.py', encoding='utf-8') as f:
    content = f.read()

target = """        if len(text.strip()) < 100:
            # Fallback OCR / Vision — uniquement la page 1 (limite connue : un document
            # scanné multi-pages n'aura de traçabilité fiable que pour sa 1ère page).
            ocr_text = ""
            if doc_fitz is not None and len(doc_fitz) > 0:
                try:
                    page = doc_fitz[0]
                    pix = page.get_pixmap()

                    try:
                        import pytesseract
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        ocr_text = pytesseract.image_to_string(img)
                    except (ImportError, Exception):
                        try:
                            from file_processor import _call_vision_model_b64
                            import base64
                            b64 = base64.b64encode(pix.tobytes("png")).decode()
                            ocr_text = _call_vision_model_b64(b64, "Page 1 OCR Fallback")
                        except Exception:
                            pass
                except Exception:
                    pass

            if len(ocr_text.strip()) > 20:
                start = len(text) + 1
                text = text + "\\n" + ocr_text
                page_spans.append({"page": 1, "start": start, "end": start + len(ocr_text), "ocr": True})"""

replacement = """        if len(text.strip()) < 100:
            # Fallback OCR PaddleOCR / RapidOCR (Multi-Pages, 300 DPI) avec traçabilité page_spans
            try:
                from arh_ocr_engine import extract_ocr_from_image
                if doc_fitz is not None and len(doc_fitz) > 0:
                    ocr_parts = []
                    ocr_spans = []
                    curr_offset = len(text)
                    for i in range(min(len(doc_fitz), 30)):
                        p = doc_fitz[i]
                        pix = p.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                        p_txt = extract_ocr_from_image(pix.tobytes("png"))
                        if p_txt and len(p_txt.strip()) > 5:
                            ocr_parts.append(p_txt)
                            st = curr_offset
                            en = curr_offset + len(p_txt)
                            ocr_spans.append({"page": i + 1, "start": st, "end": en, "ocr": True})
                            curr_offset = en + 1
                    if ocr_parts:
                        text = text + "\\n" + "\\n".join(ocr_parts)
                        page_spans = ocr_spans
            except Exception as e:
                logger.warning(f"[ARH-OCR] Erreur PaddleOCR: {e}")"""

if target in content:
    content = content.replace(target, replacement)
    with open(r'd:\DATA BASE IA\arh_document_processor.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Clean replacement succeeded!")
else:
    print("Target not found, writing arh_document_processor.py directly.")
