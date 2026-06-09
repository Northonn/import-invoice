from dataclasses import dataclass
import logging
from pathlib import Path
from time import perf_counter

import pdfplumber
import pypdfium2 as pdfium
import pytesseract

from .pdfbox import ExtractOptions, PDFBoxError, extract_text_with_pdfbox
from .settings import settings


logger = logging.getLogger("pdf_invoice_api.text_extractor")


@dataclass(frozen=True)
class TextExtractionResult:
    text: str
    method: str
    attempted_methods: list[str]
    warnings: list[str]


def extract_text_from_pdf(pdf_path: Path, options: ExtractOptions, request_id: str) -> TextExtractionResult:
    logger.info(
        "request_id=%s stage=extract_start force_ocr=%s enable_ocr=%s start_page=%s end_page=%s ocr_dpi=%s ocr_max_pages=%s ocr_page_timeout_seconds=%s",
        request_id,
        options.force_ocr,
        options.enable_ocr,
        options.start_page,
        options.end_page,
        settings.ocr_dpi,
        settings.ocr_max_pages,
        settings.ocr_page_timeout_seconds,
    )
    attempted_methods: list[str] = []
    warnings: list[str] = []

    if not options.force_ocr:
        attempted_methods.append("pdfbox")
        try:
            started_at = perf_counter()
            logger.info("request_id=%s stage=pdfbox_start", request_id)
            text = extract_text_with_pdfbox(
                pdf_path=pdf_path,
                pdfbox_jar=settings.pdfbox_jar,
                java_bin=settings.java_bin,
                timeout_seconds=settings.pdfbox_timeout_seconds,
                options=options,
            )
            logger.info(
                "request_id=%s stage=pdfbox_done elapsed_ms=%s text_chars=%s",
                request_id,
                _elapsed_ms(started_at),
                len(text),
            )
            if _has_enough_text(text):
                logger.info("request_id=%s stage=extract_done method=pdfbox", request_id)
                return TextExtractionResult(text=text, method="pdfbox", attempted_methods=attempted_methods, warnings=warnings)
            warnings.append("PDFBox retornou pouco texto; tentando pdfplumber/OCR.")
        except PDFBoxError as exc:
            logger.exception("request_id=%s stage=pdfbox_error error=%s", request_id, exc)
            warnings.append(f"PDFBox falhou: {exc}")

        attempted_methods.append("pdfplumber")
        try:
            started_at = perf_counter()
            logger.info("request_id=%s stage=pdfplumber_start", request_id)
            text = extract_text_with_pdfplumber(pdf_path, options, request_id)
            logger.info(
                "request_id=%s stage=pdfplumber_done elapsed_ms=%s text_chars=%s",
                request_id,
                _elapsed_ms(started_at),
                len(text),
            )
            if _has_enough_text(text):
                logger.info("request_id=%s stage=extract_done method=pdfplumber", request_id)
                return TextExtractionResult(
                    text=text,
                    method="pdfplumber",
                    attempted_methods=attempted_methods,
                    warnings=warnings,
                )
            warnings.append("pdfplumber retornou pouco texto; tentando OCR.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("request_id=%s stage=pdfplumber_error error=%s", request_id, exc)
            warnings.append(f"pdfplumber falhou: {exc}")

    if not settings.ocr_enabled or not options.enable_ocr:
        raise PDFBoxError("Nao foi possivel extrair texto suficiente e OCR esta desabilitado.")

    attempted_methods.append("ocr_tesseract")
    try:
        started_at = perf_counter()
        logger.info("request_id=%s stage=ocr_start", request_id)
        text = extract_text_with_ocr(pdf_path, options, request_id)
        logger.info(
            "request_id=%s stage=ocr_done elapsed_ms=%s text_chars=%s",
            request_id,
            _elapsed_ms(started_at),
            len(text),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("request_id=%s stage=ocr_error error=%s", request_id, exc)
        raise PDFBoxError(f"OCR falhou: {exc}") from exc

    if not text.strip():
        raise PDFBoxError("OCR executado, mas nenhum texto foi encontrado.")

    logger.info("request_id=%s stage=extract_done method=ocr_tesseract", request_id)
    return TextExtractionResult(text=text, method="ocr_tesseract", attempted_methods=attempted_methods, warnings=warnings)


def extract_text_with_pdfplumber(pdf_path: Path, options: ExtractOptions, request_id: str) -> str:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        selected_pages = list(_selected_page_indexes(len(pdf.pages), options, settings.ocr_max_pages))
        logger.info("request_id=%s stage=pdfplumber_pages total_pages=%s selected_pages=%s", request_id, len(pdf.pages), [i + 1 for i in selected_pages])
        for page_index in selected_pages:
            started_at = perf_counter()
            text = pdf.pages[page_index].extract_text(x_tolerance=1, y_tolerance=3) or ""
            logger.info(
                "request_id=%s stage=pdfplumber_page_done page=%s elapsed_ms=%s text_chars=%s",
                request_id,
                page_index + 1,
                _elapsed_ms(started_at),
                len(text),
            )
            if text.strip():
                page_texts.append(f"--- Page {page_index + 1} ---\n{text.strip()}")
    return "\n\n".join(page_texts)


def extract_text_with_ocr(pdf_path: Path, options: ExtractOptions, request_id: str) -> str:
    pdf = pdfium.PdfDocument(str(pdf_path))
    page_texts: list[str] = []
    scale = settings.ocr_dpi / 72

    selected_pages = list(_selected_page_indexes(len(pdf), options, settings.ocr_max_pages))
    logger.info("request_id=%s stage=ocr_pages total_pages=%s selected_pages=%s", request_id, len(pdf), [i + 1 for i in selected_pages])
    for page_index in selected_pages:
        page_started_at = perf_counter()
        logger.info("request_id=%s stage=ocr_page_render_start page=%s", request_id, page_index + 1)
        page = pdf[page_index]
        image = page.render(scale=scale).to_pil()
        logger.info(
            "request_id=%s stage=ocr_page_render_done page=%s elapsed_ms=%s image_size=%sx%s",
            request_id,
            page_index + 1,
            _elapsed_ms(page_started_at),
            image.width,
            image.height,
        )
        ocr_started_at = perf_counter()
        logger.info("request_id=%s stage=ocr_page_tesseract_start page=%s", request_id, page_index + 1)
        try:
            text = pytesseract.image_to_string(
                image,
                lang=settings.ocr_language,
                timeout=settings.ocr_page_timeout_seconds,
            )
        except RuntimeError as exc:
            logger.exception(
                "request_id=%s stage=ocr_page_tesseract_timeout page=%s timeout_seconds=%s",
                request_id,
                page_index + 1,
                settings.ocr_page_timeout_seconds,
            )
            raise PDFBoxError(
                f"OCR excedeu o timeout de {settings.ocr_page_timeout_seconds}s na pagina {page_index + 1}."
            ) from exc
        logger.info(
            "request_id=%s stage=ocr_page_tesseract_done page=%s elapsed_ms=%s text_chars=%s",
            request_id,
            page_index + 1,
            _elapsed_ms(ocr_started_at),
            len(text),
        )
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


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)
