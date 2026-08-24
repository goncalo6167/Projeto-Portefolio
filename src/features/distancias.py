"""
Distâncias de cada anúncio aos polos de atracção de Coimbra.

Substitui o antigo `geocoding.py`. A parte de geocoding desapareceu: as
coordenadas passaram a vir do próprio Imovirtual (ver `scraping/imovirtual_
detalhes.py`), com 98,6% de cobertura, contra 61% e 379 m de erro mediano
que o Nominatim dava. O que sobrou — e continua a ser o mais importante — é
transformar essas coordenadas em distâncias que expliquem preço.

O ficheiro passou a chamar-se `distancias.py` porque é só isso que faz.

COMO USAR:
    python -m src.features.distancias
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import INTERIM

ENTRADA = INTERIM / "anuncios_detalhe.csv"
SAIDA = INTERIM / "anuncios_completo.csv"

RAIO_TERRA_KM = 6371.0

# Polos de atracção de Coimbra, escolhidos por sinal e por serem pouco
# redundantes entre si. Todas as coordenadas foram confirmadas contra fonte
# externa e cruzadas com o centróide dos anúncios do bairro correspondente.
#
# A versão anterior tinha dois erros graves: o HUC estava 2,8 km a sul do
# sítio real (fica em Celas, a norte) e o Pólo II 1,1 km a norte. Ambos os
# valores errados estavam em ~40.196 — números plausíveis, inventados. Um
# erro destes enviesa todas as distâncias de forma sistemática e silenciosa;
# nada dá erro, porque os valores continuam a parecer razoáveis.
#
# Duas saíram do conjunto:
#   - a Baixa, por ficar a 400 m da Universidade (correlação de 0,98 entre as
#     duas distâncias — a mesma feature duas vezes) e por ser a de menor sinal
#     (-0,16 contra -0,31 de Solum). Entrou Solum no seu lugar: é o centro
#     comercial moderno, ao passo que a Baixa é histórica e de stock antigo.
#   - o Pólo II, por ser um campus de engenharia sem relevância para a maior
#     parte da população da cidade. Custou perder o eixo mais independente do
#     conjunto (a sua correlação com o HUC era -0,01), mas uma feature tem de
#     significar alguma coisa para quem compra, não só correlacionar.
PONTOS_REFERENCIA = {
    # Núcleo histórico: Paço das Escolas. Fica a 400 m da Baixa, logo serve
    # de proxy para ambos.
    "dist_universidade_km": (40.2074, -8.4265),
    # Centro moderno, comércio e serviços.
    "dist_solum_km": (40.2038, -8.4027),
    # Cluster de saúde (Celas) — dos maiores empregadores da cidade.
    "dist_huc_km": (40.2209, -8.4130),
}


def haversine_km(
    lat: pd.Series, lon: pd.Series, lat_ref: float, lon_ref: float
) -> pd.Series:
    """
    Distância em km de cada ponto da série a um ponto fixo.

    Vectorizado: a versão anterior usava `df.apply(axis=1)`, que percorre as
    linhas uma a uma em Python — 1548 linhas x 4 pontos = ~6200 chamadas.
    """
    lat1, lon1, lat2, lon2 = map(np.radians, [lat, lon, lat_ref, lon_ref])
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return RAIO_TERRA_KM * 2 * np.arcsin(np.sqrt(a))


def calcular_distancias(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta uma coluna de distância (km) por ponto de referência."""
    if not {"lat", "lon"} <= set(df.columns):
        raise KeyError("faltam as colunas 'lat'/'lon' — corre primeiro o scraper de detalhes.")

    df = df.copy()
    for coluna, (lat_ref, lon_ref) in PONTOS_REFERENCIA.items():
        df[coluna] = haversine_km(df["lat"], df["lon"], lat_ref, lon_ref).round(3)

    colunas = list(PONTOS_REFERENCIA)
    df["dist_polo_mais_proximo_km"] = df[colunas].min(axis=1)

    # O Imovirtual difunde algumas coordenadas num raio (`raio_precisao_m`).
    # Esta coluna evita que a distância seja tratada como exacta quando não é.
    if "raio_precisao_m" in df.columns:
        df["distancia_exacta"] = df["raio_precisao_m"] == 0

    return df


def main() -> None:
    if not ENTRADA.exists():
        raise SystemExit(
            f"Falta {ENTRADA}. Corre primeiro:\n"
            f"  python -m src.scraping.imovirtual_detalhes --juntar"
        )

    df = calcular_distancias(pd.read_csv(ENTRADA))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAIDA, index=False, encoding="utf-8")

    primeira = next(iter(PONTOS_REFERENCIA))
    com_coords = df[primeira].notna().sum()
    print(f"{SAIDA.name}: {len(df)} anúncios, {df.shape[1]} colunas")
    print(f"  com distâncias ........... {com_coords} "
          f"({100 * com_coords / len(df):.1f}%)")
    if "distancia_exacta" in df:
        print(f"    de coordenada exacta ... {int(df['distancia_exacta'].sum())}")
    print()
    print(f"  {primeira} (km):")
    print(df[primeira].describe().round(2).to_string())


if __name__ == "__main__":
    main()
