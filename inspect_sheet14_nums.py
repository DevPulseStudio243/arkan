import fitz
import re
import math

doc = fitz.open(r'C:\Users\MSI\Desktop\C3421-ROK1-300-PIG-DW-300016.pdf')
p14 = doc[13] # Sheet 14 (Orig items = 6: item_no 1 to 6)
words = p14.get_text('words')
d_words = [w for w in words if w[0] < 815 and w[1] < 670]

# Check words with digits 1..25
num_words = [w for w in d_words if re.match(r'^\d{1,2}$', w[4].strip())]
print(f"Total numeric words on Sheet 14: {len(num_words)}")
for w in sorted(num_words, key=lambda x: (int(x[4]), x[1])):
    height = w[3] - w[1]
    width = w[2] - w[0]
    # Check if there is [ or < near it
    near = [nw[4] for nw in d_words if math.hypot(nw[0]-w[0], nw[1]-w[1]) < 25.0 and nw != w]
    print(f"  Word '{w[4]}': h={height:.2f}, w={width:.2f}, pos=({w[0]:.1f}, {w[1]:.1f}) -> near: {near}")
