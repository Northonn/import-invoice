from dataclasses import dataclass
import os


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    pdfbox_jar: str = os.getenv("PDFBOX_JAR", "/opt/pdfbox/pdfbox-app.jar")
    java_bin: str = os.getenv("JAVA_BIN", "java")
    api_key: str | None = os.getenv("API_KEY")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    max_upload_mb: int = _int_env("MAX_UPLOAD_MB", 25)
    pdfbox_timeout_seconds: int = _int_env("PDFBOX_TIMEOUT_SECONDS", 60)
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() in {"1", "true", "yes", "s"}
    ocr_language: str = os.getenv("OCR_LANGUAGE", "eng+por")
    ocr_dpi: int = _int_env("OCR_DPI", 150)
    ocr_max_pages: int = _int_env("OCR_MAX_PAGES", 1)
    ocr_page_timeout_seconds: int = _int_env("OCR_PAGE_TIMEOUT_SECONDS", 20)
    min_text_chars_for_ocr: int = _int_env("MIN_TEXT_CHARS_FOR_OCR", 80)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
