import cv2, sys
sys.stdout.reconfigure(encoding='utf-8')
from rapidocr_onnxruntime import RapidOCR
ocr = RapidOCR()

for r in range(1, 8):
    cell = cv2.imread(f'd:/DATA BASE IA/cell_r{r}.png')
    # Remove cell borders by cropping inner region
    inner = cell[5:-5, 18:-18]
    pad = cv2.copyMakeBorder(inner, 15, 15, 25, 25, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    res = ocr.text_recognizer([pad])
    txt = res[0][0][0] if res and res[0] else ''
    score = float(res[0][0][1]) if res and res[0] else 0.0
    print(f'Row {r}: "{txt}" (score: {score:.2f})')
