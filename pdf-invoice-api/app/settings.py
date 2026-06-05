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
    max_upload_mb: int = _int_env("MAX_UPLOAD_MB", 25)
    pdfbox_timeout_seconds: int = _int_env("PDFBOX_TIMEOUT_SECONDS", 60)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
