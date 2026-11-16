# ============================================================
#  DEERFLOW LITE - Enhanced Multi-Format File Processor
#  Oil & Gas Document Processing Pipeline
#  Handles ALL common file formats with structured extraction,
#  confidence scoring, and graceful degradation.
# ============================================================

from __future__ import annotations

import io
import os
import re
import csv
import json
import base64
import hashlib
import logging
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_VISION_MODEL,
    VISION_CACHE_PATH,
    LLM_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Maximum bytes to read for text-based files before switching to streaming
_MAX_TEXT_BYTES = 50 * 1024 * 1024  # 50 MB
_VISION_MAX_PAGES = 15


# ============================================================
#  Data Structures
# ============================================================

@dataclass
class ExtractionResult:
    """Structured result from file processing."""

    text: str = ""
    structured_data: Dict[str, Any] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_quality: float = 0.0
    format: str = "unknown"
    warnings: List[str] = field(default_factory=list)
    page_count: int = 0
    has_images: bool = False
    language: str = "unknown"
    source: str = ""
    error: Optional[str] = None

    # -- helpers ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for downstream consumers."""
        return {
            "text": self.text,
            "structured_data": self.structured_data,
            "tables": self.tables,
            "metadata": self.metadata,
            "extraction_quality": round(self.extraction_quality, 3),
            "format": self.format,
            "warnings": self.warnings,
            "page_count": self.page_count,
            "has_images": self.has_images,
            "language": self.language,
            "source": self.source,
            "error": self.error,
        }

    # Legacy compat: allow dict-style access for callers that
    # still expect the old dict-based return from extractors.py
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


import sqlite3
import threading

# ============================================================
#  Vision Model Helpers (shared with legacy extractors)
# ============================================================

class SQLiteVisionCache:
    """
    Thread-safe Dict-like wrapper around SQLite vision cache database.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
        self._migrate_json()

    def _init_db(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS vision_cache (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error initializing SQLite vision cache: {e}")

    def _migrate_json(self):
        # The old JSON path is self.db_path with .db replaced by .json
        json_path = self.db_path.replace(".db", ".json")
        if not os.path.exists(json_path):
            return
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if data and isinstance(data, dict):
                with self.lock:
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.executemany(
                        "INSERT OR REPLACE INTO vision_cache (key, value) VALUES (?, ?)",
                        [(k, str(v)) for k, v in data.items()]
                    )
                    conn.commit()
                    conn.close()
                logger.info(f"Successfully migrated {len(data)} entries from old JSON vision cache to SQLite.")
            
            # Rename old json file
            os.rename(json_path, json_path + ".bak")
        except Exception as e:
            logger.error(f"Error migrating JSON vision cache: {e}")

    def __contains__(self, key: str) -> bool:
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM vision_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                conn.close()
                return row is not None
            except Exception:
                return False

    def __getitem__(self, key: str) -> str:
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM vision_cache WHERE key = ?", (key,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    return row[0]
                raise KeyError(key)
            except Exception as e:
                if isinstance(e, KeyError):
                    raise
                return None

    def __setitem__(self, key: str, value: str):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO vision_cache (key, value) VALUES (?, ?)", (key, value))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Error writing to SQLite vision cache: {e}")

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

_vision_cache_instance = None
_vision_cache_lock = threading.Lock()

def _load_vision_cache():
    global _vision_cache_instance
    with _vision_cache_lock:
        if _vision_cache_instance is None:
            _vision_cache_instance = SQLiteVisionCache(VISION_CACHE_PATH)
    return _vision_cache_instance


def _save_vision_cache(cache) -> None:
    """Compatibilité rétrograde — la persistence est gérée automatiquement par SQLiteVisionCache.
    Cette fonction est conservée pour les appelants qui l'utilisent explicitement.
    """
    if cache is not None and hasattr(cache, 'conn') and cache.conn:
        try:
            cache.conn.commit()
        except Exception as e:
            logger.debug(f"_save_vision_cache: commit ignoré ({e})")


def _call_vision_model_b64(b64_image: str, context: str = "") -> str:
    """Call the Ollama vision model with a base64-encoded image."""
    try:
        url = OLLAMA_BASE_URL
        if "ollama:11434" in url:
            url = "http://127.0.0.1:11434"
            
        prompt = (
            "Extract ALL text visible in this technical document image. "
            "Include equipment tags, numbers, labels, table data. "
            "Return ONLY the extracted text, nothing else. "
            "Do NOT invent or assume any content not visible."
        )
        response = httpx.post(
            f"{url}/api/generate",
            json={
                "model": OLLAMA_VISION_MODEL,
                "prompt": prompt,
                "images": [b64_image],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=LLM_TIMEOUT,
        )
        if response.status_code == 200:
            return response.json().get("response", "")
    except Exception as exc:
        logger.error("Vision model call failed (%s): %s", context, exc)
    return ""


# ============================================================
#  EncodingDetector
# ============================================================

class EncodingDetector:
    """Detect file encoding for text-based files.

    Tries a prioritised list of encodings, optionally falling back to
    ``chardet`` if it is installed.
    """

    CANDIDATES: List[str] = [
        "utf-8-sig",
        "utf-8",
        "latin-1",
        "windows-1252",
        "iso-8859-15",
        "cp1250",
        "ascii",
    ]

    @classmethod
    def detect(cls, file_path: str, sample_size: int = 8192) -> str:
        """Return the most likely encoding for *file_path*."""
        raw: bytes = b""
        try:
            with open(file_path, "rb") as fh:
                raw = fh.read(sample_size)
        except Exception:
            return "utf-8"

        return cls.detect_bytes(raw)

    @classmethod
    def detect_bytes(cls, raw: bytes) -> str:
        """Return the most likely encoding for raw bytes."""
        for enc in cls.CANDIDATES:
            try:
                raw.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue

        # Fallback: try chardet if available
        try:
            import chardet  # type: ignore
            result = chardet.detect(raw)
            if result and result.get("encoding"):
                return result["encoding"]
        except ImportError:
            pass

        return "utf-8"


# ============================================================
#  MetadataExtractor
# ============================================================

class MetadataExtractor:
    """Extract document metadata from filenames and content.

    Understands common Oil & Gas document naming conventions such as::

        PROJECT-DISC-TYPE-SEQ_REV.ext
        e.g.  PRJ-PROC-PID-001_RevB.pdf
    """

    # Oil & Gas discipline codes
    _DISCIPLINE_CODES: Dict[str, str] = {
        "PROC": "Process", "MECH": "Mechanical", "ELEC": "Electrical",
        "INST": "Instrumentation", "PIPE": "Piping", "CIVIL": "Civil",
        "STRUCT": "Structural", "HSE": "HSE", "HVAC": "HVAC",
        "TELE": "Telecom", "CTRL": "Controls",
    }

    # Document type codes
    _DOC_TYPE_CODES: Dict[str, str] = {
        "PID": "P&ID", "PFD": "Process Flow Diagram",
        "SLD": "Single Line Diagram", "GA": "General Arrangement",
        "ISO": "Isometric", "SPEC": "Specification",
        "MTO": "Material Take-Off", "MR": "Material Requisition",
        "DS": "Datasheet", "REP": "Report", "DWG": "Drawing",
        "MAN": "Manual", "PROC": "Procedure",
    }

    _REV_PATTERN = re.compile(
        r"[_\-\s]?[Rr]ev(?:ision)?[\s._\-]?([A-Z0-9]+)", re.IGNORECASE
    )
    _DATE_PATTERNS = [
        re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
        re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b"),
        re.compile(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b", re.IGNORECASE),
    ]

    @classmethod
    def extract_from_filename(cls, filename: str) -> Dict[str, Any]:
        """Parse an O&G document filename for metadata."""
        meta: Dict[str, Any] = {"filename": filename}
        stem = Path(filename).stem

        # Revision
        rev_match = cls._REV_PATTERN.search(stem)
        if rev_match:
            meta["revision"] = rev_match.group(1)

        # Discipline / document type from dash-separated segments
        parts = re.split(r"[-_]", stem)
        for part in parts:
            upper = part.upper()
            if upper in cls._DISCIPLINE_CODES:
                meta["discipline"] = cls._DISCIPLINE_CODES[upper]
            if upper in cls._DOC_TYPE_CODES:
                meta["document_type"] = cls._DOC_TYPE_CODES[upper]

        # Sequence number: first purely numeric segment with 2+ digits
        for part in parts:
            if re.fullmatch(r"\d{2,}", part):
                meta["sequence_number"] = part
                break

        return meta

    @classmethod
    def extract_from_content(cls, text: str) -> Dict[str, Any]:
        """Extract revision numbers, dates, and authors from content."""
        meta: Dict[str, Any] = {}
        if not text:
            return meta

        # Use only first 5000 chars for efficiency
        head = text[:5000]

        # Revision
        rev_match = cls._REV_PATTERN.search(head)
        if rev_match:
            meta["revision"] = rev_match.group(1)

        # Dates
        for pat in cls._DATE_PATTERNS:
            m = pat.search(head)
            if m:
                meta.setdefault("dates_found", []).append(m.group(1))

        # Simple author detection
        author_match = re.search(
            r"(?:Author|Prepared by|Auteur|Redige par)[:\s]+([^\n,;]{3,50})",
            head,
            re.IGNORECASE,
        )
        if author_match:
            meta["author"] = author_match.group(1).strip()

        # Document number patterns (e.g., DOC-XXXX-YYYY-ZZZ)
        doc_num = re.search(r"\b([A-Z]{2,5}-\d{3,}-[A-Z0-9-]+)\b", head)
        if doc_num:
            meta["document_number"] = doc_num.group(1)

        return meta


# ============================================================
#  TableExtractor
# ============================================================

class TableExtractor:
    """Specialised table extraction from various content formats."""

    @staticmethod
    def extract_from_text(text: str) -> List[Dict[str, Any]]:
        """Detect and parse pipe-delimited or aligned-column tables."""
        tables: List[Dict[str, Any]] = []
        if not text:
            return tables

        # Detect pipe-delimited tables (common in our own extraction output)
        lines = text.splitlines()
        current_rows: List[List[str]] = []
        for line in lines:
            stripped = line.strip()
            if "|" in stripped:
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if cells:
                    current_rows.append(cells)
            else:
                if len(current_rows) >= 2:
                    tables.append(TableExtractor._rows_to_table(current_rows))
                current_rows = []
        if len(current_rows) >= 2:
            tables.append(TableExtractor._rows_to_table(current_rows))

        return tables

    @staticmethod
    def extract_from_html(html: str) -> List[Dict[str, Any]]:
        """Parse HTML ``<table>`` elements into list-of-dicts."""
        tables: List[Dict[str, Any]] = []
        if not html:
            return tables

        table_pattern = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
        tag_strip = re.compile(r"<[^>]+>")

        for table_match in table_pattern.finditer(html):
            rows_raw = row_pattern.findall(table_match.group(1))
            parsed_rows: List[List[str]] = []
            for row_html in rows_raw:
                cells = [tag_strip.sub("", c).strip() for c in cell_pattern.findall(row_html)]
                if cells:
                    parsed_rows.append(cells)
            if len(parsed_rows) >= 2:
                tables.append(TableExtractor._rows_to_table(parsed_rows))

        return tables

    @staticmethod
    def normalize_table(table: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and normalize an extracted table dict."""
        rows = table.get("rows", [])
        if not rows:
            return table

        cleaned: List[Dict[str, str]] = []
        for row in rows:
            cleaned.append({k: str(v).strip() for k, v in row.items()})
        table["rows"] = cleaned
        return table

    @staticmethod
    def _rows_to_table(raw_rows: List[List[str]]) -> Dict[str, Any]:
        """Convert a list of row-lists into a header+rows dict."""
        headers = raw_rows[0]
        # Filter separator rows (e.g., "---", "===")
        data_rows = [
            r for r in raw_rows[1:]
            if not all(re.fullmatch(r"[-=:]+", c) for c in r)
        ]
        rows: List[Dict[str, str]] = []
        for r in data_rows:
            row_dict: Dict[str, str] = {}
            for idx, h in enumerate(headers):
                row_dict[h] = r[idx] if idx < len(r) else ""
            rows.append(row_dict)
        return {"headers": headers, "rows": rows, "row_count": len(rows)}


# ============================================================
#  Language Detector (lightweight)
# ============================================================

def _detect_language(text: str) -> str:
    """Very lightweight French / English detection."""
    if not text:
        return "unknown"
    sample = text[:3000].lower()
    fr_markers = [
        " le ", " la ", " les ", " des ", " est ", " dans ",
        " pour ", " une ", " avec ", " sur ", " qui ", " que ",
    ]
    en_markers = [
        " the ", " is ", " are ", " for ", " and ", " with ",
        " this ", " that ", " from ", " have ", " was ",
    ]
    fr_score = sum(sample.count(m) for m in fr_markers)
    en_score = sum(sample.count(m) for m in en_markers)
    if fr_score > en_score * 1.2:
        return "fr"
    if en_score > fr_score * 1.2:
        return "en"
    if fr_score > 0 or en_score > 0:
        return "fr" if fr_score >= en_score else "en"
    return "unknown"


# ============================================================
#  FileProcessor - main class (placeholder for per-format methods)
# ============================================================

class FileProcessor:
    """Universal file processor with format auto-detection.

    Usage::

        processor = FileProcessor()
        result = processor.process("/path/to/document.pdf")
        print(result.text)
        print(result.extraction_quality)
    """

    SUPPORTED_EXTENSIONS: Dict[str, str] = {
        # Engineering
        ".pdf": "pdf", ".dxf": "dxf", ".dwg": "dwg",
        # Office
        ".docx": "docx", ".doc": "docx",
        ".xlsx": "xlsx", ".xls": "xlsx",
        ".pptx": "pptx", ".ppt": "pptx",
        # Data
        ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
        ".csv": "csv", ".tsv": "csv",
        # Text
        ".txt": "text", ".log": "text", ".md": "text",
        ".html": "html", ".htm": "html",
        # Image
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".tiff": "image", ".tif": "image", ".bmp": "image",
    }

    def __init__(self) -> None:
        self._table_extractor = TableExtractor()
        self._meta_extractor = MetadataExtractor()
        self._enc_detector = EncodingDetector()

    # ----------------------------------------------------------
    #  Public API
    # ----------------------------------------------------------

    def process(self, file_path: str) -> ExtractionResult:
        """Main entry point -- auto-detect format and process."""
        path = Path(file_path)
        if not path.exists():
            return ExtractionResult(
                source=file_path,
                error=f"File not found: {file_path}",
                warnings=["File does not exist"],
            )

        ext = path.suffix.lower()
        fmt = self.SUPPORTED_EXTENSIONS.get(ext)
        if fmt is None:
            return ExtractionResult(
                source=file_path,
                format=ext,
                error=f"Unsupported format: {ext}",
                warnings=[f"Extension {ext} is not supported"],
            )

        handler = self._HANDLERS.get(fmt)
        if handler is None:
            return ExtractionResult(
                source=file_path,
                format=ext,
                error=f"No handler for format: {fmt}",
            )

        logger.info("Processing %s (format=%s)", file_path, fmt)
        try:
            result: ExtractionResult = handler(self, file_path)
        except Exception as exc:
            logger.exception("Unhandled error processing %s", file_path)
            return ExtractionResult(
                source=file_path,
                format=fmt,
                error=str(exc),
                extraction_quality=0.0,
                warnings=[f"Processing failed: {exc}"],
            )

        # Enrich with metadata & language detection
        result.source = file_path
        if not result.metadata:
            result.metadata = {}
        result.metadata.update(
            self._meta_extractor.extract_from_filename(path.name)
        )
        content_meta = self._meta_extractor.extract_from_content(result.text)
        result.metadata.update(content_meta)

        if result.language == "unknown":
            result.language = _detect_language(result.text)

        # Extract tables from text if none found yet
        if not result.tables and result.text:
            result.tables = self._table_extractor.extract_from_text(result.text)

        return result

    def process_bytes(self, content: bytes, filename: str) -> ExtractionResult:
        """Process from raw bytes (e.g. file upload)."""
        suffix = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return self.process(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ----------------------------------------------------------
    #  Format-specific handlers (placeholder markers below)
    # ----------------------------------------------------------

    # ----------------------------------------------------------
    #  _process_pdf
    # ----------------------------------------------------------

    def _process_pdf(self, file_path: str) -> ExtractionResult:
        """PDF extraction with fallback chain: PyPDF2 -> PyMuPDF -> OCR via vision."""
        result = ExtractionResult(format="pdf")
        warnings: List[str] = []
        pages_text: List[str] = []
        quality = 0.0

        # ---- Attempt 1: PyPDF2 ------------------------------------
        reader = None
        try:
            from PyPDF2 import PdfReader  # type: ignore
            reader = PdfReader(file_path)
            result.page_count = len(reader.pages)
            for page in reader.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
            quality = 0.85
        except Exception as exc:
            warnings.append(f"PyPDF2 failed: {exc}")
            logger.warning("PyPDF2 failed for %s: %s", file_path, exc)

        combined = "\n".join(pages_text)

        # ---- Attempt 2: PyMuPDF if PyPDF2 text is thin ------------
        if len(combined.strip()) < 100 and result.page_count > 0:
            try:
                import fitz  # type: ignore  # PyMuPDF
                doc = fitz.open(file_path)
                result.page_count = len(doc)
                fitz_texts: List[str] = []
                for page in doc:
                    fitz_texts.append(page.get_text())
                fitz_combined = "\n".join(fitz_texts)
                if len(fitz_combined.strip()) > len(combined.strip()):
                    combined = fitz_combined
                    quality = 0.80
                doc.close()
            except ImportError:
                warnings.append("PyMuPDF not installed; skipping fitz fallback")
            except Exception as exc:
                warnings.append(f"PyMuPDF fallback failed: {exc}")

        # ---- Attempt 3: OCR via vision model ----------------------
        if len(combined.strip()) < 100 and result.page_count > 0:
            ocr_text = self._ocr_pdf_via_vision(file_path)
            if ocr_text:
                combined = ocr_text
                quality = 0.55
                result.has_images = True
                warnings.append("Used OCR vision model -- quality may vary")

        # Check for images in pages
        if not result.has_images:
            try:
                if reader:
                    for page in reader.pages[:5]:
                        res = page.get("/Resources")
                        if res and hasattr(res, "get_object"):
                            res = res.get_object()
                        xobj = (res or {}).get("/XObject")
                        if xobj:
                            result.has_images = True
                            break
            except Exception:
                pass

        if not combined.strip():
            quality = 0.0
            warnings.append("No text could be extracted from PDF")

        result.text = combined
        result.extraction_quality = quality
        result.warnings = warnings
        return result

    def _ocr_pdf_via_vision(self, file_path: str) -> str:
        """Render PDF pages to images and OCR via the Ollama vision model."""
        cache = _load_vision_cache()
        try:
            file_hash = hashlib.md5(Path(file_path).read_bytes()).hexdigest()
        except Exception:
            file_hash = hashlib.md5(file_path.encode()).hexdigest()
        if file_hash in cache:
            logger.info("Vision cache hit for %s", file_path)
            return cache[file_hash]

        texts: List[str] = []
        try:
            import fitz  # type: ignore
            doc = fitz.open(file_path)
            max_pages = min(len(doc), _VISION_MAX_PAGES)
            for i in range(max_pages):
                try:
                    mat = fitz.Matrix(150 / 72, 150 / 72)
                    pix = doc[i].get_pixmap(matrix=mat)
                    b64 = base64.b64encode(pix.tobytes("png")).decode()
                    txt = _call_vision_model_b64(b64, f"Page {i + 1}")
                    if txt and len(txt.strip()) > 10:
                        texts.append(f"--- Page {i + 1} ---\n{txt}")
                except Exception as exc:
                    logger.warning("OCR page %d failed: %s", i + 1, exc)
            doc.close()
        except ImportError:
            logger.warning("PyMuPDF not installed; cannot render PDF pages for OCR")
        except Exception as exc:
            logger.error("OCR rendering failed: %s", exc)

        combined = "\n\n".join(texts)
        if combined:
            cache[file_hash] = combined
            _save_vision_cache(cache)
        return combined

    # ----------------------------------------------------------
    #  _process_docx
    # ----------------------------------------------------------

    def _process_docx(self, file_path: str) -> ExtractionResult:
        """Word document with table extraction and structure preservation."""
        result = ExtractionResult(format="docx")
        try:
            from docx import Document  # type: ignore

            doc = Document(file_path)
            paragraphs: List[str] = []
            tables: List[Dict[str, Any]] = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    style = para.style.name if para.style else ""
                    if "Heading" in style or "Titre" in style:
                        paragraphs.append(f"\n## {text}\n")
                    else:
                        paragraphs.append(text)

            for table in doc.tables:
                raw_rows: List[List[str]] = []
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    raw_rows.append(cells)
                if len(raw_rows) >= 2:
                    tbl = TableExtractor._rows_to_table(raw_rows)
                    tables.append(tbl)
                # Also add as text
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        paragraphs.append(" | ".join(cells))

            result.text = "\n".join(paragraphs)
            result.tables = tables
            result.page_count = max(1, len(paragraphs) // 40 + 1)
            result.extraction_quality = 0.90
            result.has_images = any(
                r.element.tag.endswith("drawing") or r.element.tag.endswith("pict")
                for r in doc.inline_shapes
            ) if hasattr(doc, "inline_shapes") else False
        except Exception as exc:
            logger.error("DOCX extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
            result.warnings.append(f"DOCX extraction failed: {exc}")
        return result

    # ----------------------------------------------------------
    #  _process_xlsx
    # ----------------------------------------------------------

    def _process_xlsx(self, file_path: str) -> ExtractionResult:
        """Excel with multi-sheet handling and formula detection."""
        result = ExtractionResult(format="xlsx")
        try:
            from openpyxl import load_workbook  # type: ignore

            wb = load_workbook(file_path, data_only=True)
            sheets_text: List[str] = []
            tables: List[Dict[str, Any]] = []
            has_formulas = False

            # Also load with data_only=False to detect formulas
            try:
                wb_formulas = load_workbook(file_path, data_only=False)
                for ws_f in wb_formulas.worksheets:
                    for row in ws_f.iter_rows(max_row=min(ws_f.max_row or 1, 50), values_only=True):
                        for cell in row:
                            if isinstance(cell, str) and cell.startswith("="):
                                has_formulas = True
                                break
                        if has_formulas:
                            break
                    if has_formulas:
                        break
                wb_formulas.close()
            except Exception:
                pass

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                raw_rows: List[List[str]] = []
                text_rows: List[str] = []

                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    non_empty = [c for c in cells if c]
                    if non_empty:
                        raw_rows.append(cells)
                        text_rows.append(" | ".join(non_empty))

                if text_rows:
                    sheets_text.append(
                        f"=== Sheet: {sheet_name} ===\n" + "\n".join(text_rows)
                    )
                if len(raw_rows) >= 2:
                    tables.append(TableExtractor._rows_to_table(raw_rows))

            result.text = "\n\n".join(sheets_text)
            result.tables = tables
            result.page_count = len(wb.sheetnames)
            result.extraction_quality = 0.90
            if has_formulas:
                result.structured_data["has_formulas"] = True
                result.warnings.append("Workbook contains formulas; values shown are computed results")
            wb.close()
        except Exception as exc:
            logger.error("XLSX extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
            result.warnings.append(f"XLSX extraction failed: {exc}")
        return result

    # ----------------------------------------------------------
    #  _process_csv
    # ----------------------------------------------------------

    def _process_csv(self, file_path: str) -> ExtractionResult:
        """CSV/TSV with delimiter auto-detection and encoding handling."""
        result = ExtractionResult(format="csv")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                sample = fh.read(8192)

            # Auto-detect delimiter
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = "\t" if file_path.lower().endswith(".tsv") else ","

            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                reader = csv.reader(fh, delimiter=delimiter)
                raw_rows: List[List[str]] = []
                text_lines: List[str] = []
                for i, row in enumerate(reader):
                    if i > 50000:
                        result.warnings.append("File truncated at 50 000 rows")
                        break
                    stripped = [c.strip() for c in row]
                    if any(stripped):
                        raw_rows.append(stripped)
                        text_lines.append(delimiter.join(stripped))

            result.text = "\n".join(text_lines)
            if len(raw_rows) >= 2:
                result.tables = [TableExtractor._rows_to_table(raw_rows)]
            result.page_count = 1
            result.extraction_quality = 0.95
        except Exception as exc:
            logger.error("CSV extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
            result.warnings.append(f"CSV extraction failed: {exc}")
        return result

    # ----------------------------------------------------------
    #  _process_pptx
    # ----------------------------------------------------------

    def _process_pptx(self, file_path: str) -> ExtractionResult:
        """PowerPoint with notes and embedded content."""
        result = ExtractionResult(format="pptx")
        try:
            from pptx import Presentation  # type: ignore

            prs = Presentation(file_path)
            slides_text: List[str] = []
            tables: List[Dict[str, Any]] = []

            for i, slide in enumerate(prs.slides):
                parts: List[str] = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            if para.text.strip():
                                parts.append(para.text.strip())
                    if shape.has_table:
                        raw_rows: List[List[str]] = []
                        for row in shape.table.rows:
                            cells = [c.text.strip() for c in row.cells]
                            raw_rows.append(cells)
                            non_empty = [c for c in cells if c]
                            if non_empty:
                                parts.append(" | ".join(non_empty))
                        if len(raw_rows) >= 2:
                            tables.append(TableExtractor._rows_to_table(raw_rows))
                    if hasattr(shape, "image"):
                        result.has_images = True

                # Slide notes
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        parts.append(f"[Notes] {notes}")

                if parts:
                    slides_text.append(f"--- Slide {i + 1} ---\n" + "\n".join(parts))

            result.text = "\n\n".join(slides_text)
            result.tables = tables
            result.page_count = len(prs.slides)
            result.extraction_quality = 0.85
        except Exception as exc:
            logger.error("PPTX extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
            result.warnings.append(f"PPTX extraction failed: {exc}")
        return result

    # ----------------------------------------------------------
    #  _process_xml
    # ----------------------------------------------------------

    def _process_xml(self, file_path: str) -> ExtractionResult:
        """XML with structure-aware text extraction."""
        result = ExtractionResult(format="xml")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                raw = fh.read(_MAX_TEXT_BYTES)

            # Parse the tree
            try:
                root = ET.fromstring(raw)
                texts: List[str] = []

                def _walk(elem: ET.Element, depth: int = 0) -> None:
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if elem.text and elem.text.strip():
                        texts.append(f"{'  ' * depth}{tag}: {elem.text.strip()}")
                    for child in elem:
                        _walk(child, depth + 1)
                    if elem.tail and elem.tail.strip():
                        texts.append(elem.tail.strip())

                _walk(root)
                result.text = "\n".join(texts)
                result.structured_data["root_tag"] = root.tag.split("}")[-1] if "}" in root.tag else root.tag
                result.extraction_quality = 0.90
            except ET.ParseError as exc:
                result.warnings.append(f"XML parse error, falling back to raw text: {exc}")
                result.text = raw
                result.extraction_quality = 0.50

            result.page_count = 1
        except Exception as exc:
            logger.error("XML extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_json
    # ----------------------------------------------------------

    def _process_json(self, file_path: str) -> ExtractionResult:
        """JSON with nested structure flattening."""
        result = ExtractionResult(format="json")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                raw = fh.read(_MAX_TEXT_BYTES)

            try:
                data = json.loads(raw)
                result.structured_data["json_data"] = data

                flat_lines: List[str] = []

                def _flatten(obj: Any, prefix: str = "") -> None:
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            _flatten(v, f"{prefix}{k}.")
                    elif isinstance(obj, list):
                        for i, v in enumerate(obj[:200]):
                            _flatten(v, f"{prefix}[{i}].")
                        if len(obj) > 200:
                            flat_lines.append(f"{prefix}... ({len(obj)} items total)")
                    else:
                        flat_lines.append(f"{prefix.rstrip('.')}: {obj}")

                _flatten(data)
                result.text = "\n".join(flat_lines)
                result.extraction_quality = 0.95
            except json.JSONDecodeError as exc:
                result.warnings.append(f"JSON parse error, using raw text: {exc}")
                result.text = raw
                result.extraction_quality = 0.40

            result.page_count = 1
        except Exception as exc:
            logger.error("JSON extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_yaml
    # ----------------------------------------------------------

    def _process_yaml(self, file_path: str) -> ExtractionResult:
        """YAML files -- read as text, optionally parse structure."""
        result = ExtractionResult(format="yaml")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                raw = fh.read(_MAX_TEXT_BYTES)
            result.text = raw
            result.page_count = 1
            result.extraction_quality = 0.85

            # Try to parse for structured_data
            try:
                import yaml as _yaml  # type: ignore
                data = _yaml.safe_load(raw)
                if isinstance(data, (dict, list)):
                    result.structured_data["yaml_data"] = data
                    result.extraction_quality = 0.95
            except ImportError:
                result.warnings.append("PyYAML not installed; structured parsing skipped")
            except Exception as exc:
                result.warnings.append(f"YAML parse warning: {exc}")
        except Exception as exc:
            logger.error("YAML extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_html
    # ----------------------------------------------------------

    def _process_html(self, file_path: str) -> ExtractionResult:
        """HTML with tag stripping and table extraction."""
        result = ExtractionResult(format="html")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                raw = fh.read(_MAX_TEXT_BYTES)

            # Extract tables first
            result.tables = self._table_extractor.extract_from_html(raw)

            # Strip tags for plain text
            # Remove script/style blocks
            cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            # Replace block-level tags with newlines
            cleaned = re.sub(r"<(br|p|div|h[1-6]|tr|li)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
            # Strip remaining tags
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            # Collapse whitespace
            cleaned = re.sub(r"[ \t]+", " ", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

            result.text = cleaned.strip()
            result.page_count = 1
            result.extraction_quality = 0.80
        except Exception as exc:
            logger.error("HTML extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_image
    # ----------------------------------------------------------

    def _process_image(self, file_path: str) -> ExtractionResult:
        """Image via vision model for P&ID, drawings, etc."""
        result = ExtractionResult(format="image", has_images=True)
        try:
            with open(file_path, "rb") as fh:
                img_bytes = fh.read()

            # Basic metadata via Pillow
            try:
                from PIL import Image  # type: ignore
                img = Image.open(io.BytesIO(img_bytes))
                result.metadata["image_size"] = f"{img.width}x{img.height}"
                result.metadata["image_mode"] = img.mode
                result.page_count = getattr(img, "n_frames", 1)
            except Exception:
                pass

            b64 = base64.b64encode(img_bytes).decode()
            text = _call_vision_model_b64(b64, Path(file_path).name)
            result.text = text
            result.extraction_quality = 0.55 if text.strip() else 0.0
            if not text.strip():
                result.warnings.append("Vision model returned no text for image")
        except Exception as exc:
            logger.error("Image extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_dxf
    # ----------------------------------------------------------

    def _process_dxf(self, file_path: str) -> ExtractionResult:
        """DXF text entity extraction from AutoCAD drawings."""
        result = ExtractionResult(format="dxf")
        try:
            encoding = self._enc_detector.detect(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                raw = fh.read(_MAX_TEXT_BYTES)

            # Try ezdxf first
            try:
                import ezdxf  # type: ignore
                doc = ezdxf.readfile(file_path)
                msp = doc.modelspace()
                texts: List[str] = []
                for entity in msp:
                    if entity.dxftype() in ("TEXT", "MTEXT"):
                        t = entity.dxf.text if hasattr(entity.dxf, "text") else ""
                        if not t and hasattr(entity, "text"):
                            t = entity.text
                        if t and t.strip():
                            texts.append(t.strip())
                    elif entity.dxftype() == "INSERT":
                        name = entity.dxf.name if hasattr(entity.dxf, "name") else ""
                        if name:
                            texts.append(f"[Block: {name}]")

                result.text = "\n".join(texts)
                result.extraction_quality = 0.70 if texts else 0.20
                result.page_count = 1
                result.has_images = True
                return result
            except ImportError:
                result.warnings.append("ezdxf not installed; using regex fallback")
            except Exception as exc:
                result.warnings.append(f"ezdxf failed: {exc}")

            # Fallback: regex-based extraction of TEXT/MTEXT entities
            # DXF text entities follow group code 1 (primary text value)
            lines = raw.splitlines()
            texts = []
            i = 0
            while i < len(lines) - 1:
                code = lines[i].strip()
                value = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if code == "1" and value:
                    # Filter out DXF internal codes
                    if not re.fullmatch(r"[A-Z_]+", value) and len(value) > 1:
                        texts.append(value)
                i += 1

            result.text = "\n".join(texts) if texts else "[DXF file - no text entities extracted]"
            result.extraction_quality = 0.40 if texts else 0.10
            result.page_count = 1
            result.has_images = True
        except Exception as exc:
            logger.error("DXF extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  _process_dwg
    # ----------------------------------------------------------

    def _process_dwg(self, file_path: str) -> ExtractionResult:
        """
        DWG extraction via pid_analyzer.parse_dwg_file().
        Extrait les tags P&ID (équipements, instruments, vannes) du binaire DWG
        en appliquant le même moteur de pattern-matching que pour les PDFs.
        Génère également un rendu visuel PNG via ezdxf si disponible.
        """
        result = ExtractionResult(format="dwg", has_images=True)
        result.metadata.update(
            self._meta_extractor.extract_from_filename(Path(file_path).name)
        )

        try:
            # Import lazy pour éviter la dépendance circulaire au niveau module
            from pid_analyzer import parse_dwg_file
            import json as _json

            logger.info("_process_dwg: appel de parse_dwg_file pour %s", file_path)
            pid_data = parse_dwg_file(
                dwg_path=file_path,
                output_image_dir=str(Path(file_path).parent / "generated_visuals"),
                discipline="pid"
            )

            # Récupérer le rendu visuel si disponible
            if pid_data.get("image_url"):
                result.metadata["image_url"] = pid_data["image_url"]
                result.metadata["has_visual"] = True
            else:
                result.metadata["has_visual"] = False

            # Compter les éléments extraits
            n_elements = len(pid_data.get("elements", []))
            n_equipment = len(pid_data.get("equipment", []))
            n_instruments = len(pid_data.get("instruments", []))
            n_valves = len(pid_data.get("valves", []))

            # Sérialiser les données P&ID pour l'API
            result.text = _json.dumps({
                "source": "dwg_pid_analyzer",
                "file": Path(file_path).name,
                "elements": pid_data.get("elements", []),
                "equipment": pid_data.get("equipment", []),
                "instruments": pid_data.get("instruments", []),
                "valves": pid_data.get("valves", []),
                "lines": pid_data.get("lines", []),
                "safety": pid_data.get("safety", []),
                "cross_references": pid_data.get("cross_references", []),
                "document": pid_data.get("document", {}),
                "general_notes": pid_data.get("general_notes", []),
                "holds": pid_data.get("holds", []),
                "image_url": pid_data.get("image_url"),
            }, ensure_ascii=False, indent=2)

            result.extraction_quality = 0.75 if n_elements > 0 else 0.20
            result.page_count = 1
            result.metadata["element_count"] = n_elements
            result.metadata["equipment_count"] = n_equipment
            result.metadata["instrument_count"] = n_instruments
            result.metadata["valve_count"] = n_valves

            if n_elements == 0:
                result.warnings.append(
                    "Aucun tag P&ID extrait du fichier DWG. "
                    "Vérifier que le fichier contient du texte lisible."
                )
            else:
                logger.info(
                    "_process_dwg: %d éléments extraits (%d équipements, %d instruments, %d vannes)",
                    n_elements, n_equipment, n_instruments, n_valves
                )

        except ImportError as ie:
            logger.error("pid_analyzer non disponible: %s", ie)
            result.text = (
                f"[DWG file: {Path(file_path).name}]\n"
                "Erreur: pid_analyzer non trouvé. Vérifier l'installation."
            )
            result.extraction_quality = 0.05
            result.error = str(ie)
        except Exception as exc:
            logger.error("DWG extraction failed for %s: %s", file_path, exc, exc_info=True)
            result.text = (
                f"[DWG file: {Path(file_path).name}]\n"
                f"Erreur lors de l'extraction: {exc}"
            )
            result.extraction_quality = 0.05
            result.error = str(exc)

        return result

    # ----------------------------------------------------------
    #  _process_text
    # ----------------------------------------------------------

    def _process_text(self, file_path: str) -> ExtractionResult:
        """Plain text with encoding detection and large-file streaming."""
        result = ExtractionResult(format="text")
        try:
            file_size = os.path.getsize(file_path)
            encoding = self._enc_detector.detect(file_path)

            if file_size > _MAX_TEXT_BYTES:
                result.warnings.append(
                    f"File is large ({file_size / 1024 / 1024:.1f} MB); "
                    f"reading first {_MAX_TEXT_BYTES // 1024 // 1024} MB only"
                )

            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                text = fh.read(_MAX_TEXT_BYTES)

            result.text = text
            result.page_count = 1
            result.extraction_quality = 0.90
            result.metadata["encoding"] = encoding
        except Exception as exc:
            logger.error("Text extraction failed for %s: %s", file_path, exc)
            result.error = str(exc)
        return result

    # ----------------------------------------------------------
    #  Handler mapping (must be defined AFTER the methods)
    # ----------------------------------------------------------

    _HANDLERS: Dict[str, Any] = {
        "pdf": _process_pdf,
        "docx": _process_docx,
        "xlsx": _process_xlsx,
        "csv": _process_csv,
        "pptx": _process_pptx,
        "xml": _process_xml,
        "json": _process_json,
        "yaml": _process_yaml,
        "html": _process_html,
        "image": _process_image,
        "dxf": _process_dxf,
        "dwg": _process_dwg,
        "text": _process_text,
    }


# ============================================================
#  Convenience wrapper (backward compat with extractors.py)
# ============================================================

_default_processor: Optional[FileProcessor] = None


def get_processor() -> FileProcessor:
    """Return a module-level singleton processor."""
    global _default_processor
    if _default_processor is None:
        _default_processor = FileProcessor()
    return _default_processor


def extract_file(file_path: str) -> dict:
    """Drop-in replacement for the legacy ``extractors.extract_file``."""
    result = get_processor().process(file_path)
    return result.to_dict()
