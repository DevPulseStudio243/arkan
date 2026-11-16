import os
with open('arh_document_processor.py', encoding='utf-8') as f:
    text = f.read()

# Fix the broken part of _search_per_doc and re-insert _detect_visual_stamps_and_signatures
import re

# find the broken section
broken_pattern = r'            m = re\.search\(pattern, text_upper, flags\)\n                logger\.error\("\[ARH-Vision\] Erreur ouverture PDF %s: %s", fp, e\)'

# Replace the whole chunk from the start of the broken part up to def _verify_engineering_calculations
start_idx = text.find('        for d in parsed_docs:\n            text_upper = d.get("text", "").upper()\n            m = re.search(pattern, text_upper, flags)')
end_idx = text.find('    def _verify_engineering_calculations(')

if start_idx != -1 and end_idx != -1:
    fixed_code = '''        for d in parsed_docs:
            text_upper = d.get("text", "").upper()
            m = re.search(pattern, text_upper, flags)
            if m:
                page = self._page_at_offset(d.get("page_spans", []), m.start())
                return m, d.get("file_name", "?"), page
        return None, None, None

    def _detect_visual_stamps_and_signatures(self, file_paths: list, page_spans: list) -> dict:
        """Détecte visuellement les cachets, tampons et signatures sur chaque page via Vision IA."""
        results = {
            "stamps_detected": [],
            "signatures_detected": [],
            "pages_without_stamp": [],
            "pages_with_stamp": [],
            "confidence_scores": {},
            "vision_analysis": []
        }
        
        try:
            import fitz
        except ImportError:
            logger.warning("[ARH-Vision] PyMuPDF non disponible pour détection visuelle")
            return results
        
        for fp in file_paths:
            try:
                doc = fitz.open(fp)
                fname = os.path.basename(fp)
                # Only check key pages: first, last, and pages likely to have stamps
                pages_to_check = set()
                pages_to_check.add(0)  # First page
                pages_to_check.add(len(doc) - 1)  # Last page
                # Check pages that contain certificate-like content
                for i in range(min(len(doc), 50)):  # Limit to 50 pages for performance
                    page = doc[i]
                    page_text = page.get_text().upper()
                    if any(kw in page_text for kw in ['CERTIFICAT', 'CERTIFICATE', 'APPROUVE', 'APPROVED', 
                                                  'INSPECTION', 'TEST REPORT', 'PV', 'PROCES VERBAL',
                                                  'HYDROTEST', 'EPREUVE', 'CONFORMITE', 'CONFORMITY']):
                        pages_to_check.add(i)
                
                for page_idx in sorted(pages_to_check):
                    if page_idx >= len(doc):
                        continue
                    page = doc[page_idx]
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))  # 225 DPI balance
                    img_bytes = pix.tobytes("png")
                    
                    import base64
                    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                    
                    # Call Ollama Vision API
                    try:
                        import httpx
                        import json as json_mod
                        prompt = """Analyze this document page carefully. Answer these questions in JSON format:
{
  "has_official_stamp": true/false,
  "stamp_count": number,
  "stamp_descriptions": ["description of each stamp found"],
  "stamp_colors": ["blue", "red", "black"],
  "has_signature": true/false,
  "signature_count": number,
  "is_original_document": true/false,
  "has_approval_marking": true/false,
  "organism_detected": "name of inspection organism if visible",
  "confidence": 0.0-1.0
}
Only return JSON, no other text."""
                        
                        resp = httpx.post(
                            "http://localhost:11434/api/generate",
                            json={
                                "model": "qwen2.5vl:3b",
                                "prompt": prompt,
                                "images": [img_b64],
                                "stream": False,
                                "options": {"temperature": 0.1, "num_predict": 500}
                            },
                            timeout=60.0
                        )
                        
                        if resp.status_code == 200:
                            response_text = resp.json().get("response", "")
                            # Try to parse JSON from response
                            import re
                            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
                            if json_match:
                                vision_data = json_mod.loads(json_match.group())
                            else:
                                vision_data = {"raw_response": response_text, "confidence": 0.3}
                            
                            vision_data["file"] = fname
                            vision_data["page"] = page_idx + 1
                            results["vision_analysis"].append(vision_data)
                            
                            if vision_data.get("has_official_stamp"):
                                results["stamps_detected"].append({
                                    "file": fname, "page": page_idx + 1,
                                    "descriptions": vision_data.get("stamp_descriptions", []),
                                    "colors": vision_data.get("stamp_colors", []),
                                    "organism": vision_data.get("organism_detected", ""),
                                    "confidence": vision_data.get("confidence", 0.5)
                                })
                                results["pages_with_stamp"].append(page_idx + 1)
                            else:
                                results["pages_without_stamp"].append({"file": fname, "page": page_idx + 1})
                            
                            if vision_data.get("has_signature"):
                                results["signatures_detected"].append({
                                    "file": fname, "page": page_idx + 1,
                                    "count": vision_data.get("signature_count", 1),
                                    "confidence": vision_data.get("confidence", 0.5)
                                })
                            
                            results["confidence_scores"][f"{fname}_p{page_idx+1}"] = vision_data.get("confidence", 0.5)
                    
                    except Exception as ve:
                        logger.warning("[ARH-Vision] Erreur analyse page %d de %s: %s", page_idx+1, fname, ve)
                
                doc.close()
            except Exception as e:
                logger.error("[ARH-Vision] Erreur ouverture PDF %s: %s", fp, e)
        
        logger.info("[ARH-Vision] Analyse visuelle: %d cachets, %d signatures détectés sur %d pages",
                    len(results['stamps_detected']), len(results['signatures_detected']),
                    len(results.get('vision_analysis', [])))
        return results

'''
    
    new_text = text[:start_idx] + fixed_code + text[end_idx:]
    with open('arh_document_processor.py', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print("Fixed _search_per_doc and added _detect_visual_stamps_and_signatures")
else:
    print("Could not find start or end index")

