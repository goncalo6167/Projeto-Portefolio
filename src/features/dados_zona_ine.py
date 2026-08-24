import requests
import pandas as pd
import time
import os

# Nomes exatos confirmados na base de dados da geoapi.pt
FREGUESIAS_GEOAPI = {
    "santo_antonio_olivais": "Santo António dos Olivais",
    "eiras_sao_paulo_frades": "União das freguesias de Eiras e São Paulo de Frades",
    "coimbra_centro": "União das freguesias de Coimbra (Sé Nova, Santa Cruz, Almedina e São Bartolomeu)",
    "santa_clara_castelo_viegas": "União das freguesias de Santa Clara e Castelo Viegas",
    "sao_martinho_bispo": "União das freguesias de São Martinho do Bispo e Ribeira de Frades",
}

MUNICIPIO = "coimbra"

def buscar_dados_com_retry(nome_freguesia: str, retries=3, backoff=10):
    """
    Faz o pedido à API com um sistema de re-tentativa caso receba erro 429.
    """
    url = f"https://json.geoapi.pt/municipio/{MUNICIPIO}/freguesia/{nome_freguesia}"
    
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            
            if resp.status_code == 200:
                return resp.json()
            
            if resp.status_code == 429:
                print(f"  ! Limite atingido (429). A aguardar {backoff} segundos para tentar de novo...")
                time.sleep(backoff)
                continue
            
            print(f"  Erro {resp.status_code} em '{nome_freguesia}'")
            return {}
            
        except Exception as e:
            print(f"  Erro de ligação: {e}")
            time.sleep(backoff)
            
    return {}

def processar_dados(data):
    if not data:
        return {}

    censos = data.get("censos2021", {})
    # Se não houver 2021, tenta 2011 como fallback
    if not censos:
        censos = data.get("censos2011", {})

    def para_float(valor):
        if valor is None: return None
        try: return float(valor)
        except: return None

    area_ha = para_float(data.get("areaha"))
    populacao = para_float(censos.get("N_INDIVIDUOS_RESIDENT"))
    
    area_km2 = area_ha / 100 if area_ha else None
    densidade = populacao / area_km2 if (populacao and area_km2) else None

    return {
        "area_km2": area_km2,
        "populacao_2021": populacao,
        "densidade_hab_km2": densidade,
        "n_alojamentos_2021": para_float(censos.get("N_ALOJAMENTOS")),
        "n_agregados_2021": para_float(censos.get("N_AGREGADOS")),
    }

def main():
    linhas = []
    
    # Criar pasta se não existir
    caminho_pasta = "data/external"
    if not os.path.exists(caminho_pasta):
        os.makedirs(caminho_pasta)

    for chave_interna, nome_geoapi in FREGUESIAS_GEOAPI.items():
        print(f"A buscar dados de '{nome_geoapi}'...")
        raw_data = buscar_dados_com_retry(nome_geoapi)
        dados = processar_dados(raw_data)
        
        dados["freguesia"] = chave_interna
        linhas.append(dados)
        
        # Espera 10 segundos entre pedidos normais para não stressar a API
        time.sleep(10)

    df = pd.DataFrame(linhas)
    
    # Reordenar para a freguesia ser a primeira coluna
    cols = ['freguesia'] + [c for c in df.columns if c != 'freguesia']
    df = df[cols]

    print("\nDados finais:")
    print(df)

    saida = os.path.join(caminho_pasta, "features_zona_ine.csv")
    df.to_csv(saida, index=False)
    print(f"\nSucesso! Guardado em: {saida}")

if __name__ == "__main__":
    main()