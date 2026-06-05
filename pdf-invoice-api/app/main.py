from pathlib import Path
import tempfile

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile

from .pdfbox import ExtractOptions, PDFBoxError, extract_text_with_pdfbox
from .settings import settings


app = FastAPI(
    title="PDF Invoice API",
    version="0.1.0",
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
) -> ExtractOptions:
    if start_page and end_page and end_page < start_page:
        raise HTTPException(status_code=422, detail="end_page deve ser maior ou igual a start_page.")
    return ExtractOptions(
        start_page=start_page,
        end_page=end_page,
        password=password,
        sort=sort,
        rotation_magic=rotation_magic,
    )


def extract_from_temp_pdf(pdf_path: Path, options: ExtractOptions) -> str:
    try:
        return extract_text_with_pdfbox(
            pdf_path=pdf_path,
            pdfbox_jar=settings.pdfbox_jar,
            java_bin=settings.java_bin,
            timeout_seconds=settings.pdfbox_timeout_seconds,
            options=options,
        )
    except PDFBoxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def write_request_stream_to_file(request: Request, destination: Path) -> int:
    total = 0
    with destination.open("wb") as buffer:
        async for chunk in request.stream():
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
            buffer.write(chunk)
    return total


async def write_upload_to_file(upload: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as buffer:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="PDF excede o tamanho maximo permitido.")
            buffer.write(chunk)
    return total


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "pdfbox_jar_configured": bool(settings.pdfbox_jar),
        "pdfbox_jar_exists": Path(settings.pdfbox_jar).exists(),
    }


@app.post("/v1/pdf/extract-text")
async def extract_text_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
) -> dict[str, str | int | bool | None]:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Envie um arquivo PDF.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_upload_to_file(file, pdf_path)
        text = extract_from_temp_pdf(pdf_path, options)

    return {
        "filename": file.filename,
        "bytes": byte_count,
        "text_length": len(text),
        "text": text,
        "sort": options.sort,
        "rotation_magic": options.rotation_magic,
    }


@app.post("/v1/pdf/extract-text/raw")
async def extract_text_raw_pdf(
    request: Request,
    filename: str | None = Query(default=None),
    _: None = Depends(require_api_key),
    options: ExtractOptions = Depends(build_options),
) -> dict[str, str | int | bool | None]:
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    if content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Content-Type deve ser application/pdf.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        byte_count = await write_request_stream_to_file(request, pdf_path)
        text = extract_from_temp_pdf(pdf_path, options)

    return {
        "filename": filename,
        "bytes": byte_count,
        "text_length": len(text),
        "text": text,
        "sort": options.sort,
        "rotation_magic": options.rotation_magic,
    }
