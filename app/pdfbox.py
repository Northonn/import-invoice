from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile


class PDFBoxError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractOptions:
    start_page: int | None = None
    end_page: int | None = None
    password: str | None = None
    sort: bool = True
    rotation_magic: bool = False
    enable_ocr: bool = True
    force_ocr: bool = False


def extract_text_with_pdfbox(
    *,
    pdf_path: Path,
    pdfbox_jar: str,
    java_bin: str,
    timeout_seconds: int,
    options: ExtractOptions,
) -> str:
    jar_path = Path(pdfbox_jar)
    if not jar_path.exists():
        raise PDFBoxError(f"Arquivo PDFBox nao encontrado: {jar_path}")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=True) as output_file:
        command = [
            java_bin,
            "-jar",
            str(jar_path),
            "export:text",
            "-encoding=UTF-8",
            f"-i={pdf_path}",
            f"-o={output_file.name}",
        ]

        if options.sort:
            command.append("-sort")
        if options.rotation_magic:
            command.append("-rotationMagic")
        if options.start_page is not None:
            command.append(f"-startPage={options.start_page}")
        if options.end_page is not None:
            command.append(f"-endPage={options.end_page}")
        if options.password:
            command.append(f"-password={options.password}")

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise PDFBoxError("Tempo limite excedido ao processar o PDF.") from exc
        except OSError as exc:
            raise PDFBoxError(f"Falha ao executar Java/PDFBox: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise PDFBoxError(detail or "PDFBox retornou erro sem detalhes.")

        return Path(output_file.name).read_text(encoding="utf-8", errors="replace")
