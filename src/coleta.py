"""
Coleta dos dados históricos do INMET (estações automáticas) e das fontes extras.

Como usar:
    python src/coleta.py

Pode rodar de novo sem medo: o que já foi baixado ou convertido é pulado.
"""
import shutil
import time
import zipfile
import datetime
from pathlib import Path

import requests
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Recorte do projeto
ANOS = [2021, 2022, 2023, 2024]

URL_INMET = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"

# Fontes extras: IBGE (estados, municípios e malha das UFs para o mapa) e NOAA (índice ONI do El Niño)
FONTES_EXTRAS = {
    "ibge/estados.json":    "https://servicodados.ibge.gov.br/api/v1/localidades/estados",
    "ibge/municipios.json": "https://servicodados.ibge.gov.br/api/v1/localidades/municipios",
    "ibge/malha_uf.json":   "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF",
    "noaa/oni.txt":         "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (projeto academico de Big Data - UTFPR)"}

# Colunas dos CSVs de 2021 a 2024 (conferido: o cabeçalho é igual nos quatro anos)
COLUNAS_ORIGINAIS = [
    "Data", "Hora UTC",
    "PRECIPITAÇÃO TOTAL, HORÁRIO (mm)",
    "PRESSAO ATMOSFERICA AO NIVEL DA ESTACAO, HORARIA (mB)",
    "PRESSÃO ATMOSFERICA MAX.NA HORA ANT. (AUT) (mB)",
    "PRESSÃO ATMOSFERICA MIN. NA HORA ANT. (AUT) (mB)",
    "RADIACAO GLOBAL (Kj/m²)",
    "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
    "TEMPERATURA DO PONTO DE ORVALHO (°C)",
    "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)",
    "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)",
    "TEMPERATURA ORVALHO MAX. NA HORA ANT. (AUT) (°C)",
    "TEMPERATURA ORVALHO MIN. NA HORA ANT. (AUT) (°C)",
    "UMIDADE REL. MAX. NA HORA ANT. (AUT) (%)",
    "UMIDADE REL. MIN. NA HORA ANT. (AUT) (%)",
    "UMIDADE RELATIVA DO AR, HORARIA (%)",
    "VENTO, DIREÇÃO HORARIA (gr) (° (gr))",
    "VENTO, RAJADA MAXIMA (m/s)",
    "VENTO, VELOCIDADE HORARIA (m/s)",
]
MEDIDAS = COLUNAS_ORIGINAIS[2:]


def baixar(url, destino, tentativas=3):
    """Baixa um arquivo em blocos. Se ele já existe, pula. Se der erro, tenta de novo."""
    destino = Path(destino)
    if destino.exists() and destino.stat().st_size > 0:
        print(f"⏭️  {destino.name} já existe ({destino.stat().st_size / 1e6:,.1f} MB), pulando")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")

    for tentativa in range(1, tentativas + 1):
        try:
            t0 = time.time()
            # 15s para conectar e 120s para receber os dados
            with requests.get(url, headers=HEADERS, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                with open(parcial, "wb") as f:
                    for bloco in r.iter_content(chunk_size=8 * 1024 * 1024):
                        f.write(bloco)
            parcial.rename(destino)  # só vira o arquivo final se o download chegou até o fim
            print(f"✅ {destino.name} baixado em {time.time() - t0:.0f}s ({destino.stat().st_size / 1e6:,.1f} MB)")
            return
        except requests.RequestException as e:
            print(f"⚠️  Tentativa {tentativa}/{tentativas} falhou: {e}")
            if tentativa < tentativas:
                time.sleep(tentativa * 5)

    if parcial.exists():
        parcial.unlink()
    raise RuntimeError(f"Não consegui baixar {url}")


def testar_zip(caminho):
    """Confere se o zip não está corrompido."""
    with zipfile.ZipFile(caminho) as z:
        ruim = z.testzip()
    if ruim is not None:
        raise RuntimeError(f"{caminho.name} está corrompido ({ruim}). Apague o arquivo e rode de novo.")


def numero(texto):
    """Transforma '-15,789' em -15.789. Se não der, devolve None."""
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def ler_estacao(z, nome):
    """Lê o CSV de uma estação: 8 linhas com os dados da estação e depois as medições de hora em hora."""
    with z.open(nome) as f:
        topo = [f.readline().decode("latin-1").strip() for _ in range(8)]
    info = [linha.split(";")[1] if ";" in linha else "" for linha in topo]

    with z.open(nome) as f:
        df = pd.read_csv(f, sep=";", skiprows=8, encoding="latin-1", decimal=",",
                         dtype={"Data": "category", "Hora UTC": "category"})

    # o ';' no fim de cada linha cria uma coluna vazia sem nome
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    # se o layout vier diferente, renomeia pela posição para todos os anos ficarem iguais
    if list(df.columns) != COLUNAS_ORIGINAIS:
        print(f"⚠️  Layout diferente em {nome}, renomeando pela posição")
        df.columns = COLUNAS_ORIGINAIS[:len(df.columns)]

    # medições como float32 (se vier texto no meio dos números, vira nulo)
    for c in MEDIDAS:
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce")
        df[c] = df[c].astype("float32")

    df["regiao"] = info[0]
    df["uf"] = info[1]
    df["estacao"] = info[2]
    df["codigo_wmo"] = info[3]
    df["latitude"] = numero(info[4])
    df["longitude"] = numero(info[5])
    df["altitude"] = numero(info[6])
    for c in ["regiao", "estacao", "codigo_wmo"]:
        df[c] = df[c].astype("category")
    return df, info


def converter_ano(ano, zip_path, pasta_inmet, tmp_local):
    """Converte todos os CSVs de um ano para Parquet, particionado por ano e UF.
    Escreve primeiro numa pasta temporária e só copia para o destino no final."""
    tmp = Path(tmp_local) / f"inmet_{ano}"
    shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.time()

    partes, metadados = [], []
    with zipfile.ZipFile(zip_path) as z:
        csvs = [m for m in z.infolist() if m.filename.upper().endswith(".CSV")]
        for i, membro in enumerate(csvs, 1):
            df, info = ler_estacao(z, membro.filename)
            df["ano"] = ano
            partes.append(df)
            metadados.append({
                "ano": ano,
                "arquivo": membro.filename,
                "uf": info[1],
                "estacao": info[2],
                "codigo_wmo": info[3],
                "linhas": len(df),
                "colunas": len(COLUNAS_ORIGINAIS),
                "mb_csv": round(membro.file_size / 1e6, 3),
                "url": URL_INMET.format(ano=ano),
                "baixado_em": datetime.datetime.fromtimestamp(Path(zip_path).stat().st_mtime).isoformat(timespec="seconds"),
            })
            if i % 100 == 0:
                print(f"   {ano}: {i}/{len(csvs)} arquivos lidos")

    df_ano = pd.concat(partes, ignore_index=True)
    for c in ["Data", "Hora UTC", "regiao", "estacao", "codigo_wmo"]:
        df_ano[c] = df_ano[c].astype("category")  # o concat perde o tipo category quando as categorias são diferentes
    pq.write_to_dataset(pa.Table.from_pandas(df_ano, preserve_index=False),
                        root_path=str(tmp), partition_cols=["ano", "uf"],
                        compression="snappy", existing_data_behavior="overwrite_or_ignore")
    del df_ano, partes

    destino = Path(pasta_inmet) / f"ano={ano}"
    shutil.rmtree(destino, ignore_errors=True)
    shutil.copytree(tmp / f"ano={ano}", destino)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"✅ {ano}: {len(csvs)} arquivos convertidos para Parquet em {time.time() - t0:.0f}s")
    return pd.DataFrame(metadados)


def coletar(base, anos=ANOS, tmp_local=None):
    """Baixa os zips do INMET, converte para Parquet (Bronze) e baixa as fontes extras.
    Devolve a tabela de metadados da coleta."""
    base = Path(base)
    pasta_zip = base / "data" / "bronze" / "zip"
    pasta_inmet = base / "data" / "bronze" / "inmet"
    pasta_meta = base / "data" / "bronze" / "metadados"
    tmp_local = Path(tmp_local) if tmp_local else base / "data" / "_tmp"
    for p in [pasta_zip, pasta_inmet, pasta_meta, tmp_local]:
        p.mkdir(parents=True, exist_ok=True)

    for ano in anos:
        zip_path = pasta_zip / f"{ano}.zip"
        baixar(URL_INMET.format(ano=ano), zip_path)
        testar_zip(zip_path)

        meta_csv = pasta_meta / f"metadados_{ano}.csv"
        if (pasta_inmet / f"ano={ano}").exists() and meta_csv.exists():
            print(f"⏭️  {ano} já está em Parquet, pulando a conversão")
        else:
            converter_ano(ano, zip_path, pasta_inmet, tmp_local).to_csv(meta_csv, index=False)

    for nome, url in FONTES_EXTRAS.items():
        destino = base / "data" / "bronze" / nome
        try:
            baixar(url, destino)
        except RuntimeError:
            # o IBGE costuma não responder para quem está fora do Brasil (o Colab roda nos EUA)
            # nesse caso usa a cópia que fica no repositório, em data/referencia
            copia = base / "data" / "referencia" / nome
            if not copia.exists():
                raise
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(copia, destino)
            print(f"⚠️  Usei a cópia salva em data/referencia/{nome}")

    return pd.concat([pd.read_csv(pasta_meta / f"metadados_{ano}.csv") for ano in anos], ignore_index=True)


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parent.parent
    meta = coletar(raiz)
    print(f"\nTotal: {len(meta):,} arquivos, {meta['linhas'].sum():,} linhas, {meta['mb_csv'].sum():,.0f} MB em CSV")
