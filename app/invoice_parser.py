from datetime import UTC, datetime
import base64
import json
import logging
from pathlib import Path
import re
from time import perf_counter
from typing import Any

from openai import OpenAI, OpenAIError

from .invoice_prompt import INVOICE_EXTRACTION_PROMPT, INVOICE_EXTRACTION_PROMPT_VERSION
from .invoice_schema import INVOICE_IMPORT_SCHEMA, REQUIRED_FOR_INSERT
from .settings import settings


logger = logging.getLogger("pdf_invoice_api.invoice_parser")


class InvoiceParseError(RuntimeError):
    pass


MODEL_PRICES_USD_PER_1M_TOKENS = {
    "gpt-4.1-mini": {
        "input": 0.40,
        "cached_input": 0.10,
        "output": 1.60,
    },
    "gpt-4.1-mini-2025-04-14": {
        "input": 0.40,
        "cached_input": 0.10,
        "output": 1.60,
    },
    "gpt-5-mini": {
        "input": 0.25,
        "cached_input": 0.025,
        "output": 2.00,
    },
    "gpt-5-mini-2025-08-07": {
        "input": 0.25,
        "cached_input": 0.025,
        "output": 2.00,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}


SYSTEM_PROMPT = INVOICE_EXTRACTION_PROMPT
PROMPT_VERSION = INVOICE_EXTRACTION_PROMPT_VERSION


def parse_invoice_text(
    *,
    text: str,
    filename: str | None,
    id_tenant: int | None,
    id_usuario_incluiu: int | None,
    id_processoimportacao: int | None,
    include_extracted_text: bool,
    openai_model: str | None,
    request_id: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise InvoiceParseError("OPENAI_API_KEY nao configurada no servidor.")

    selected_model = openai_model or settings.openai_model
    logger.info(
        "request_id=%s stage=openai_parse_start model=%s text_chars=%s filename=%s",
        request_id,
        selected_model,
        len(text),
        filename,
    )
    client = OpenAI(api_key=settings.openai_api_key)
    context = {
        "id_tenant": id_tenant,
        "id_usuario_incluiu": id_usuario_incluiu,
        "id_processoimportacao": id_processoimportacao,
    }

    user_prompt = {
        "filename": filename,
        "context": context,
        "invoice_text": text,
    }

    try:
        started_at = perf_counter()
        response = client.responses.create(
            model=selected_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Transforme o texto da invoice neste JSON estruturado:\n"
                    + json.dumps(user_prompt, ensure_ascii=False),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "invoice_import",
                    "strict": True,
                    "schema": INVOICE_IMPORT_SCHEMA,
                }
            },
        )
        logger.info(
            "request_id=%s stage=openai_response_done elapsed_ms=%s output_chars=%s",
            request_id,
            _elapsed_ms(started_at),
            len(response.output_text or ""),
        )
    except OpenAIError as exc:
        logger.exception("request_id=%s stage=openai_error error=%s", request_id, exc)
        raise InvoiceParseError(f"Erro ao chamar OpenAI: {exc}") from exc

    usage = _build_usage_summary(response, selected_model)
    _log_usage(request_id=request_id, stage="openai_usage", usage=usage)

    try:
        started_at = perf_counter()
        parsed = json.loads(response.output_text)
        logger.info("request_id=%s stage=openai_json_loaded elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    except (TypeError, json.JSONDecodeError) as exc:
        logger.exception("request_id=%s stage=openai_json_error", request_id)
        raise InvoiceParseError("OpenAI retornou uma resposta que nao foi possivel ler como JSON.") from exc

    _normalize_invoice_number(parsed, text)
    _normalize_customer_order_reference(parsed, text)
    _sanitize_importer_document(parsed, text)
    _sanitize_party_documents(parsed)
    parsed["schema_version"] = "1.0"
    parsed["source"] = {
        "type": "pdf_invoice",
        "filename": filename,
        "extracted_text": text if include_extracted_text else None,
        "extracted_at": datetime.now(UTC).isoformat(),
        "api_version": settings.api_version,
        "prompt_version": PROMPT_VERSION,
    }
    parsed["context"] = context
    parsed["required_for_insert"] = REQUIRED_FOR_INSERT

    pending_fields = find_pending_required_fields(parsed)
    logger.info(
        "request_id=%s stage=openai_parse_done items=%s pending_fields=%s",
        request_id,
        len(parsed.get("items") or []),
        len(pending_fields),
    )

    return {
        "api_version": settings.api_version,
        "prompt_version": PROMPT_VERSION,
        "model": selected_model,
        "usage": usage,
        "text_length": len(text),
        "invoice_import": parsed,
        "pending_fields": pending_fields,
    }


def parse_invoice_pdf_file(
    *,
    pdf_path: Path,
    filename: str | None,
    id_tenant: int | None,
    id_usuario_incluiu: int | None,
    id_processoimportacao: int | None,
    fallback_text: str | None = None,
    openai_model: str | None,
    request_id: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise InvoiceParseError("OPENAI_API_KEY nao configurada no servidor.")

    selected_model = openai_model or settings.openai_model
    logger.info(
        "request_id=%s stage=openai_pdf_parse_start model=%s filename=%s bytes=%s",
        request_id,
        selected_model,
        filename,
        pdf_path.stat().st_size,
    )

    client = OpenAI(api_key=settings.openai_api_key)
    context = {
        "id_tenant": id_tenant,
        "id_usuario_incluiu": id_usuario_incluiu,
        "id_processoimportacao": id_processoimportacao,
    }

    started_at = perf_counter()
    base64_pdf = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
    logger.info(
        "request_id=%s stage=openai_pdf_base64_done elapsed_ms=%s base64_chars=%s",
        request_id,
        _elapsed_ms(started_at),
        len(base64_pdf),
    )

    instruction = {
        "filename": filename,
        "context": context,
        "task": "Analise este PDF de invoice, incluindo paginas escaneadas/imagens, e retorne o JSON estruturado.",
        "auxiliary_extracted_text": fallback_text,
    }

    try:
        started_at = perf_counter()
        response = client.responses.create(
            model=selected_model,
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": filename or "invoice.pdf",
                            "file_data": f"data:application/pdf;base64,{base64_pdf}",
                        },
                        {
                            "type": "input_text",
                            "text": json.dumps(instruction, ensure_ascii=False),
                        },
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "invoice_import",
                    "strict": True,
                    "schema": INVOICE_IMPORT_SCHEMA,
                }
            },
        )
        logger.info(
            "request_id=%s stage=openai_pdf_response_done elapsed_ms=%s output_chars=%s",
            request_id,
            _elapsed_ms(started_at),
            len(response.output_text or ""),
        )
    except OpenAIError as exc:
        logger.exception("request_id=%s stage=openai_pdf_error error=%s", request_id, exc)
        raise InvoiceParseError(f"Erro ao chamar OpenAI com PDF: {exc}") from exc

    usage = _build_usage_summary(response, selected_model)
    _log_usage(request_id=request_id, stage="openai_pdf_usage", usage=usage)

    try:
        parsed = json.loads(response.output_text)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.exception("request_id=%s stage=openai_pdf_json_error", request_id)
        raise InvoiceParseError("OpenAI retornou uma resposta que nao foi possivel ler como JSON.") from exc

    _normalize_invoice_number(parsed, fallback_text)
    _normalize_customer_order_reference(parsed, fallback_text)
    _sanitize_importer_document(parsed, fallback_text)
    _sanitize_party_documents(parsed)
    parsed["schema_version"] = "1.0"
    parsed["source"] = {
        "type": "pdf_invoice",
        "filename": filename,
        "extracted_text": None,
        "extracted_at": datetime.now(UTC).isoformat(),
        "api_version": settings.api_version,
        "prompt_version": PROMPT_VERSION,
    }
    parsed["context"] = context
    parsed["required_for_insert"] = REQUIRED_FOR_INSERT

    pending_fields = find_pending_required_fields(parsed)
    logger.info(
        "request_id=%s stage=openai_pdf_parse_done items=%s pending_fields=%s",
        request_id,
        len(parsed.get("items") or []),
        len(pending_fields),
    )

    return {
        "api_version": settings.api_version,
        "prompt_version": PROMPT_VERSION,
        "model": selected_model,
        "usage": usage,
        "invoice_import": parsed,
        "pending_fields": pending_fields,
    }


def find_pending_required_fields(payload: dict[str, Any]) -> list[str]:
    pending: list[str] = []
    for field in REQUIRED_FOR_INSERT["imp_invoice"]:
        if _value_is_missing(_get_path(payload, field)):
            pending.append(field)

    items = payload.get("items") or []
    if not items:
        pending.extend(REQUIRED_FOR_INSERT["imp_invoice_item"])
        return pending

    for index, item in enumerate(items):
        item_payload = {"items": [item], "context": payload.get("context", {})}
        for field in REQUIRED_FOR_INSERT["imp_invoice_item"]:
            if _value_is_missing(_get_path(item_payload, field)):
                pending.append(field.replace("items[]", f"items[{index}]"))

    return pending


def _normalize_invoice_number(payload: dict[str, Any], text: str | None) -> None:
    invoice = payload.get("invoice")
    if not isinstance(invoice, dict):
        return

    current_number = invoice.get("num_invoice")
    if isinstance(current_number, str) and current_number.strip():
        invoice["num_invoice"] = current_number.strip()
        return

    if not text:
        return

    match = re.search(
        r"\b(?:proforma\s+invoice|proforma\s+invoice\s+no\.?|pi\s+no\.?)\s*[:#-]?\s*([A-Z0-9][\w.\-/]*)",
        text,
        re.IGNORECASE,
    )
    if match:
        invoice["num_invoice"] = match.group(1).strip(" \t\r\n:;#.,")


def _normalize_customer_order_reference(payload: dict[str, Any], text: str | None) -> None:
    invoice = payload.get("invoice")
    if not isinstance(invoice, dict):
        return

    order = invoice.get("pedido_importacao")
    if not isinstance(order, dict):
        return

    normalized = order.get("numero_pedido_importacao_extraido")
    original = order.get("referencia_original_extraida") or normalized
    if not isinstance(original, str) or not original.strip():
        return

    order["referencia_original_extraida"] = original.strip()
    label = order.get("rotulo_referencia_extraido")
    value = normalized if isinstance(normalized, str) and normalized.strip() else original
    prefix_pattern = re.compile(
        r"^(?:(?:customer\s+)?(?:purchase\s+order|p\s*[./]\s*o|p\.\s*o\.|po|order|"
        r"doc(?:ument(?:o)?)?\.?|refer.ncia|ref\.?)\b[\s:;#./-]*)+",
        re.IGNORECASE,
    )
    cleaned = prefix_pattern.sub("", value.strip()).strip(" \t\r\n:;#.,/\\-")

    is_supplier_customer_code = (
        _looks_like_supplier_customer_code(original)
        or _looks_like_supplier_customer_code(cleaned)
        or _looks_like_supplier_customer_code(label)
    )

    if _looks_like_address(cleaned) or _looks_like_address(original) or is_supplier_customer_code:
        crt_reference = _find_crt_reference(text) if text else None
        if crt_reference:
            order["referencia_original_extraida"] = crt_reference["original"]
            order["numero_pedido_importacao_extraido"] = crt_reference["number"]
            order["rotulo_referencia_extraido"] = crt_reference["label"]
        else:
            order["referencia_original_extraida"] = None
            order["numero_pedido_importacao_extraido"] = None
            order["rotulo_referencia_extraido"] = None
        return

    order["numero_pedido_importacao_extraido"] = cleaned or None


def _looks_like_address(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False

    upper = value.upper()
    address_pattern = re.compile(
        r"\b(ROD|ROD\.|RODOVIA|RUA|AV|AV\.|AVENIDA|DOMICILIO|DOMICÍLIO|ADDRESS|STREET|ROAD|"
        r"BAIRRO|CENTRAL|CEP|POSTAL|BELCHIOR|GASPAR|SC|BRASIL|BRAZIL|N[°ºO]\s*\d+)\b",
        re.IGNORECASE,
    )
    return bool(address_pattern.search(upper))


def _looks_like_supplier_customer_code(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False

    return bool(
        re.search(
            r"\b(C[OÓ]D(?:IGO)?\.?\s*(?:DO\s+)?CLIENTE|CUSTOMER\s+CODE|CLIENT\s+CODE|COD\.?\s*CLIENTE)\b",
            value,
            re.IGNORECASE,
        )
    )


def _find_crt_reference(text: str | None) -> dict[str, str] | None:
    if not text:
        return None

    match = re.search(r"\b(CRT)\s*[:#-]?\s*([A-Z]{1,4}[.\-/]?\d[\w.\-/]*)", text, re.IGNORECASE)
    if not match:
        return None

    label = match.group(1).upper()
    number = match.group(2).strip(" \t\r\n:;#.,")
    return {"label": label, "number": number, "original": f"{label}: {number}"}


def _sanitize_importer_document(payload: dict[str, Any], text: str | None) -> None:
    invoice = payload.get("invoice")
    if not isinstance(invoice, dict):
        return

    importer = invoice.get("importador")
    if not isinstance(importer, dict):
        return

    current_document = importer.get("documento_extraido")
    if _is_brazilian_tax_document(current_document):
        return

    document = _find_brazilian_document_near_importer(text, importer.get("nome_extraido")) if text else None
    if document:
        importer["documento_extraido"] = document
    elif isinstance(current_document, str) and current_document.strip():
        logger.info(
            "stage=importer_document_discarded invalid_document=%s",
            current_document,
        )
        importer["documento_extraido"] = None


def _sanitize_party_documents(payload: dict[str, Any]) -> None:
    invoice = payload.get("invoice")
    if not isinstance(invoice, dict):
        return

    importer = invoice.get("importador")
    exporter = invoice.get("exportador")
    if not isinstance(importer, dict) or not isinstance(exporter, dict):
        return

    importer_document = importer.get("documento_extraido")
    exporter_document = exporter.get("documento_extraido")
    if not _is_brazilian_tax_document(importer_document) or not _is_brazilian_tax_document(exporter_document):
        return

    if _only_digits(importer_document) != _only_digits(exporter_document):
        return

    logger.info(
        "stage=exporter_document_discarded reason=same_as_importer_document document=%s",
        exporter_document,
    )
    exporter["documento_extraido"] = None


def _find_brazilian_document_near_importer(text: str, importer_name: Any) -> str | None:
    cnpj_pattern = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
    normalized_text = text.replace("\r", "\n")
    candidates: list[tuple[int, str]] = []

    for match in re.finditer(
        r"(invoice\s+address|delivery\s+address|consignee|buyer|importer|customer|sold\s+to|ship\s+to|bill\s+to)",
        normalized_text,
        re.IGNORECASE,
    ):
        block = normalized_text[match.start() : match.start() + 700]
        for cnpj_match in cnpj_pattern.finditer(block):
            if _is_valid_cnpj(cnpj_match.group(0)):
                candidates.append((match.start(), cnpj_match.group(0)))
                break

    if isinstance(importer_name, str) and importer_name.strip():
        name_token = re.escape(importer_name.strip()[:60])
        name_match = re.search(name_token, normalized_text, re.IGNORECASE)
        if name_match:
            block = normalized_text[name_match.start() : name_match.start() + 500]
            for cnpj_match in cnpj_pattern.finditer(block):
                if _is_valid_cnpj(cnpj_match.group(0)):
                    candidates.insert(0, (name_match.start(), cnpj_match.group(0)))
                    break

    if candidates:
        return candidates[0][1]

    return None


def _is_brazilian_tax_document(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    digits = _only_digits(value)
    if len(digits) == 14:
        return _is_valid_cnpj(digits)
    if len(digits) == 11:
        return _is_valid_cpf(digits)
    return False


def _only_digits(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def _is_valid_cnpj(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    def check_digit(prefix: str, weights: list[int]) -> str:
        total = sum(int(digit) * weight for digit, weight in zip(prefix, weights))
        remainder = total % 11
        return "0" if remainder < 2 else str(11 - remainder)

    first = check_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    second = check_digit(digits[:12] + first, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == first + second


def _is_valid_cpf(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    first_total = sum(int(digits[i]) * (10 - i) for i in range(9))
    first_remainder = (first_total * 10) % 11
    first = 0 if first_remainder == 10 else first_remainder

    second_total = sum(int(digits[i]) * (11 - i) for i in range(10))
    second_remainder = (second_total * 10) % 11
    second = 0 if second_remainder == 10 else second_remainder

    return digits[-2:] == f"{first}{second}"


def _get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.replace("items[]", "items.0").split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _value_is_missing(value: Any) -> bool:
    return value is None or value == ""


def _build_usage_summary(response: Any, model: str) -> dict[str, Any]:
    usage = _serialize_openai_object(getattr(response, "usage", None)) or {}
    usage["estimated_cost_usd"] = _estimate_cost_usd(usage, model)
    return usage


def _serialize_openai_object(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _serialize_openai_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_openai_object(item) for item in value]
    return value


def _estimate_cost_usd(usage: dict[str, Any], model: str) -> dict[str, float | None]:
    prices = MODEL_PRICES_USD_PER_1M_TOKENS.get(model)
    if not prices:
        return {
            "input": None,
            "cached_input": None,
            "output": None,
            "total": None,
        }

    input_tokens = _number_or_zero(usage.get("input_tokens"))
    output_tokens = _number_or_zero(usage.get("output_tokens"))
    cached_tokens = _cached_input_tokens(usage)
    non_cached_input_tokens = max(input_tokens - cached_tokens, 0)

    input_cost = non_cached_input_tokens / 1_000_000 * prices["input"]
    cached_input_cost = cached_tokens / 1_000_000 * prices["cached_input"]
    output_cost = output_tokens / 1_000_000 * prices["output"]

    return {
        "input": round(input_cost, 8),
        "cached_input": round(cached_input_cost, 8),
        "output": round(output_cost, 8),
        "total": round(input_cost + cached_input_cost + output_cost, 8),
    }


def _cached_input_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        return 0
    return _number_or_zero(details.get("cached_tokens"))


def _number_or_zero(value: Any) -> int:
    if isinstance(value, int | float):
        return int(value)
    return 0


def _log_usage(*, request_id: str, stage: str, usage: dict[str, Any]) -> None:
    logger.info(
        "request_id=%s stage=%s usage=%s",
        request_id,
        stage,
        json.dumps(usage, ensure_ascii=False, sort_keys=True),
    )


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)
