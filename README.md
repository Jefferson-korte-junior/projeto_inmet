# Clima no Brasil com os dados do INMET (2021 a 2024)

Projeto da disciplina Introdução a Big Data e Data Analytics (UTFPR). Esta é a Parte 1 do projeto: coleta, análise exploratória, limpeza e visualizações dos dados das estações meteorológicas automáticas do INMET.

## Dados

| Item | Valor |
|------|-------|
| Fonte principal | INMET, dados históricos das estações automáticas |
| Endereço | https://portal.inmet.gov.br/dadoshistoricos |
| Recorte | 2021 a 2024, todas as UFs, medições de hora em hora |
| Volume | 2.287 arquivos CSV, 20.029.680 linhas, 1.547 MB em CSV |
| Segunda fonte | IBGE (estados, municípios e malha das UFs) e NOAA (índice ONI do El Niño) |

## Estrutura

```
projeto_inmet/
  data/bronze/    zips originais, Parquet bruto por ano e UF e as fontes extras (não vai para o GitHub)
  data/silver/    dados limpos em Parquet por ano e UF (não vai para o GitHub)
  data/gold/      indicadores para os gráficos (não vai para o GitHub)
  data/referencia/ cópia dos arquivos do IBGE e do ONI, usada se o site não responder
  notebooks/      projeto_inmet.ipynb com coleta, EDA, limpeza e gráficos
  src/            coleta.py, o script que baixa e converte os dados
  reports/        ficha da proposta, relatório, dicionário de dados, metadados, log de limpeza e figuras
```

Os dados não ficam no repositório porque são grandes. O script de coleta baixa tudo de novo direto do INMET, do IBGE e da NOAA.

A API do IBGE costuma não responder para acessos de fora do Brasil, e o Google Colab roda em servidores fora do país. Por isso a pasta `data/referencia` guarda uma cópia pequena (2,6 MB) dos arquivos do IBGE e do ONI. O script sempre tenta baixar primeiro e só usa essa cópia se o download falhar.

## Como reproduzir

### No Google Colab (como o projeto foi feito)

1. Copie a pasta `projeto_inmet` inteira para o seu Google Drive, de preferência na raiz (`MyDrive/projeto_inmet`). Dentro de uma pasta da raiz também funciona, porque o notebook procura sozinho.
2. Abra `notebooks/projeto_inmet.ipynb` no Colab.
3. Use Ambiente de execução e depois Executar tudo, e autorize o acesso ao Drive.

Na primeira vez a coleta baixa uns 380 MB e demora alguns minutos. Nas próximas vezes o que já existe é reaproveitado.

### No computador

```
pip install pandas pyarrow requests matplotlib geopandas
python src/coleta.py
```

Depois abra o notebook a partir da pasta `notebooks`. Fora do Colab ele usa a própria pasta do projeto.

## O que cada etapa gera

| Etapa | Saída |
|-------|-------|
| Coleta | `data/bronze`, `reports/metadados_coleta_arquivos.csv`, `reports/metadados_coleta_resumo.csv`, `reports/dicionario_de_dados.csv` |
| Análise exploratória | seção 2 do notebook com o diagnóstico de qualidade e a lista de problemas |
| Limpeza | `data/silver` e `reports/log_limpeza.csv` |
| Indicadores | `data/gold` |
| Visualizações | `reports/figuras` |
| Relatório | `reports/relatorio_parte1.docx` |
