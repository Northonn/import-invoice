# PDF Invoice API

API Python para receber invoices em PDF, extrair texto com Apache PDFBox e devolver JSON para consumo pelo Oracle APEX.

O PDFBox nao e uma API HTTP pronta; ele e uma biblioteca/ferramenta Java. Este projeto publica uma API HTTP em FastAPI que chama o `pdfbox-app.jar` por linha de comando.

## Endpoints

- `GET /health`: verifica se a API esta no ar e se o JAR do PDFBox existe.
- `POST /v1/pdf/extract-text`: recebe PDF em `multipart/form-data`, campo `file`.
- `POST /v1/pdf/extract-text/raw`: recebe o corpo bruto com `Content-Type: application/pdf`. Este endpoint costuma ser mais simples para enviar BLOB do Oracle APEX.

Parametros opcionais de query:

- `start_page`: primeira pagina, base 1.
- `end_page`: ultima pagina, base 1.
- `password`: senha do PDF, se houver.
- `sort`: ordena texto por posicao antes de escrever. Padrao: `true`.
- `rotation_magic`: tenta corrigir texto rotacionado/inclinado. Padrao: `false`.

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

## Publicacao gratis para teste no Render

O projeto inclui `render.yaml` para criar um Web Service gratuito no Render usando Docker.

Passo a passo:

1. Suba esta pasta para um repositorio GitHub.
2. Crie uma conta em https://render.com.
3. No Dashboard, escolha `New` > `Blueprint`.
4. Conecte o repositorio GitHub.
5. Se o repositorio tiver este projeto em uma subpasta, informe o caminho do Blueprint:

```text
outputs/pdf-invoice-api/render.yaml
```

6. Apos publicar, teste:

```bash
curl https://SEU-SERVICO.onrender.com/health
```

O Render gera automaticamente a variavel `API_KEY`. Veja o valor em `Environment` no dashboard e use no header `X-API-Key`.

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
- `PDFBOX_JAR`: caminho do `pdfbox-app.jar`.
- `JAVA_BIN`: binario Java. Padrao: `java`.
- `MAX_UPLOAD_MB`: tamanho maximo do PDF. Padrao: `25`.
- `PDFBOX_TIMEOUT_SECONDS`: timeout de extracao. Padrao: `60`.
