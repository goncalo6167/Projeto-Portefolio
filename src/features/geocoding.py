"""
Geocoding dos anúncios + distância a pontos de referência em Coimbra.

pip install geopy pandas
"""

import time
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.extra.rate_limiter import RateLimiter

# --- Pontos de referência em Coimbra ---------------------------------------
PONTOS_REFERENCIA = {
    "dist_centro_km": (40.2111, -8.4291),        # Praça 8 de Maio / centro histórico
    "dist_universidade_km": (40.2076, -8.4246),   # Paço das Escolas / Universidade de Coimbra
    "dist_polo2_km": (40.1963, -8.4157),          # Pólo II (engenharias)
    "dist_chuc_km": (40.1962, -8.4218),           # Hospitais da Universidade de Coimbra
}


def geocode_dataset(df: pd.DataFrame, coluna_morada: str = "morada") -> pd.DataFrame:
    """Geocodifica cada morada única (evita pedir o mesmo endereço 2x)."""
    geolocator = Nominatim(user_agent="projeto-imoveis-coimbra")
    # RateLimiter respeita o limite de 1 pedido/segundo do Nominatim (obrigatório)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

    moradas_unicas = df[coluna_morada].dropna().unique()
    print(f"A geocodificar {len(moradas_unicas)} moradas únicas...")

    cache = {}
    for i, morada in enumerate(moradas_unicas):
        # adiciona ", Portugal" ajuda a precisão do Nominatim
        query = f"{morada}, Portugal"
        try:
            resultado = geocode(query)
            if resultado:
                cache[morada] = (resultado.latitude, resultado.longitude)
            else:
                cache[morada] = (None, None)
        except Exception as e:
            print(f"  Falhou '{morada}': {e}")
            cache[morada] = (None, None)

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(moradas_unicas)} feitas...")

    df["lat"] = df[coluna_morada].map(lambda m: cache.get(m, (None, None))[0])
    df["lon"] = df[coluna_morada].map(lambda m: cache.get(m, (None, None))[1])

    n_falhados = df["lat"].isna().sum()
    print(f"Geocoding concluído. {n_falhados} anúncios sem coordenadas ({n_falhados/len(df):.1%}).")

    return df


def calcular_distancias(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas de distância (km) a cada ponto de referência."""
    for nome_coluna, ponto_ref in PONTOS_REFERENCIA.items():
        df[nome_coluna] = df.apply(
            lambda row: (
                geodesic((row["lat"], row["lon"]), ponto_ref).km
                if pd.notna(row["lat"]) and pd.notna(row["lon"])
                else None
            ),
            axis=1,
        )
    return df


if __name__ == "__main__":
    df = pd.read_csv("data/raw/imovirtual_todas_freguesias_raw.csv")

    # limpeza mínima antes de geocodificar (poupa pedidos)
    df = df.drop_duplicates(subset="link")
    df = df.dropna(subset=["preco_eur", "area_m2"])

    df = geocode_dataset(df)
    df = calcular_distancias(df)

    saida = "data/raw/dataset_geocodificado_raw.csv"
    df.to_csv(saida, index=False)
    print(f"Guardado: {saida}")
