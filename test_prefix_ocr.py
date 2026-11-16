import cv2, sys, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()

for r in range(1, 8):
    cell = cv2.imread(f'd:/DATA BASE IA/cell_r{r}.png')
    inner = cell[5:-5, 18:-18]
    ih, iw = inner.shape[:2]
    
    # Create prefix image with "QTE: "
    prefix = np.ones((ih, 80, 3), dtype=np.uint8) * 255
    cv2.putText(prefix, "QTE ", (5, int(ih*0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    
    combined = np.hstack([prefix, inner])
    pad = cv2.copyMakeBorder(combined, 15, 15, 20, 20, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    
    res, _ = ocr(pad)
    txt = res[0][1] if res else ''
    score = float(res[0][2]) if res else 0.0
    print(f'Row {r} with prefix: "{txt}" (score: {score:.2f})')
