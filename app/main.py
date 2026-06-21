from pathlib import Path
from typing import Any
import logging
import sys
import tempfile
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile

from .invoice_parser import InvoiceParseError, parse_invoice_pdf_file, parse_invoice_text
from .pdfbox import ExtractOptions, PDFBoxError
from .settings import settings
from .text_extractor import TextExtractionResult, extract_text_from_pdf


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("pdf_invoice_api.main")

ALLOWED_OPENAI_MODELS = {
    "gpt-4.1-mini",
    "gpt-4.1-mini-2025-04-14",
    "gpt-5-mini",
    "gpt-5-mini-2025-08-07",
    "gpt-4o-mini",
    "gpt-4o-mini-2024-07-18",
}

app = FastAPI(
    title="PDF Invoice API",
    version=settings.api_version,
    description="Extrai texto de invoices em PDF usando Apache PDFBox.",
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="API key invalida ou ausente.")


def build_options(
    start_page: int | None = Query(default=None, ge=1),
    end_page: int | None = Query(default=None, ge=1),
    password: str | None = Query(default=None),
    sort: bool = Query(default=True),
    rotation_magic: bool = Query(default=False),
    enable_ocr: bool = Query(default=True),
    force_ocr: bool = Query(default=False),
) -> ExtractOptions:
    if start_page and end_page and end_page < start_page:
        raise HTTPException(status_code=422, detail="end_page deve ser maior ou igual a start_page.")
    return ExtractOptions(
        start_page=start_page,
        end_page=end_page,
        password=password,
        sort=sort,
        rotation_magic=rotation_magic,
        enable_ocr=enable_ocr,
        force_ocr=force_ocr,
    )


def build_context(
    id_tenant: int | None = Query(default=None),
    id_usuario_incluiu: int | None = Query(default=None),
    id_processoimportacao: int | None = Query(default=None),
    include_extracted_text: bool = Query(default=False),
) -> dict[str, int | bool | None]:
    return {
        "id_tenant": id_tenant,
        "id_usuario_incluiu": id_usuario_incluiu,
        "id_processoimportacao": id_processoimportacao,
        "include_extracted_text": include_extracted_text,
    }


def build_openai_model(openai_model: str | None = Query(default=None)) -> str | None:
    if openai_model is None:
        return None
    normalized_model = openai_model.strip()
    if normalized_model not in ALLOWED_OPENAI_MODELS:
        allowed = ", ".join(sorted(ALLOWED_OPENAI_MODELS))
        raise HTTPException(status_code=422, detail=f"openai_model invalido. Modelos permitidos: {allowed}.")
    return normalized_model


def extract_from_temp_pdf(pdf_path: Path, options: ExtractOptions, request_id: str) -> TextExtractionResult:
    try:
        return extract_text_from_pdf(pdf_path, options, request_id)
    except PDFBoxError as exc:
        logger.exception("request_id=%s stage=extract_error error=%s", request_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def extract_auxiliary_text_for_pdf_parse(
    pdf_path: Path,
    request_id: str,
    *,
    enable_ocr: bool,
) -> TextExtractionResult | None:
    options = ExtractOptions(enable_ocr=enable_ocr)
    try:
        return extract_text_from_pdf(pdf_path, options, request_id)
    except PDFBoxError as exc:
        logger.warning("request_id=%s stage=auxiliary_text_unavailable error=%s", request_id, exc)
        return None


async def write_request_stream_to_file(request: Request, destination: Path, request_id: str) -> int:
    total = 0
    logger.info("request_id=%s stage=raw_upload_start", request_id)
    started_at = perf_counter()
    with destination.open("wb") as buffer:
        async for chunk in request.stream():
            total += len(chunk)
            if total > settings.max_upload_bytes:
                logger.warning("request_id=%s stage=upload_too_large bytes=%s", request_id, total)
                raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
            buffer.write(chunk)
    logger.info("request_id=%s stage=raw_upload_done elapsed_ms=%s bytes=%s", request_id, _elapsed_ms(started_at), total)
    return total


async def write_upload_to_file(upload: UploadFile, destination: Path, request_id: str) -> int:
    total = 0
    logger.info(
        "request_id=%s stage=multipart_upload_start filename=%s content_type=%s",
        request_id,
        upload.filename,
        upload.content_type,
    )
    started_at = perf_counter()
    with destination.open("wb") as buffer:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                logger.warning("request_id=%s stage=upload_too_large bytes=%s", request_id, total)
                raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
            buffer.write(chunk)
    logger.info("request_id=%s stage=multipart_upload_done elapsed_ms=%s bytes=%s", request_id, _elapsed_ms(started_at), total)
    return total


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "api_version": settings.api_version,
        "pdfbox_jar_configured": bool(settings.pdfbox_jar),
        "pdfbox_jar_exists": Path(settings.pdfbox_jar).exists(),
        "openai_configured": bool(settings.openai_api_key),
        "openai_model": settings.openai_model,
        "allowed_openai_models": sorted(ALLOWED_OPENAI_MODELS),
        "ocr_enabled": settings.ocr_enabled,
        "ocr_language": settings.ocr_language,
    }


def parse_text_to_invoice_import(
    *,
    text: str,
    filename: str | None,
    context: dict[str, int | bool | None],
    openai_model: str | None,
    request_id: str,
) -> dict:
    try:
        return parse_invoice_text(
            text=text,
            filename=filename,
            id_tenant=context["id_tenant"],  # type: ignore[arg-type]
            id_usuario_incluiu=context["id_usuario_incluiu"],  # type: ignore[arg-type]
            id_processoimportacao=context["id_processoimportacao"],  # type: ignore[arg-type]
            include_extracted_text=bool(context["include_extracted_text"]),
            openai_model=openai_model,
            request_id=request_id,
        )
    except InvoiceParseError as exc:
        logger.exception("request_id=%s stage=parse_error error=%s", request_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/pdf/extract-text")
async def extract_text_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
) -> dict[str, str | int | bool | None]:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/pdf/extract-text stage=request_start filename=%s", request_id, file.filename)
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Envie um arquivo PDF.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_upload_to_file(file, pdf_path, request_id)
        extraction = extract_from_temp_pdf(pdf_path, options, request_id)

    logger.info("request_id=%s endpoint=/v1/pdf/extract-text stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))

    return {
        "request_id": request_id,
        "filename": file.filename,
        "bytes": byte_count,
        "text_length": len(extraction.text),
        "text": extraction.text,
        "extraction_method": extraction.method,
        "attempted_extraction_methods": extraction.attempted_methods,
        "extraction_warnings": extraction.warnings,
        "sort": options.sort,
        "rotation_magic": options.rotation_magic,
    }


@app.post("/v1/invoice/extract-and-parse")
async def extract_and_parse_invoice_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
    context: dict[str, int | bool | None] = Depends(build_context),
    openai_model: str | None = Depends(build_openai_model),
) -> dict:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/invoice/extract-and-parse stage=request_start filename=%s", request_id, file.filename)
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Envie um arquivo PDF.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_upload_to_file(file, pdf_path, request_id)
        extraction = extract_from_temp_pdf(pdf_path, options, request_id)

    parsed = parse_text_to_invoice_import(
        text=extraction.text,
        filename=file.filename,
        context=context,
        openai_model=openai_model,
        request_id=request_id,
    )
    logger.info("request_id=%s endpoint=/v1/invoice/extract-and-parse stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    return {
        "request_id": request_id,
        "filename": file.filename,
        "bytes": byte_count,
        "text_length": len(extraction.text),
        "extraction_method": extraction.method,
        "attempted_extraction_methods": extraction.attempted_methods,
        "extraction_warnings": extraction.warnings,
        **parsed,
    }


@app.post("/v1/invoice/parse-pdf-openai")
async def parse_invoice_pdf_openai_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    context: dict[str, int | bool | None] = Depends(build_context),
    openai_model: str | None = Depends(build_openai_model),
    auxiliary_ocr: bool = Query(default=False),
) -> dict:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/invoice/parse-pdf-openai stage=request_start filename=%s", request_id, file.filename)
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Envie um arquivo PDF.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_upload_to_file(file, pdf_path, request_id)
        auxiliary_extraction = extract_auxiliary_text_for_pdf_parse(
            pdf_path,
            request_id,
            enable_ocr=auxiliary_ocr,
        )
        parsed = parse_pdf_file_to_invoice_import(
            pdf_path=pdf_path,
            filename=file.filename,
            context=context,
            openai_model=openai_model,
            request_id=request_id,
            fallback_text=auxiliary_extraction.text if auxiliary_extraction else None,
        )

    logger.info("request_id=%s endpoint=/v1/invoice/parse-pdf-openai stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    return {
        "request_id": request_id,
        "filename": file.filename,
        "bytes": byte_count,
        "extraction_method": "openai_pdf_vision",
        "auxiliary_ocr_enabled": auxiliary_ocr,
        "auxiliary_text_method": auxiliary_extraction.method if auxiliary_extraction else None,
        "auxiliary_text_length": len(auxiliary_extraction.text) if auxiliary_extraction else 0,
        **parsed,
    }


@app.post("/v1/pdf/extract-text/raw")
async def extract_text_raw_pdf(
    request: Request,
    filename: str | None = Query(default=None),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
) -> dict[str, str | int | bool | None]:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/pdf/extract-text/raw stage=request_start filename=%s", request_id, filename)
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Content-Type deve ser application/pdf.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_request_stream_to_file(request, pdf_path, request_id)
        extraction = extract_from_temp_pdf(pdf_path, options, request_id)

    logger.info("request_id=%s endpoint=/v1/pdf/extract-text/raw stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))

    return {
        "request_id": request_id,
        "filename": filename,
        "bytes": byte_count,
        "text_length": len(extraction.text),
        "text": extraction.text,
        "extraction_method": extraction.method,
        "attempted_extraction_methods": extraction.attempted_methods,
        "extraction_warnings": extraction.warnings,
        "sort": options.sort,
        "rotation_magic": options.rotation_magic,
    }


@app.post("/v1/invoice/extract-and-parse/raw")
async def extract_and_parse_invoice_raw_pdf(
    request: Request,
    filename: str | None = Query(default=None),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
    context: dict[str, int | bool | None] = Depends(build_context),
    openai_model: str | None = Depends(build_openai_model),
) -> dict:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/invoice/extract-and-parse/raw stage=request_start filename=%s", request_id, filename)
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Content-Type deve ser application/pdf.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_request_stream_to_file(request, pdf_path, request_id)
        extraction = extract_from_temp_pdf(pdf_path, options, request_id)

    parsed = parse_text_to_invoice_import(
        text=extraction.text,
        filename=filename,
        context=context,
        openai_model=openai_model,
        request_id=request_id,
    )
    logger.info("request_id=%s endpoint=/v1/invoice/extract-and-parse/raw stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    return {
        "request_id": request_id,
        "filename": filename,
        "bytes": byte_count,
        "text_length": len(extraction.text),
        "extraction_method": extraction.method,
        "attempted_extraction_methods": extraction.attempted_methods,
        "extraction_warnings": extraction.warnings,
        **parsed,
    }


@app.post("/v1/invoice/parse-pdf-openai/raw")
async def parse_invoice_pdf_openai_raw(
    request: Request,
    filename: str | None = Query(default=None),
    _: None = Depends(require_api_key),
    context: dict[str, int | bool | None] = Depends(build_context),
    openai_model: str | None = Depends(build_openai_model),
    auxiliary_ocr: bool = Query(default=False),
) -> dict:
    request_id = new_request_id()
    logger.info("request_id=%s endpoint=/v1/invoice/parse-pdf-openai/raw stage=request_start filename=%s", request_id, filename)
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Content-Type deve ser application/pdf.")

    started_at = perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_request_stream_to_file(request, pdf_path, request_id)
        auxiliary_extraction = extract_auxiliary_text_for_pdf_parse(
            pdf_path,
            request_id,
            enable_ocr=auxiliary_ocr,
        )
        parsed = parse_pdf_file_to_invoice_import(
            pdf_path=pdf_path,
            filename=filename,
            context=context,
            openai_model=openai_model,
            request_id=request_id,
            fallback_text=auxiliary_extraction.text if auxiliary_extraction else None,
        )

    logger.info("request_id=%s endpoint=/v1/invoice/parse-pdf-openai/raw stage=request_done elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    return {
        "request_id": request_id,
        "filename": filename,
        "bytes": byte_count,
        "extraction_method": "openai_pdf_vision",
        "auxiliary_ocr_enabled": auxiliary_ocr,
        "auxiliary_text_method": auxiliary_extraction.method if auxiliary_extraction else None,
        "auxiliary_text_length": len(auxiliary_extraction.text) if auxiliary_extraction else 0,
        **parsed,
    }


def new_request_id() -> str:
    return uuid4().hex[:12]


def parse_pdf_file_to_invoice_import(
    *,
    pdf_path: Path,
    filename: str | None,
    context: dict[str, int | bool | None],
    openai_model: str | None,
    request_id: str,
    fallback_text: str | None,
) -> dict:
    try:
        return parse_invoice_pdf_file(
            pdf_path=pdf_path,
            filename=filename,
            id_tenant=context["id_tenant"],  # type: ignore[arg-type]
            id_usuario_incluiu=context["id_usuario_incluiu"],  # type: ignore[arg-type]
            id_processoimportacao=context["id_processoimportacao"],  # type: ignore[arg-type]
            fallback_text=fallback_text,
            openai_model=openai_model,
            request_id=request_id,
        )
    except InvoiceParseError as exc:
        logger.exception("request_id=%s stage=parse_pdf_error error=%s", request_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)
