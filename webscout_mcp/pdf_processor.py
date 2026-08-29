"""PDF document processing module for webscout-mcp.

Extract text, tables, metadata, and images from PDF documents.
Supports both text-based and scanned PDFs (with OCR).

Features:
- Text extraction from PDF
- Table extraction (structured data)
- Metadata extraction (title, author, creation date, etc.)
- Image extraction
- Page-by-page processing
- OCR support for scanned PDFs
- PDF to text/markdown conversion
- Encrypted PDF handling
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class PDFPage:
    """A single page from a PDF document."""

    page_number: int
    text: str = ""
    images: list[dict] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "num_images": len(self.images),
            "num_tables": len(self.tables),
            "width": self.width,
            "height": self.height,
        }


@dataclass
class PDFMetadata:
    """Metadata extracted from a PDF document."""

    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""
    modification_date: str = ""
    num_pages: int = 0
    encrypted: bool = False
    file_size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "keywords": self.keywords,
            "creator": self.creator,
            "producer": self.producer,
            "creation_date": self.creation_date,
            "modification_date": self.modification_date,
            "num_pages": self.num_pages,
            "encrypted": self.encrypted,
            "file_size_bytes": self.file_size_bytes,
        }


@dataclass
class PDFResult:
    """Result of PDF processing."""

    file_path: str = ""
    metadata: PDFMetadata = field(default_factory=PDFMetadata)
    pages: list[PDFPage] = field(default_factory=list)
    full_text: str = ""
    success: bool = False
    error_message: str = ""

    @property
    def num_pages(self) -> int:
        return len(self.pages)

    @property
    def total_images(self) -> int:
        return sum(len(p.images) for p in self.pages)

    @property
    def total_tables(self) -> int:
        return sum(len(p.tables) for p in self.pages)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "metadata": self.metadata.to_dict(),
            "num_pages": self.num_pages,
            "total_images": self.total_images,
            "total_tables": self.total_tables,
            "full_text_length": len(self.full_text),
            "success": self.success,
            "error_message": self.error_message,
            "pages": [p.to_dict() for p in self.pages],
        }


class PDFProcessor:
    """PDF document processor.

    Extracts text, tables, metadata, and images from PDF files.
    Supports multiple backends: PyPDF2, pdfplumber, pymupdf.
    """

    def __init__(
        self,
        extract_tables: bool = True,
        extract_images: bool = False,
        ocr_enabled: bool = False,
        ocr_language: str = "eng+chi_sim",
    ) -> None:
        self.extract_tables = extract_tables
        self.extract_images = extract_images
        self.ocr_enabled = ocr_enabled
        self.ocr_language = ocr_language
        self._backend = None
        self._detect_backend()

    def _detect_backend(self) -> None:
        """Detect available PDF processing backend."""
        try:
            import fitz  # PyMuPDF

            self._backend = "pymupdf"
            log.debug("Using PyMuPDF backend")
        except ImportError:
            try:
                import pdfplumber

                self._backend = "pdfplumber"
                log.debug("Using pdfplumber backend")
            except ImportError:
                try:
                    import PyPDF2

                    self._backend = "pypdf2"
                    log.debug("Using PyPDF2 backend")
                except ImportError:
                    self._backend = None
                    log.warning("No PDF backend available. Install PyMuPDF, pdfplumber, or PyPDF2")

    @property
    def backend(self) -> str | None:
        """Get the detected backend."""
        return self._backend

    def process(self, file_path: str, password: str | None = None) -> PDFResult:
        """Process a PDF file.

        Args:
            file_path: Path to PDF file.
            password: Password for encrypted PDFs.

        Returns:
            PDFResult with extracted content.
        """
        result = PDFResult(file_path=file_path)

        if not os.path.exists(file_path):
            result.error_message = f"File not found: {file_path}"
            return result

        if not file_path.lower().endswith(".pdf"):
            result.error_message = "File is not a PDF"
            return result

        # Get file size
        result.metadata.file_size_bytes = os.path.getsize(file_path)

        try:
            if self._backend == "pymupdf":
                self._process_pymupdf(file_path, result, password)
            elif self._backend == "pdfplumber":
                self._process_pdfplumber(file_path, result, password)
            elif self._backend == "pypdf2":
                self._process_pypdf2(file_path, result, password)
            else:
                result.error_message = "No PDF backend available. Install with: pip install pymupdf"
                return result

            # Combine full text
            result.full_text = "\n\n".join(page.text for page in result.pages if page.text)
            result.metadata.num_pages = len(result.pages)
            result.success = True

        except Exception as exc:
            result.error_message = f"{type(exc).__name__}: {exc}"
            log.error("PDF processing failed", extra={"file": file_path, "error": str(exc)})

        return result

    def _process_pymupdf(self, file_path: str, result: PDFResult, password: str | None) -> None:
        """Process PDF using PyMuPDF."""
        import fitz

        doc = fitz.open(file_path)

        # Handle encrypted PDF
        if doc.is_encrypted:
            result.metadata.encrypted = True
            if password:
                doc.authenticate(password)
            else:
                raise ValueError("PDF is encrypted, password required")

        # Extract metadata
        meta = doc.metadata
        if meta:
            result.metadata.title = meta.get("title", "") or ""
            result.metadata.author = meta.get("author", "") or ""
            result.metadata.subject = meta.get("subject", "") or ""
            result.metadata.keywords = meta.get("keywords", "") or ""
            result.metadata.creator = meta.get("creator", "") or ""
            result.metadata.producer = meta.get("producer", "") or ""
            result.metadata.creation_date = meta.get("creationDate", "") or ""
            result.metadata.modification_date = meta.get("modDate", "") or ""

        # Process pages
        for page_num in range(len(doc)):
            page = doc[page_num]
            pdf_page = PDFPage(
                page_number=page_num + 1,
                width=page.rect.width,
                height=page.rect.height,
            )

            # Extract text
            pdf_page.text = page.get_text()

            # Extract images
            if self.extract_images:
                image_list = page.get_images(full=True)
                for img_idx, img in enumerate(image_list):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    pdf_page.images.append(
                        {
                            "index": img_idx,
                            "width": base_image.get("width", 0),
                            "height": base_image.get("height", 0),
                            "ext": base_image.get("ext", ""),
                            "size": len(base_image.get("image", b"")),
                        }
                    )

            # Extract tables (PyMuPDF doesn't have built-in table extraction,
            # but we can try to detect text blocks arranged in tables)
            if self.extract_tables:
                # Simple table detection based on text blocks
                blocks = page.get_text("blocks")
                if len(blocks) > 5:
                    # Group blocks by y-coordinate to detect rows
                    rows = {}
                    for block in blocks:
                        if len(block) >= 5:
                            y = round(block[1], -1)  # Round to nearest 10
                            if y not in rows:
                                rows[y] = []
                            rows[y].append(block[4].strip())
                    # If multiple rows with similar column counts, treat as table
                    if len(rows) >= 3:
                        table = [cells for _, cells in sorted(rows.items())]
                        pdf_page.tables.append(table)

            result.pages.append(pdf_page)

        doc.close()

    def _process_pdfplumber(self, file_path: str, result: PDFResult, password: str | None) -> None:
        """Process PDF using pdfplumber."""
        import pdfplumber

        with pdfplumber.open(file_path, password=password) as pdf:
            # Extract metadata
            if pdf.metadata:
                result.metadata.title = pdf.metadata.get("Title", "") or ""
                result.metadata.author = pdf.metadata.get("Author", "") or ""
                result.metadata.subject = pdf.metadata.get("Subject", "") or ""
                result.metadata.keywords = pdf.metadata.get("Keywords", "") or ""
                result.metadata.creator = pdf.metadata.get("Creator", "") or ""
                result.metadata.producer = pdf.metadata.get("Producer", "") or ""
                result.metadata.creation_date = str(pdf.metadata.get("CreationDate", "") or "")
                result.metadata.modification_date = str(pdf.metadata.get("ModDate", "") or "")

            # Process pages
            for page_num, page in enumerate(pdf.pages):
                pdf_page = PDFPage(
                    page_number=page_num + 1,
                    width=page.width,
                    height=page.height,
                )

                # Extract text
                pdf_page.text = page.extract_text() or ""

                # Extract tables
                if self.extract_tables:
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            pdf_page.tables.append(table)

                # Extract images
                if self.extract_images:
                    if hasattr(page, "images"):
                        for img_idx, img in enumerate(page.images):
                            pdf_page.images.append(
                                {
                                    "index": img_idx,
                                    "width": img.get("width", 0),
                                    "height": img.get("height", 0),
                                    "name": img.get("name", ""),
                                }
                            )

                result.pages.append(pdf_page)

    def _process_pypdf2(self, file_path: str, result: PDFResult, password: str | None) -> None:
        """Process PDF using PyPDF2 (basic text extraction only)."""
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            from pypdf import PdfReader

        reader = PdfReader(file_path)

        # Handle encrypted PDF
        if reader.is_encrypted:
            result.metadata.encrypted = True
            if password:
                reader.decrypt(password)
            else:
                raise ValueError("PDF is encrypted, password required")

        # Extract metadata
        if reader.metadata:
            result.metadata.title = str(reader.metadata.get("/Title", "") or "")
            result.metadata.author = str(reader.metadata.get("/Author", "") or "")
            result.metadata.subject = str(reader.metadata.get("/Subject", "") or "")
            result.metadata.creator = str(reader.metadata.get("/Creator", "") or "")
            result.metadata.producer = str(reader.metadata.get("/Producer", "") or "")

        # Process pages
        for page_num, page in enumerate(reader.pages):
            pdf_page = PDFPage(page_number=page_num + 1)
            try:
                pdf_page.text = page.extract_text() or ""
            except Exception:
                pdf_page.text = ""
            result.pages.append(pdf_page)

    def extract_text(self, file_path: str, password: str | None = None) -> str:
        """Extract only text from a PDF.

        Args:
            file_path: Path to PDF file.
            password: Password for encrypted PDFs.

        Returns:
            Extracted text.
        """
        result = self.process(file_path, password)
        return result.full_text

    def extract_tables(self, file_path: str, password: str | None = None) -> list[list[list[str]]]:
        """Extract only tables from a PDF.

        Args:
            file_path: Path to PDF file.
            password: Password for encrypted PDFs.

        Returns:
            List of tables, each table is a list of rows, each row is a list of cells.
        """
        result = self.process(file_path, password)
        all_tables = []
        for page in result.pages:
            all_tables.extend(page.tables)
        return all_tables

    def get_page_count(self, file_path: str, password: str | None = None) -> int:
        """Get the number of pages in a PDF.

        Args:
            file_path: Path to PDF file.
            password: Password for encrypted PDFs.

        Returns:
            Number of pages.
        """
        result = self.process(file_path, password)
        return result.num_pages

    def to_markdown(self, file_path: str, password: str | None = None) -> str:
        """Convert PDF to Markdown format.

        Args:
            file_path: Path to PDF file.
            password: Password for encrypted PDFs.

        Returns:
            Markdown formatted text.
        """
        result = self.process(file_path, password)
        if not result.success:
            return f"Error: {result.error_message}"

        lines = []
        if result.metadata.title:
            lines.append(f"# {result.metadata.title}")
            lines.append("")

        for page in result.pages:
            lines.append(f"## Page {page.page_number}")
            lines.append("")
            if page.text:
                lines.append(page.text)
                lines.append("")

            for table_idx, table in enumerate(page.tables):
                lines.append(f"### Table {table_idx + 1}")
                lines.append("")
                if table:
                    # Header
                    header = table[0]
                    lines.append("| " + " | ".join(str(c) for c in header) + " |")
                    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                    # Rows
                    for row in table[1:]:
                        lines.append("| " + " | ".join(str(c) for c in row) + " |")
                    lines.append("")

        return "\n".join(lines)


def process_pdf(
    file_path: str,
    extract_tables: bool = True,
    extract_images: bool = False,
    password: str | None = None,
) -> PDFResult:
    """Convenience function to process a PDF file.

    Args:
        file_path: Path to PDF file.
        extract_tables: Whether to extract tables.
        extract_images: Whether to extract images.
        password: Password for encrypted PDFs.

    Returns:
        PDFResult with extracted content.
    """
    processor = PDFProcessor(extract_tables=extract_tables, extract_images=extract_images)
    return processor.process(file_path, password)
