# ============================================================
#  DEERFLOW LITE - IBM Docling Extractor Module
#  Extraction haute fidélité (tables, structures) pour PDF
# ============================================================

import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger("deerflow.docling")

class DoclingExtractor:
    """Wrapper pour IBM Docling permettant l'extraction de PDF complexes."""

    def __init__(self):
        self._converter = None
        self._initialized = False

    def _ensure_initialized(self):
        """Initialisation paresseuse de Docling."""
        if self._initialized:
            return
        try:
            from docling.document_converter import DocumentConverter
            # Initialise le convertisseur (charge les modèles locaux ou les télécharge)
            self._converter = DocumentConverter()
            logger.info("IBM Docling DocumentConverter initialisé avec succès.")
        except Exception as e:
            logger.error(f"Impossible d'initialiser IBM Docling: {e}")
            self._converter = None
        self._initialized = True

    def disponible(self) -> bool:
        """Vérifie si Docling est disponible et prêt à l'emploi."""
        self._ensure_initialized()
        return self._converter is not None

    def extract_pdf(self, filepath: str) -> Dict[str, Any]:
        """
        Extrait le contenu d'un PDF technique avec Docling :
        - Conversion du document complet en Markdown
        - Extraction des tables structurées en Markdown
        - Métadonnées et nombre de pages
        """
        if not self.disponible():
            logger.warning("Docling non disponible. Extraction impossible.")
            return {}

        try:
            logger.info(f"Début de l'extraction Docling pour: {filepath}")
            result = self._converter.convert(filepath)
            
            # 1. Obtenir le texte en Markdown
            markdown_text = result.document.export_to_markdown()
            
            # 2. Extraire les tables sous forme de Markdown
            tables = []
            # Parcourir les éléments du document pour extraire les tables
            # Dans docling 2.x, result.document possède des structures d'éléments
            try:
                for element, _ in result.document.iterate_elements():
                    # Vérifier si l'élément ressemble à une table ou s'il s'agit d'une table
                    if element.__class__.__name__ == "TableItem" or hasattr(element, "export_to_markdown"):
                        if element.__class__.__name__ == "TableItem":
                            table_md = element.export_to_markdown()
                            if table_md:
                                tables.append(table_md)
            except Exception as e:
                logger.warning(f"Erreur lors de l'itération des tables Docling: {e}")

            # 3. Récupérer les métadonnées de base
            pages_count = getattr(result.document, "pages", None)
            if not pages_count and hasattr(result, "pages"):
                pages_count = len(result.pages)
            if not pages_count:
                pages_count = 1

            metadata = {
                "title": getattr(result.document, "title", ""),
                "pages": pages_count,
            }

            logger.info(f"Extraction Docling réussie pour {filepath} | {pages_count} pages | {len(tables)} tables trouvées.")
            return {
                "text": markdown_text,
                "tables": tables,
                "metadata": metadata,
                "pages": pages_count,
            }

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction Docling de {filepath}: {e}", exc_info=True)
            return {}


_docling_instance = None

def get_docling_extractor() -> DoclingExtractor:
    """Retourne l'instance singleton de DoclingExtractor."""
    global _docling_instance
    if _docling_instance is None:
        _docling_instance = DoclingExtractor()
    return _docling_instance
