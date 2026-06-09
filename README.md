# PDF Invoice API

API Python para receber invoices em PDF, extrair texto com Apache PDFBox e devolver JSON para consumo pelo Oracle APEX.

O PDFBox nao e uma API HTTP pronta; ele e uma biblioteca/ferramenta Java. Este projeto publica uma API HTTP em FastAPI que chama o `pdfbox-app.jar` por linha de comando.

## Endpoints

- `GET /health`: verifica se a API esta no ar e se o JAR do PDFBox existe.
- `POST /v1/pdf/extract-text`: recebe PDF em `multipart/form-data`, campo `file`.
- `POST /v1/pdf/extract-text/raw`: recebe o corpo bruto com `Content-Type: application/pdf`. Este endpoint costuma ser mais simples para enviar BLOB do Oracle APEX.
- `POST /v1/invoice/extract-and-parse`: recebe PDF em `multipart/form-data`, extrai texto e transforma em JSON de importacao usando OpenAI.
- `POST /v1/invoice/extract-and-parse/raw`: recebe PDF bruto, extrai texto e transforma em JSON de importacao usando OpenAI. Recomendado para APEX.
- `POST /v1/invoice/parse-pdf-openai`: recebe PDF em `multipart/form-data` e envia o PDF diretamente para a OpenAI analisar texto/imagem e transformar em JSON.
- `POST /v1/invoice/parse-pdf-openai/raw`: recebe PDF bruto e envia o PDF diretamente para a OpenAI analisar texto/imagem e transformar em JSON. Recomendado para PDF escaneado/imagem.

Parametros opcionais de query:

- `start_page`: primeira pagina, base 1.
- `end_page`: ultima pagina, base 1.
- `password`: senha do PDF, se houver.
- `sort`: ordena texto por posicao antes de escrever. Padrao: `true`.
- `rotation_magic`: tenta corrigir texto rotacionado/inclinado. Padrao: `false`.
- `enable_ocr`: permite OCR quando PDFBox/pdfplumber retornarem pouco texto. Padrao: `true`.
- `force_ocr`: ignora PDFBox/pdfplumber e tenta OCR diretamente. Padrao: `false`.
- `id_tenant`: ID do tenant vindo do sistema.
- `id_usuario_incluiu`: ID do usuario logado no sistema.
- `id_processoimportacao`: ID do processo de importacao, se ja existir.
- `include_extracted_text`: inclui o texto extraido dentro de `invoice_import.source.extracted_text`. Padrao: `false`.
- `openai_model`: modelo usado na analise da invoice. Se omitido, usa `OPENAI_MODEL`. Permitidos: `gpt-4.1-mini`, `gpt-4.1-mini-2025-04-14`, `gpt-5-mini`, `gpt-5-mini-2025-08-07`, `gpt-4o-mini`, `gpt-4o-mini-2024-07-18`.

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

Forcar OCR em PDF escaneado/imagem:

```bash
curl -X POST "http://localhost:8000/v1/pdf/extract-text?force_ocr=true" \
  -H "X-API-Key: troque-esta-chave" \
  -F "file=@invoice-escaneada.pdf;type=application/pdf"
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

Analisar PDF escaneado/imagem diretamente com OpenAI:

```bash
curl -X POST "http://localhost:8000/v1/invoice/parse-pdf-openai?id_tenant=1&id_usuario_incluiu=10&openai_model=gpt-4o-mini" \
  -H "X-API-Key: troque-esta-chave" \
  -F "file=@invoice-escaneada.pdf;type=application/pdf"
```

Analisar PDF bruto diretamente com OpenAI:

```bash
curl -X POST "http://localhost:8000/v1/invoice/parse-pdf-openai/raw?filename=invoice.pdf&id_tenant=1&id_usuario_incluiu=10&openai_model=gpt-4o-mini" \
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
    p_url         => 'https://seu-dominio.com/v1/pdf/extract-text/raw?filename=invoice.pdf',
    p_http_method => 'POST',
    p_body_blob   => :P10_INVOICE_BLOB
  );

  -- l_response contem JSON com o campo "text".
end;
/
```

Depois de extrair o texto, o proximo passo e criar uma camada de parser para identificar numero da invoice, exportador, importador, moeda, valores, incoterm, pesos, itens e NCM/HS Code quando existir.

## Variaveis de ambiente

- `API_KEY`: se definida, exige header `X-API-Key`.
- `OPENAI_API_KEY`: chave da OpenAI usada para transformar o texto extraido em JSON.
- `OPENAI_MODEL`: modelo usado na analise da invoice. Padrao: `gpt-4.1-mini`.
- `PDFBOX_JAR`: caminho do `pdfbox-app.jar`.
- `JAVA_BIN`: binario Java. Padrao: `java`.
- `MAX_UPLOAD_MB`: tamanho maximo do PDF. Padrao: `25`.
- `PDFBOX_TIMEOUT_SECONDS`: timeout de extracao. Padrao: `60`.
- `OCR_ENABLED`: habilita fallback por OCR. Padrao: `true`.
- `OCR_LANGUAGE`: idiomas do Tesseract. Padrao: `eng+por`.
- `OCR_DPI`: resolucao usada para renderizar paginas antes do OCR. Padrao: `150`.
- `OCR_MAX_PAGES`: numero maximo de paginas enviadas ao OCR. Padrao: `1`.
- `OCR_PAGE_TIMEOUT_SECONDS`: timeout por pagina no Tesseract. Padrao: `20`.
- `MIN_TEXT_CHARS_FOR_OCR`: minimo de caracteres para considerar que a extracao textual foi suficiente. Padrao: `80`.
