# Prompts de Analise de Invoices

Esta pasta contem prompts de referencia para calibrar a extracao de dados de invoices de importacao.

Arquivos:

- `01_raimko_marine.md`: invoice Raimko Marine, layout com `Invoice to`, `Customer Ref`, fabricante, pickup address e totais simples.
- `02_calisa_argentina.md`: factura de exportacion argentina, layout escaneado com CRT, Cod. Cliente, permiso de embarque e pesos em bloco auxiliar.
- `03_bobst.md`: commercial invoice Bobst, duas paginas, blocos `Bill-to` e `Ship-to`, itens tecnicos e banco na segunda pagina.
- `04_farm_frites.md`: invoice Farm Frites, alimentos congelados, lotes auxiliares, datas de producao/validade e totais por peso.
- `05_gosea_china.md`: commercial invoice bilingue chines/ingles, pedido de compra, proforma invoice, pesos unitarios e totais.
- `06_hungca_vietnam.md`: commercial invoice Vietnam, pescado congelado, contrato, B/L, container, tamanhos comerciais e valores FOB/CIF.
- `07_best_known_auto_parts.md`: invoice chinesa Best-Known Auto Parts, autopecas, muitos itens por PO, FOB Shanghai e HS codes consolidados.
- `08_fischer_air.md`: invoice Fischer Automaten, embarque aereo, itens com embalagem sem valor e preco por centena.
- `09_ruian_weichuang.md`: invoice chinesa Ruian Weichuang, reles/plungers, duas paginas, FOB Ningbo e NCM consolidado.
- `10_daihatsu_infinearth.md`: invoice Daihatsu Infinearth, pecas de motor, duas paginas, FCA Osaka e pedido do cliente no rodape.
- `00_consolidated_invoice_extraction.md`: prompt consolidado para unificar as regras de todos os layouts.

Objetivo:

Usar os prompts individuais para analisar cada familia de invoice e evoluir o prompt consolidado usado pela API para preencher o JSON definido em `app/invoice_schema.py`.
