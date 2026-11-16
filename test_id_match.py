import cv2, numpy as np

id_templates = {}
for i in range(1, 8):
    cell = cv2.imread(f'd:/DATA BASE IA/id_r{i}.png', cv2.IMREAD_GRAYSCALE)
    _, inv = cv2.threshold(cell, 200, 255, cv2.THRESH_BINARY_INV)
    inv[:, :5] = 0
    inv[:, -8:] = 0
    pts = np.where(inv > 128)
    if len(pts[0]) > 0:
        y1, y2 = pts[0].min(), pts[0].max() + 1
        x1, x2 = pts[1].min(), pts[1].max() + 1
        id_templates[str(i)] = cell[y1:y2, x1:x2]

for r in range(1, 8):
    cell = cv2.imread(f'd:/DATA BASE IA/cell_r{r}.png', cv2.IMREAD_GRAYSCALE)
    inner = cell[5:-5, 18:-18]
    best_digit = None
    best_score = -1
    for d, tmpl in id_templates.items():
        if tmpl.shape[0] < inner.shape[0] and tmpl.shape[1] < inner.shape[1]:
            res = cv2.matchTemplate(inner, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = max_val
                best_digit = d
    print(f'Row {r} QTE matched: {best_digit} (correlation={best_score:.3f})')
