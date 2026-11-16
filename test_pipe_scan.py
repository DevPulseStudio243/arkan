import fitz

doc = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
total_pipes = 0
for page_idx in range(2, 33):
    p = doc[page_idx]
    words = p.get_text('words')
    pipe_ns_words = [w for w in words if w[0] > 750 and 805 <= w[1] <= 822]
    cl_len_words = [w for w in words if w[0] > 750 and 820 <= w[1] <= 835]
    ns_vals = [w for w in sorted(pipe_ns_words, key=lambda x: x[0]) if w[4].upper() not in ('PIPE', 'NS')]
    p_sheet = []
    for nw in ns_vals:
        matching_len = [w for w in cl_len_words if abs(w[0] - nw[0]) < 18]
        if matching_len:
            raw_sz = nw[4].strip()
            sz_str = raw_sz if '"' in raw_sz else f'{raw_sz}"'
            try:
                l_val = float(matching_len[0][4].replace(',', '.'))
                if l_val > 0:
                    p_sheet.append((sz_str, l_val))
            except ValueError:
                pass
    total_pipes += len(p_sheet)
    print(f'Sheet {page_idx+1}: {len(p_sheet)} pipes -> {p_sheet}')
print('Total pipes from cartouche tables:', total_pipes)
