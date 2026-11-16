import os
import logging
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger(__name__)

class VisionGenerator:
    """
    Générateur de visuels techniques pour DeerFlow Lite.
    Permet de créer des infographies de résumé de projet.
    """
    def __init__(self, output_dir="generated_visuals"):
        self.output_dir = Path(os.getcwd()) / output_dir
        self.output_dir.mkdir(exist_ok=True)
        
    def generate_project_summary_card(self, project_name, sections):
        """
        Génère une carte de résumé visuelle.
        sections: list of dicts {title, points}
        """
        if not HAS_PIL:
            logger.warning("Pillow non installé - génération visuelle impossible")
            return None
        try:
            # Paramètres de style
            width, height = 1200, 800
            bg_color = (24, 24, 26) # Anthropic Dark
            accent_color = (212, 163, 115) # Gold
            text_color = (237, 237, 237) # Whiteish
            
            # Création de l'image
            img = Image.new('RGB', (width, height), color=bg_color)
            draw = ImageDraw.Draw(img)
            
            # Essayer de charger une police, sinon utiliser la police par défaut
            try:
                # Sur Windows, on peut chercher Arial
                font_path = "arial.ttf"
                title_font = ImageFont.truetype(font_path, 40)
                section_font = ImageFont.truetype(font_path, 30)
                point_font = ImageFont.truetype(font_path, 22)
            except:
                title_font = ImageFont.load_default()
                section_font = ImageFont.load_default()
                point_font = ImageFont.load_default()
            
            # Titre
            draw.rectangle([0, 0, width, 100], fill=(39, 39, 42))
            draw.text((40, 30), f"RÉSUMÉ DE PROJET : {project_name.upper()}", fill=accent_color, font=title_font)
            
            # Dessiner les sections
            y_offset = 150
            for section in sections:
                title = section.get("title", "Section")
                points = section.get("points", [])
                
                # Header de section
                draw.text((40, y_offset), title.upper(), fill=accent_color, font=section_font)
                draw.line([40, y_offset + 35, 350, y_offset + 35], fill=accent_color, width=2)
                
                y_offset += 60
                for pt in points:
                    # Gérer le wrapping simple
                    if len(pt) > 80:
                        pt_text = pt[:77] + "..."
                    else:
                        pt_text = pt
                    draw.text((60, y_offset), f"• {pt_text}", fill=text_color, font=point_font)
                    y_offset += 40
                
                y_offset += 40
                if y_offset > height - 100:
                    break

            # Logo / Footer
            draw.text((width - 250, height - 50), "DEERFLOW LITE AI SYSTEM", fill=(100, 100, 100))
            
            output_filename = f"summary_{project_name.lower().replace(' ', '_')}.png"
            output_path = self.output_dir / output_filename
            img.save(output_path)
            logger.info(f"Visual summary generated at {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Failed to generate visual: {e}", exc_info=True)
            return None

# Singleton
_generator = VisionGenerator()

def get_vision_generator():
    return _generator
