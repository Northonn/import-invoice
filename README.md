# PDF Invoice API

API Python para receber invoices em PDF, extrair texto com Apache PDFBox e devolver JSON para consumo pelo Oracle APEX.

O PDFBox nao e uma API HTTP pronta; ele e uma biblioteca/ferramenta Java. Este projeto publica uma API HTTP em FastAPI que chama o `pdfbox-app.jar` por linha de comando.

## Endpoints

- `GET /health`: verifica se a API esta no ar e se o JAR do PDFBox existe.
- `POST /v1/pdf/extract-text`: recebe PDF em `multipart/form-data`, campo `file`.
- `POST /v1/pdf/extract-text/raw`: recebe o corpo bruto com `Content-Type: application/pdf`. Este endpoint costuma ser mais simples para enviar BLOB do Oracle APEX.
- `POST /v1/invoice/extract-and-parse`: recebe PDF em `multipart/form-data`, extrai texto e transforma em JSON de importacao usando OpenAI.
- `POST /v1/invoice/extract-and-parse/raw`: recebe PDF bruto, extrai texto e transforma em JSON de importacao usando OpenAI. Recomendado para APEX.

Parametros opcionais de query:

- `start_page`: primeira pagina, base 1.
- `end_page`: ultima pagina, base 1.
- `password`: senha do PDF, se houver.
- `sort`: ordena texto por posicao antes de escrever. Padrao: `true`.
- `rotation_magic`: tenta corrigir texto rotacionado/inclinado. Padrao: `false`.
- `id_tenant`: ID do tenant vindo do sistema.
- `id_usuario_incluiu`: ID do usuario logado no sistema.
- `id_processoimportacao`: ID do processo de importacao, se ja existir.
- `include_extracted_text`: inclui o texto extraido dentro de `invoice_import.source.extracted_text`. Padrao: `false`.

## Publicacao com Docker

```bash
docker compose up --build -d
```

Teste:

```bash
curl http://localhost:8000/health
```

Envio multipart:

```bash
curl -X POST "http://localhost:8000/v1/pdf/extract-text?sort=true" \
  -H "X-API-Key: troque-esta-chave" \
  -F "file=@invoice.pdf;type=application/pdf"
```

Envio PDF bruto:

```bash
curl -X POST "http://localhost:8000/v1/pdf/extract-text/raw?filename=invoice.pdf" \
  -H "X-API-Key: troque-esta-chave" \
  -H "Content-Type: application/pdf" \
  --data-binary "@invoice.pdf"
```

Extrair e analisar invoice com OpenAI:

```bash
curl -X POST "http://localhost:8000/v1/invoice/extract-and-parse?id_tenant=1&id_usuario_incluiu=10" \
  -H "X-API-Key: troque-esta-chave" \
  -F "file=@invoice.pdf;type=application/pdf"
```

Extrair e analisar invoice via PDF bruto:

```bash
curl -X POST "http://localhost:8000/v1/invoice/extract-and-parse/raw?filename=invoice.pdf&id_tenant=1&id_usuario_incluiu=10" \
  -H "X-API-Key: troque-esta-chave" \
  -H "Content-Type: application/pdf" \
  --data-binary "@invoice.pdf"
```

## Publicacao gratis para teste no Render

O projeto inclui `render.yaml` para criar um Web Service gratuito no Render usando Docker.

Passo a passo:

1. Suba esta pasta para um repositorio GitHub.
2. Crie uma conta em https://render.com.
3. No Dashboard, escolha `New` > `Blueprint`.
4. Conecte o repositorio GitHub.
5. O Render vai detectar o `render.yaml` na raiz do repositorio.
6. Apos publicar, teste:

```bash
curl https://SEU-SERVICO.onrender.com/health
```

O Render gera automaticamente a variavel `API_KEY`. Veja o valor em `Environment` no dashboard e use no header `X-API-Key`.

Para o endpoint com analise por IA, configure tambem no Render:

```text
OPENAI_API_KEY=sua-chave-openai
OPENAI_MODEL=gpt-4.1-mini
```

Observacao: no plano gratis, o servico pode dormir apos alguns minutos sem trafego. A primeira chamada depois disso pode demorar.

## Execucao local sem Docker

Requisitos:

- Python 3.11+
- Java 17+
- `pdfbox-app-3.0.5.jar`

Baixe o PDFBox:

```bash
chmod +x scripts/download_pdfbox.sh
./scripts/download_pdfbox.sh
```

Suba a API:

```bash
python -m venv .venv
. .venv/bin/activate
pip install .
export PDFBOX_JAR="$PWD/vendor/pdfbox/pdfbox-app-3.0.5.jar"
export API_KEY="troque-esta-chave"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Exemplo de chamada no Oracle APEX / PL/SQL

Use o endpoint raw quando o arquivo estiver salvo como BLOB em uma tabela ou item de upload.

```sql
declare
  l_response clob;
begin
  apex_web_service.g_request_headers.delete;
  apex_web_service.g_request_headers(1).name := 'Content-Type';
  apex_web_service.g_request_headers(1).value := 'application/pdf';
  apex_web_service.g_request_headers(2).name := 'X-API-Key';
  apex_web_service.g_request_headers(2).value := 'troque-esta-chave';

  l_response := apex_web_service.make_rest_request(
    p_url         => 'https://seu-dominio.com/v1/invoice/extract-and-parse/raw?filename=invoice.pdf&id_tenant=1&id_usuario_incluiu=10',
    p_http_method => 'POST',
    p_body_blob   => :P10_INVOICE_BLOB
  );

  -- l_response contem JSON com invoice_import e pending_fields.
end;
/
```

Depois de receber o JSON, grave em staging ou APEX Collection para revisao antes de inserir em `IMP_INVOICE` e `IMP_INVOICE_ITEM`.

## Variaveis de ambiente

- `API_KEY`: se definida, exige header `X-API-Key`.
- `OPENAI_API_KEY`: chave da OpenAI usada para transformar o texto extraido em JSON.
- `OPENAI_MODEL`: modelo usado na analise da invoice. Padrao: `gpt-4.1-mini`.
- `PDFBOX_JAR`: caminho do `pdfbox-app.jar`.
- `JAVA_BIN`: binario Java. Padrao: `java`.
- `MAX_UPLOAD_MB`: tamanho maximo do PDF. Padrao: `25`.
- `PDFBOX_TIMEOUT_SECONDS`: timeout de extracao. Padrao: `60`.
