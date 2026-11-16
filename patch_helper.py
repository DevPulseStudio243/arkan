import os
with open('arh_document_processor.py', encoding='utf-8') as f:
    text = f.read()

helper_code = '''
    def _extract_page_blocks(self, file_path: str) -> list:
        """Extrait les blocs de texte avec leurs coordonnées (bounding boxes) pour chaque page."""
        blocks_data = []
        try:
            import fitz
            doc = fitz.open(file_path)
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_dict = page.get_text("dict")
                page_blocks = []
                for block in page_dict.get("blocks", []):
                    if block.get("type") == 0:  # Text block
                        block_text = ""
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                block_text += span.get("text", "")
                        if block_text.strip():
                            bbox = block.get("bbox", [0, 0, 0, 0])
                            page_blocks.append({
                                "text": block_text.strip(),
                                "bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
                                "page": page_idx + 1
                            })
                blocks_data.append({
                    "file": os.path.basename(file_path),
                    "page": page_idx + 1,
                    "blocks": page_blocks,
                    "page_width": page_dict.get("width", 595),
                    "page_height": page_dict.get("height", 842)
                })
            doc.close()
        except Exception as e:
            logger.warning("[ARH-BBox] Erreur extraction blocs %s: %s", file_path, e)
        return blocks_data
'''

# Find the end of _extract_pdf_text_with_pages
import re
match = re.search(r'        return text, page_spans, blocks_data\n', text)
if match:
    insert_pos = match.end()
    text = text[:insert_pos] + helper_code + text[insert_pos:]
    with open('arh_document_processor.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Added _extract_page_blocks')
else:
    print('Could not find insertion point')
