import cv2, sys
sys.stdout.reconfigure(encoding='utf-8')
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
img = cv2.imread('d:/DATA BASE IA/qte_col.png')

tests = [
    ('Row 1 (Pipe)', 130, 180, 40, 110),
    ('Row 2 (Elbow 90)', 255, 295, 55, 85),
    ('Row 3 (Elbow 45)', 330, 370, 55, 85),
    ('Row 4 (Flange)', 455, 495, 55, 85),
    ('Row 5 (Bolts)', 580, 620, 50, 100),
    ('Row 6 (Gasket)', 655, 695, 55, 85),
    ('Row 7 (Valve)', 780, 820, 55, 85),
]

for name, y1, y2, x1, x2 in tests:
    patch = img[y1:y2, x1:x2]
    patch_pad = cv2.copyMakeBorder(patch, 15, 15, 25, 25, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    res = ocr.text_recognizer([patch_pad])
    text = res[0][0][0] if res and res[0] else ''
    score = float(res[0][0][1]) if res and res[0] else 0.0
    print(f'{name:20s}: text="{text}" score={score:.2f}')
