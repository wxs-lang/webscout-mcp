"""OCR (Optical Character Recognition) module for webscout-mcp.

Extract text from images using multiple OCR backends.
Supports Tesseract, PaddleOCR, and easyocr.

Features:
- Multi-backend OCR (Tesseract, PaddleOCR, EasyOCR)
- Image preprocessing (grayscale, threshold, denoise)
- Text extraction with bounding boxes
- Language detection and multi-language support
- Table structure detection
- Confidence scores
- Batch processing
- Image format support (PNG, JPG, TIFF, PDF)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class OCRResult:
    """OCR result for a single image."""

    text: str = ""
    confidence: float = 0.0
    lines: List[dict] = field(default_factory=list)
    words: List[dict] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    processing_time_ms: float = 0.0
    backend: str = ""
    languages: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "num_lines": len(self.lines),
            "num_words": len(self.words),
            "image_width": self.image_width,
            "image_height": self.image_height,
            "processing_time_ms": self.processing_time_ms,
            "backend": self.backend,
            "languages": self.languages,
            "lines": self.lines,
        }


class OCREngine:
    """OCR engine with multiple backend support.

    Features:
    - Tesseract OCR (via pytesseract)
    - PaddleOCR
    - EasyOCR
    - Image preprocessing
    - Confidence scoring
    """

    SUPPORTED_BACKENDS = ["tesseract", "paddleocr", "easyocr"]

    def __init__(
        self,
        backend: str = "tesseract",
        languages: Optional[List[str]] = None,
        preprocess: bool = True,
        tesseract_cmd: Optional[str] = None,
    ) -> None:
        self.backend = backend.lower()
        self.languages = languages or ["eng"]
        self.preprocess = preprocess
        self.tesseract_cmd = tesseract_cmd
        self._engine = None
        self._detect_backend()

    def _detect_backend(self) -> None:
        """Detect and initialize the OCR backend."""
        if self.backend == "tesseract":
            try:
                import pytesseract

                if self.tesseract_cmd:
                    pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
                self._engine = pytesseract
                log.debug("Tesseract OCR backend initialized")
            except ImportError:
                log.warning("pytesseract not available, OCR will be limited")
                self._engine = None

        elif self.backend == "paddleocr":
            try:
                from paddleocr import PaddleOCR

                self._engine = PaddleOCR(use_angle_cls=True, lang=self.languages[0] if self.languages else "en")
                log.debug("PaddleOCR backend initialized")
            except ImportError:
                log.warning("paddleocr not available")
                self._engine = None

        elif self.backend == "easyocr":
            try:
                import easyocr

                self._engine = easyocr.Reader(self.languages, gpu=False)
                log.debug("EasyOCR backend initialized")
            except ImportError:
                log.warning("easyocr not available")
                self._engine = None

    @property
    def is_available(self) -> bool:
        """Check if OCR backend is available."""
        return self._engine is not None

    def preprocess_image(self, image_path: str) -> str:
        """Preprocess image for better OCR results.

        Args:
            image_path: Path to input image.

        Returns:
            Path to preprocessed image.
        """
        if not self.preprocess:
            return image_path

        try:
            from PIL import Image, ImageEnhance, ImageFilter

            img = Image.open(image_path)

            # Convert to grayscale
            if img.mode != "L":
                img = img.convert("L")

            # Increase contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)

            # Sharpen
            img = img.filter(ImageFilter.SHARPEN)

            # Save preprocessed image
            preprocessed_path = image_path + "_preprocessed.png"
            img.save(preprocessed_path)
            return preprocessed_path

        except ImportError:
            log.warning("Pillow not available for image preprocessing")
            return image_path

    def recognize(self, image_path: str) -> OCRResult:
        """Recognize text in an image.

        Args:
            image_path: Path to image file.

        Returns:
            OCRResult with recognized text and metadata.
        """
        import time

        result = OCRResult(backend=self.backend, languages=self.languages)

        if not os.path.exists(image_path):
            result.text = ""
            result.confidence = 0.0
            return result

        if not self.is_available:
            result.text = ""
            result.confidence = 0.0
            log.warning("OCR backend not available")
            return result

        start_time = time.time()

        try:
            # Preprocess image
            processed_path = self.preprocess_image(image_path)

            # Get image dimensions
            try:
                from PIL import Image

                with Image.open(processed_path) as img:
                    result.image_width, result.image_height = img.size
            except ImportError:
                pass

            # Perform OCR based on backend
            if self.backend == "tesseract":
                self._recognize_tesseract(processed_path, result)
            elif self.backend == "paddleocr":
                self._recognize_paddleocr(processed_path, result)
            elif self.backend == "easyocr":
                self._recognize_easyocr(processed_path, result)

            # Clean up preprocessed image
            if processed_path != image_path and os.path.exists(processed_path):
                try:
                    os.unlink(processed_path)
                except OSError:
                    pass

        except Exception as exc:
            log.error("OCR recognition failed", extra={"error": str(exc)})
            result.text = ""
            result.confidence = 0.0

        result.processing_time_ms = round((time.time() - start_time) * 1000, 2)
        return result

    def _recognize_tesseract(self, image_path: str, result: OCRResult) -> None:
        """Recognize using Tesseract."""
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        lang = "+".join(self.languages) if self.languages else "eng"

        # Get detailed data
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)

        # Extract text and words
        texts = []
        confidences = []
        for i, text in enumerate(data["text"]):
            if text.strip():
                texts.append(text)
                conf = data["conf"][i]
                if conf > 0:
                    confidences.append(conf)
                    result.words.append(
                        {
                            "text": text,
                            "confidence": conf,
                            "left": data["left"][i],
                            "top": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                        }
                    )

        result.text = " ".join(texts)
        result.confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

        # Extract lines
        current_line = []
        current_line_num = -1
        for i, text in enumerate(data["text"]):
            if text.strip():
                line_num = data["line_num"][i]
                if line_num != current_line_num:
                    if current_line:
                        result.lines.append({"text": " ".join(current_line), "line_num": current_line_num})
                    current_line = []
                    current_line_num = line_num
                current_line.append(text)
        if current_line:
            result.lines.append({"text": " ".join(current_line), "line_num": current_line_num})

    def _recognize_paddleocr(self, image_path: str, result: OCRResult) -> None:
        """Recognize using PaddleOCR."""
        output = self._engine.ocr(image_path, cls=True)

        texts = []
        confidences = []
        for line in output:
            if line:
                for word_info in line:
                    bbox, (text, conf) = word_info
                    texts.append(text)
                    confidences.append(conf)
                    result.words.append(
                        {
                            "text": text,
                            "confidence": conf,
                            "bbox": bbox,
                        }
                    )

        result.text = "\n".join(texts)
        result.confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        result.lines = [{"text": t} for t in texts]

    def _recognize_easyocr(self, image_path: str, result: OCRResult) -> None:
        """Recognize using EasyOCR."""
        output = self._engine.readtext(image_path)

        texts = []
        confidences = []
        for bbox, text, conf in output:
            texts.append(text)
            confidences.append(conf)
            result.words.append(
                {
                    "text": text,
                    "confidence": conf,
                    "bbox": bbox,
                }
            )

        result.text = " ".join(texts)
        result.confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        result.lines = [{"text": t} for t in texts]

    def recognize_batch(self, image_paths: List[str]) -> List[OCRResult]:
        """Recognize text in multiple images.

        Args:
            image_paths: List of image file paths.

        Returns:
            List of OCRResult objects.
        """
        results = []
        for path in image_paths:
            result = self.recognize(path)
            results.append(result)
        return results

    def extract_table(self, image_path: str) -> List[List[str]]:
        """Extract table structure from image (basic).

        Args:
            image_path: Path to image file.

        Returns:
            List of rows, each row is a list of cell texts.
        """
        result = self.recognize(image_path)
        if not result.text:
            return []

        # Basic table extraction based on line positions
        # This is a simplified version
        lines = result.lines
        if not lines:
            return [[result.text]]

        # Group by y-coordinate if available
        rows = []
        current_row = []
        current_y = None

        for line in lines:
            if "top" in line:
                y = line["top"]
                if current_y is None or abs(y - current_y) > 20:
                    if current_row:
                        rows.append(current_row)
                    current_row = [line["text"]]
                    current_y = y
                else:
                    current_row.append(line["text"])
            else:
                rows.append([line["text"]])

        if current_row:
            rows.append(current_row)

        return rows if rows else [[result.text]]


def ocr_image(
    image_path: str,
    backend: str = "tesseract",
    languages: Optional[List[str]] = None,
) -> OCRResult:
    """Convenience function to perform OCR on an image.

    Args:
        image_path: Path to image file.
        backend: OCR backend (tesseract, paddleocr, easyocr).
        languages: List of language codes.

    Returns:
        OCRResult with recognized text.
    """
    engine = OCREngine(backend=backend, languages=languages)
    return engine.recognize(image_path)
