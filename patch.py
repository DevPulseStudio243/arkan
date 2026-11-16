import os
with open('arh_document_processor.py', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'def _extract_pdf_text_with_pages(self, file_path: str) -> Tuple[str, List[Dict[str, Any]]]:',
    'def _extract_pdf_text_with_pages(self, file_path: str) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:'
)

old_init = '''        text = ""
        page_spans: List[Dict[str, Any]] = []
        doc_fitz = None'''
new_init = '''        text = ""
        page_spans: List[Dict[str, Any]] = []
        blocks_data: List[Dict[str, Any]] = []
        doc_fitz = None'''
text = text.replace(old_init, new_init)

old_loop = '''            for i, page in enumerate(doc_fitz):
                page_text = page.get_text()
                parts.append(page_text)
                start = offset
                end = offset + len(page_text)
                page_spans.append({"page": i + 1, "start": start, "end": end})
                offset = end + 1  # +1 pour le "\\n" de jonction'''
new_loop = '''            for i, page in enumerate(doc_fitz):
                page_text = page.get_text()
                parts.append(page_text)
                start = offset
                end = offset + len(page_text)
                page_spans.append({"page": i + 1, "start": start, "end": end})
                offset = end + 1  # +1 pour le "\\n" de jonction
                
                page_dict = page.get_text("dict")
                page_blocks = []
                for block in page_dict.get("blocks", []):
                    if block.get("type") == 0:
                        b_text = ""
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                b_text += span.get("text", "")
                        if b_text.strip():
                            bbox = block.get("bbox", [0, 0, 0, 0])
                            page_blocks.append({
                                "text": b_text.strip(),
                                "bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
                                "page": i + 1
                            })
                blocks_data.append({
                    "file": os.path.basename(file_path),
                    "page": i + 1,
                    "blocks": page_blocks,
                    "page_width": page_dict.get("width", 595),
                    "page_height": page_dict.get("height", 842)
                })'''
text = text.replace(old_loop, new_loop)

text = text.replace('        return text, page_spans', '        return text, page_spans, blocks_data')

with open('arh_document_processor.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Updated _extract_pdf_text_with_pages')
