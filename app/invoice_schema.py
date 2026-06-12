from typing import Any


def nullable(schema_type: str) -> dict[str, Any]:
    return {"type": [schema_type, "null"]}


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties.keys()),
    }


def enum(values: list[Any]) -> dict[str, Any]:
    if None in values:
        return {"type": ["string", "null"], "enum": values}
    return {"type": "string", "enum": values}


REQUIRED_FOR_INSERT = {
    "imp_invoice": [
        "context.id_tenant",
        "context.id_usuario_incluiu",
        "invoice.num_invoice",
        "invoice.exportador.id_exportador",
        "invoice.importador.id_importador",
        "invoice.condicao_pagamento.id_condicaopagamento",
        "invoice.incoterm.id_incoterm",
        "invoice.moeda.id_moeda",
        "invoice.valores.valor_invoice_informado",
    ],
    "imp_invoice_item": [
        "context.id_tenant",
        "context.id_usuario_incluiu",
        "items[].entrega.id_entrega",
        "items[].entrega_item.id_entrega_item",
        "items[].item.id_item",
        "items[].ncm.id_ncm",
        "items[].unidade_medida.id_unidademedida",
        "items[].quantidade",
        "items[].valores.valor_unitario",
        "items[].valores.valor_total_condicao_venda",
    ],
}

person_schema = obj(
    {
        "id_exportador": nullable("integer"),
        "nome_extraido": nullable("string"),
        "documento_extraido": nullable("string"),
    }
)

INVOICE_IMPORT_SCHEMA = obj(
    {
        "schema_version": {"type": "string"},
        "source": obj(
            {
                "type": {"type": "string", "enum": ["pdf_invoice"]},
                "filename": nullable("string"),
                "extracted_text": nullable("string"),
                "extracted_at": nullable("string"),
            }
        ),
        "context": obj(
            {
                "id_tenant": nullable("integer"),
                "id_usuario_incluiu": nullable("integer"),
                "id_processoimportacao": nullable("integer"),
            }
        ),
        "invoice": obj(
            {
                "num_invoice": nullable("string"),
                "data_invoice": nullable("string"),
                "ind_status": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "pedido_importacao": obj(
                    {
                        "id_pedidoimportacao": nullable("integer"),
                        "numero_pedido_importacao_extraido": nullable("string"),
                        "rotulo_referencia_extraido": nullable("string"),
                    }
                ),
                "exportador": person_schema,
                "importador": obj(
                    {
                        "id_importador": nullable("integer"),
                        "nome_extraido": nullable("string"),
                        "documento_extraido": nullable("string"),
                    }
                ),
                "adquirente": obj(
                    {
                        "id_adquirente": nullable("integer"),
                        "nome_extraido": nullable("string"),
                        "documento_extraido": nullable("string"),
                    }
                ),
                "condicao_pagamento": obj(
                    {
                        "id_condicaopagamento": nullable("integer"),
                        "descricao_extraida": nullable("string"),
                    }
                ),
                "incoterm": obj(
                    {
                        "id_incoterm": nullable("integer"),
                        "codigo_extraido": nullable("string"),
                    }
                ),
                "moeda": obj(
                    {
                        "id_moeda": nullable("integer"),
                        "codigo_extraido": nullable("string"),
                    }
                ),
                "ind_forma_pagamento": {"type": "integer", "enum": [1, 2]},
                "pesos": obj({"peso_liquido": nullable("number"), "peso_bruto": nullable("number")}),
                "valores": obj(
                    {
                        "valor_total_mercadoria": nullable("number"),
                        "valor_desconto": nullable("number"),
                        "valor_despesa_invoice": nullable("number"),
                        "valor_total_condicao_venda": nullable("number"),
                        "valor_invoice_informado": nullable("number"),
                        "valor_compensado": nullable("number"),
                        "valor_total_financeiro": nullable("number"),
                    }
                ),
                "pagamento": obj({"ind_situacao_titulo_pagamento": enum(["N", "S"])}),
                "divergencia": obj(
                    {
                        "ind_divergencia": enum(["S", "N", None]),
                        "ind_tratamento_saldo": nullable("string"),
                        "motivo_desconto": nullable("string"),
                    }
                ),
            }
        ),
        "items": {
            "type": "array",
            "items": obj(
                {
                    "sequencia_item_invoice": nullable("integer"),
                    "entrega": obj(
                        {
                            "id_entrega": nullable("integer"),
                            "referencia_extraida": nullable("string"),
                        }
                    ),
                    "entrega_item": obj(
                        {
                            "id_entrega_item": nullable("integer"),
                            "referencia_extraida": nullable("string"),
                        }
                    ),
                    "item": obj(
                        {
                            "id_item": nullable("integer"),
                            "codigo_extraido": nullable("string"),
                            "descricao_extraida": nullable("string"),
                        }
                    ),
                    "ncm": obj({"id_ncm": nullable("integer"), "codigo_extraido": nullable("string")}),
                    "unidade_medida": obj(
                        {
                            "id_unidademedida": nullable("integer"),
                            "codigo_extraido": nullable("string"),
                        }
                    ),
                    "quantidade": nullable("number"),
                    "pesos": obj(
                        {
                            "peso_unitario": nullable("number"),
                            "peso_liquido_total": nullable("number"),
                            "peso_bruto_unitario": nullable("number"),
                            "peso_bruto_total": nullable("number"),
                        }
                    ),
                    "valores": obj(
                        {
                            "valor_unitario": nullable("number"),
                            "valor_desconto": nullable("number"),
                            "valor_total_condicao_venda": nullable("number"),
                            "valor_total_desconto_invoice_item": nullable("number"),
                            "valor_total_mercadoria": nullable("number"),
                            "valor_total_despesa_invoice_item": nullable("number"),
                        }
                    ),
                    "fabricante": obj(
                        {
                            "id_fabricante": nullable("integer"),
                            "nome_extraido": nullable("string"),
                        }
                    ),
                    "pais_origem": obj(
                        {
                            "id_pais_origem": nullable("integer"),
                            "codigo_extraido": nullable("string"),
                            "nome_extraido": nullable("string"),
                        }
                    ),
                }
            ),
        },
        "required_for_insert": obj(
            {
                "imp_invoice": {"type": "array", "items": {"type": "string"}},
                "imp_invoice_item": {"type": "array", "items": {"type": "string"}},
            }
        ),
    }
)
