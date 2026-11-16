import os
with open('arh_document_processor.py', encoding='utf-8') as f:
    text = f.read()

# Add a dictionary in process_dossier_batch to store evidence
insert_start = text.find('        # 1. Extraction textuelle intégrale & OCR multi-pages')
insert_after_init = text.find('        priority_text_blob = ""\n', insert_start) + len('        priority_text_blob = ""\n')

new_init = '''        all_page_blocks_evidence = []
        all_page_spans = []
'''
text = text[:insert_after_init] + new_init + text[insert_after_init:]

# Update the for fp in file_paths loop to call _extract_page_blocks
loop_insert = text.find('            parsed_docs.append({')
new_loop_logic = '''            blocks = self._extract_page_blocks(fp)
            all_page_blocks_evidence.extend(blocks)
            all_page_spans.extend(page_spans)
            
'''
text = text[:loop_insert] + new_loop_logic + text[loop_insert:]

# Call _detect_visual_stamps_and_signatures before building the final return dict
return_start = text.find('        return {\n            "dossier_id": dossier_id,')
new_vision_call = '''        # Vision IA
        visual_stamp_analysis = self._detect_visual_stamps_and_signatures(file_paths, all_page_spans)

'''
text = text[:return_start] + new_vision_call + text[return_start:]

# Add to the return dict
return_end = text.find('            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n        }')
new_return_fields = '''            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "visual_stamp_analysis": visual_stamp_analysis,
            "page_blocks_evidence": all_page_blocks_evidence
        }'''
text = text[:return_end] + new_return_fields + text[return_end + len('            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n        }')]

with open('arh_document_processor.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated process_dossier_batch")
