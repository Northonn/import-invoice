from datetime import UTC, datetime
import json
import logging
from time import perf_counter
from typing import Any

from openai import OpenAI, OpenAIError

from .invoice_schema import INVOICE_IMPORT_SCHEMA, REQUIRED_FOR_INSERT
from .settings import settings


logger = logging.getLogger("pdf_invoice_api.invoice_parser")


class InvoiceParseError(RuntimeError):
    pass


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
        "text_length": len(text),
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


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)
