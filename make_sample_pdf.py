"""
make_sample_pdf.py
==================
Génère le PDF de test vectoriel synthétique pour valider le pipeline
circuit_graph, pid_viewer et test_pid.
"""

import fitz

def make(pdf_path: str):
    doc = fitz.open()
    page = doc.new_page(width=600, height=500)

    # 1. Équipements (rectangles avec width >= 30, height >= 30)
    # V-101 : center (90, 300), w=80, h=100 -> rect (50, 250, 130, 350)
    page.draw_rect(fitz.Rect(50, 250, 130, 350), color=(0, 0, 0), width=1.5)
    page.insert_text(fitz.Point(70, 305), "V-101", fontsize=10)

    # V-102 : center (490, 300), w=80, h=100 -> rect (450, 250, 530, 350)
    page.draw_rect(fitz.Rect(450, 250, 530, 350), color=(0, 0, 0), width=1.5)
    page.insert_text(fitz.Point(470, 305), "V-102", fontsize=10)

    # TK-201 : center (490, 115), w=80, h=70 -> rect (450, 80, 530, 150)
    page.draw_rect(fitz.Rect(450, 80, 530, 150), color=(0, 0, 0), width=1.5)
    page.insert_text(fitz.Point(465, 120), "TK-201", fontsize=10)

    # 2. Vannes (petites formes fermées <= 30)
    # HV-101 : center (200, 300), w=20, h=12 -> rect (190, 294, 210, 306)
    page.draw_rect(fitz.Rect(190, 294, 210, 306), color=(0, 0, 0), fill=(0.8, 0.8, 0.8), width=1.0)
    page.insert_text(fitz.Point(180, 285), "HV-101", fontsize=9)

    # XV-102 : center (370, 300), w=20, h=12 -> rect (360, 294, 380, 306)
    page.draw_rect(fitz.Rect(360, 294, 380, 306), color=(0, 0, 0), fill=(0.8, 0.8, 0.8), width=1.0)
    page.insert_text(fitz.Point(350, 285), "XV-102", fontsize=9)

    # HV-103 : center (370, 115), w=20, h=12 -> rect (360, 109, 380, 121)
    page.draw_rect(fitz.Rect(360, 109, 380, 121), color=(0, 0, 0), fill=(0.8, 0.8, 0.8), width=1.0)
    page.insert_text(fitz.Point(350, 100), "HV-103", fontsize=9)

    # 3. Flèche de flux : triangle fermé de 3 lignes max(w,h) <= 14
    # Points : (238, 295), (238, 305), (250, 300) -> cx=244, cy=300, w=12, h=10
    shape = page.new_shape()
    shape.draw_line(fitz.Point(238, 295), fitz.Point(238, 305))
    shape.draw_line(fitz.Point(238, 305), fitz.Point(250, 300))
    shape.draw_line(fitz.Point(250, 300), fitz.Point(238, 295))
    shape.finish(color=(0, 0, 0), fill=(0, 0, 0), closePath=True)
    shape.commit()

    # 4. Segments de tuyauterie (lignes simples)
    lines = [
        (fitz.Point(130, 300), fitz.Point(190, 300)),
        (fitz.Point(210, 300), fitz.Point(300, 300)),
        (fitz.Point(300, 300), fitz.Point(360, 300)),
        (fitz.Point(380, 300), fitz.Point(450, 300)),
        (fitz.Point(300, 300), fitz.Point(300, 115)),
        (fitz.Point(300, 115), fitz.Point(360, 115)),
        (fitz.Point(380, 115), fitz.Point(450, 115)),
    ]
    for p1, p2 in lines:
        page.draw_line(p1, p2, color=(0, 0, 0), width=1.5)

    # 5. Étiquettes de lignes
    page.insert_text(fitz.Point(140, 290), '10"-FG-5001-CS150', fontsize=9)
    page.insert_text(fitz.Point(310, 290), '10"-FG-5003-CS150', fontsize=9)
    page.insert_text(fitz.Point(310, 108), '4"-FG-5002-CS150', fontsize=9)

    doc.save(pdf_path)
    doc.close()

if __name__ == "__main__":
    make("sample.pdf")
    print("sample.pdf created successfully.")
