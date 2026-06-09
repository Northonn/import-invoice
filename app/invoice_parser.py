from datetime import UTC, datetime
import base64
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

from openai import OpenAI, OpenAIError

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
}


SYSTEM_PROMPT = """
Voce e um extrator de dados de commercial invoices de comercio exterior.
Retorne JSON conforme o schema informado.
Extraia apenas informacoes presentes no texto.
Nao invente IDs internos do sistema. Campos id_* devem permanecer null, exceto quando forem fornecidos no contexto.
Quando nao encontrar um campo, retorne null.
Datas devem ficar em YYYY-MM-DD quando a data completa existir; caso contrario, null.
Numeros devem ser retornados como number, sem simbolo de moeda e sem separador de milhar.
Use ponto como separador decimal.
Moedas devem usar codigo ISO quando aparecer, por exemplo USD, EUR, BRL.
Incoterms devem usar codigo curto quando aparecer, por exemplo EXW, FOB, CIF.
Itens devem representar as linhas de mercadoria da invoice, nao dados bancarios ou totais.
""".strip()


def parse_invoice_text(
    *,
    text: str,
    filename: str | None,
    id_tenant: int | None,
    id_usuario_incluiu: int | None,
    id_processoimportacao: int | None,
    include_extracted_text: bool,
    request_id: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise InvoiceParseError("OPENAI_API_KEY nao configurada no servidor.")

    logger.info(
        "request_id=%s stage=openai_parse_start model=%s text_chars=%s filename=%s",
        request_id,
        settings.openai_model,
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
            model=settings.openai_model,
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

    usage = _build_usage_summary(response, settings.openai_model)
    _log_usage(request_id=request_id, stage="openai_usage", usage=usage)

    try:
        started_at = perf_counter()
        parsed = json.loads(response.output_text)
        logger.info("request_id=%s stage=openai_json_loaded elapsed_ms=%s", request_id, _elapsed_ms(started_at))
    except (TypeError, json.JSONDecodeError) as exc:
        logger.exception("request_id=%s stage=openai_json_error", request_id)
        raise InvoiceParseError("OpenAI retornou uma resposta que nao foi possivel ler como JSON.") from exc

    parsed["schema_version"] = "1.0"
    parsed["source"] = {
        "type": "pdf_invoice",
        "filename": filename,
        "extracted_text": text if include_extracted_text else None,
        "extracted_at": datetime.now(UTC).isoformat(),
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
        "model": settings.openai_model,
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
    request_id: str,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise InvoiceParseError("OPENAI_API_KEY nao configurada no servidor.")

    logger.info(
        "request_id=%s stage=openai_pdf_parse_start model=%s filename=%s bytes=%s",
        request_id,
        settings.openai_model,
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
    }

    try:
        started_at = perf_counter()
        response = client.responses.create(
            model=settings.openai_model,
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

    usage = _build_usage_summary(response, settings.openai_model)
    _log_usage(request_id=request_id, stage="openai_pdf_usage", usage=usage)

    try:
        parsed = json.loads(response.output_text)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.exception("request_id=%s stage=openai_pdf_json_error", request_id)
        raise InvoiceParseError("OpenAI retornou uma resposta que nao foi possivel ler como JSON.") from exc

    parsed["schema_version"] = "1.0"
    parsed["source"] = {
        "type": "pdf_invoice",
        "filename": filename,
        "extracted_text": None,
        "extracted_at": datetime.now(UTC).isoformat(),
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
        "model": settings.openai_model,
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
