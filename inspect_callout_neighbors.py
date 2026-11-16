import fitz
import math

doc = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
p = doc[8] # Sheet 9
words = p.get_text('words')
d_words = [w for w in words if w[0] < 815 and w[1] < 670]

for target in ['3', '4', '11', '12']:
    target_words = [w for w in d_words if w[4] == target]
    print(f"\n=== Callout '{target}' ({len(target_words)} matches) ===")
    for tw in target_words:
        # Find all words within radius 60 pt
        neighbors = [
            nw for nw in d_words 
            if math.hypot(nw[0]-tw[0], nw[1]-tw[1]) < 60.0 and nw != tw
        ]
        near_txt = ' '.join(nw[4] for nw in sorted(neighbors, key=lambda x: (x[1], x[0])))
        print(f"  At ({tw[0]:.1f}, {tw[1]:.1f}): nearby words -> {near_txt}")
