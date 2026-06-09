from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
import pytesseract

from .pdfbox import ExtractOptions, PDFBoxError, extract_text_with_pdfbox
from .settings import settings


@dataclass(frozen=True)
class TextExtractionResult:
    text: str
    method: str
    attempted_methods: list[str]
    warnings: list[str]


def extract_text_from_pdf(pdf_path: Path, options: ExtractOptions) -> TextExtractionResult:
    attempted_methods: list[str] = []
    warnings: list[str] = []

    if not options.force_ocr:
        attempted_methods.append("pdfbox")
        try:
            text = extract_text_with_pdfbox(
                pdf_path=pdf_path,
                pdfbox_jar=settings.pdfbox_jar,
                java_bin=settings.java_bin,
                timeout_seconds=settings.pdfbox_timeout_seconds,
                options=options,
            )
            if _has_enough_text(text):
                return TextExtractionResult(text=text, method="pdfbox", attempted_methods=attempted_methods, warnings=warnings)
            warnings.append("PDFBox retornou pouco texto; tentando pdfplumber/OCR.")
        except PDFBoxError as exc:
            warnings.append(f"PDFBox falhou: {exc}")

        attempted_methods.append("pdfplumber")
        try:
            text = extract_text_with_pdfplumber(pdf_path, options)
            if _has_enough_text(text):
                return TextExtractionResult(
                    text=text,
                    method="pdfplumber",
                    attempted_methods=attempted_methods,
                    warnings=warnings,
                )
            warnings.append("pdfplumber retornou pouco texto; tentando OCR.")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdfplumber falhou: {exc}")

    if not settings.ocr_enabled or not options.enable_ocr:
        raise PDFBoxError("Nao foi possivel extrair texto suficiente e OCR esta desabilitado.")

    attempted_methods.append("ocr_tesseract")
    try:
        text = extract_text_with_ocr(pdf_path, options)
    except Exception as exc:  # noqa: BLE001
        raise PDFBoxError(f"OCR falhou: {exc}") from exc

    if not text.strip():
        raise PDFBoxError("OCR executado, mas nenhum texto foi encontrado.")

    return TextExtractionResult(text=text, method="ocr_tesseract", attempted_methods=attempted_methods, warnings=warnings)


def extract_text_with_pdfplumber(pdf_path: Path, options: ExtractOptions) -> str:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index in _selected_page_indexes(len(pdf.pages), options, settings.ocr_max_pages):
            text = pdf.pages[page_index].extract_text(x_tolerance=1, y_tolerance=3) or ""
            if text.strip():
                page_texts.append(f"--- Page {page_index + 1} ---\n{text.strip()}")
    return "\n\n".join(page_texts)


def extract_text_with_ocr(pdf_path: Path, options: ExtractOptions) -> str:
    pdf = pdfium.PdfDocument(str(pdf_path))
    page_texts: list[str] = []
    scale = settings.ocr_dpi / 72

    for page_index in _selected_page_indexes(len(pdf), options, settings.ocr_max_pages):
        page = pdf[page_index]
        image = page.render(scale=scale).to_pil()
        text = pytesseract.image_to_string(image, lang=settings.ocr_language)
        if text.strip():
            page_texts.append(f"--- Page {page_index + 1} OCR ---\n{text.strip()}")

    return "\n\n".join(page_texts)


def _selected_page_indexes(total_pages: int, options: ExtractOptions, max_pages: int) -> range:
    start = max((options.start_page or 1) - 1, 0)
    end = min(options.end_page or total_pages, total_pages)
    if max_pages > 0:
        end = min(end, start + max_pages)
    return range(start, end)


def _has_enough_text(text: str) -> bool:
    compact = "".join(text.split())
    return len(compact) >= settings.min_text_chars_for_ocr
