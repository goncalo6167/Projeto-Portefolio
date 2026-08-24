"""
Scraper do Imovirtual para anúncios de habitação em Coimbra.

O Imovirtual é uma aplicação Next.js: cada página de resultados embute um
<script id="__NEXT_DATA__"> com o JSON exacto que alimenta o React. Em vez de
raspar o HTML renderizado (frágil, depende de classes css-xxxxx que mudam a
cada deploy), lemos esse JSON directamente.

Vantagens face à abordagem por seletores CSS:
  - `pagination.totalPages` diz quantas páginas existem  -> fim da paginação às cegas
  - `id` numérico estável por anúncio                    -> deduplicação fiável
  - `totalPrice`, `areaInSquareMeters` já são numéricos   -> zero parsing de "265 000 €"
  - `pricePerSquareMeter` vem calculado pelo próprio site -> controlo cruzado
  - `reverseGeocoding` dá distrito/concelho/freguesia/bairro com IDs estáveis
  - `createdAtFirst` dá a data real da 1ª publicação      -> tempo em mercado

COMO USAR:
    python -m src.scraping.imovirtual_listagens              # 5 freguesias x 2 tipos
    python -m src.scraping.imovirtual_listagens --pesquisa moradia_coimbra_centro
    python -m src.scraping.imovirtual_listagens --offline    # reprocessa o HTML em disco

O modo --offline não faz um único pedido: reprocessa o HTML já guardado em
data/raw/html/. Serve para validar alterações ao parser sem voltar a incomodar
o site.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

import pandas as pd
import requests

from src.config import FREGUESIAS, HTML, INTERIM

# --- Configuração ---------------------------------------------------------

BASE = "https://www.imovirtual.com/pt/resultados/comprar"

# O Imovirtual separa apartamentos de moradias em pesquisas distintas. Ambos
# entram no âmbito; o campo `estate` do JSON diz depois qual é qual por anúncio.
TIPOS = ("apartamento", "moradia")

PESQUISAS = {
    f"{tipo}_{nome}": f"{BASE}/{tipo}/coimbra/coimbra/{slug}"
    for tipo in TIPOS
    for nome, slug in FREGUESIAS.items()
}

PESQUISAS_POR_OMISSAO = list(PESQUISAS)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9",
}


LIMITE_PAGINAS = 100           # travão de segurança, nunca deve ser atingido
PAUSA_MIN, PAUSA_MAX = 2, 5    # segundos entre pedidos

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# O Imovirtual conta divisões (sala incluída); a tipologia portuguesa conta
# quartos. T3 = 4 divisões. "MORE" é o balde do site para 9+ divisões.
ROOMS_PARA_TIPOLOGIA = {
    "ONE": "T0", "TWO": "T1", "THREE": "T2", "FOUR": "T3", "FIVE": "T4",
    "SIX": "T5", "SEVEN": "T6", "EIGHT": "T7", "NINE": "T8", "TEN": "T9",
    "MORE": "T9+",
}

FLOOR_PARA_NUMERO = {
    "CELLAR": -1, "GROUND": 0, "FIRST": 1, "SECOND": 2, "THIRD": 3,
    "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8,
    "NINTH": 9, "TENTH": 10,
}

# Não é habitação, seja qual for a categoria em que foi listado.
PADRAO_NAO_HABITACAO = re.compile(
    r"\b(?:pr[ée]dio|terreno|lote|armaz[ée]m|loja|escrit[óo]rio|"
    r"garagem\s+para\s+venda)\b",
    re.IGNORECASE,
)
# Só é contraditório se o anúncio estiver listado como apartamento.
PADRAO_MORADIA = re.compile(r"\b(?:moradia|vivenda|quintinha)\b", re.IGNORECASE)
PADRAO_ARRENDAMENTO = re.compile(r"\b(?:arrendar|arrendamento|aluguer)\b", re.IGNORECASE)

# O site usa "1999-02-29" como sentinela de data desconhecida. Nem sequer é uma
# data válida — 1999 não foi bissexto. Se passasse em bruto, qualquer cálculo de
# tempo em mercado dava ~27 anos para 38 anúncios.
DATA_SENTINELA = "1999-02-29"


# --- Leitura do JSON embutido ---------------------------------------------


def extrair_next_data(html: str) -> dict:
    """Devolve o payload __NEXT_DATA__ de uma página de resultados."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError(
            "__NEXT_DATA__ não encontrado. O site pode ter mudado de framework, "
            "ou a resposta foi uma página de bloqueio/captcha."
        )
    return json.loads(match.group(1))


def extrair_search_ads(html: str) -> dict:
    """Devolve o nó searchAds (items + pagination) de uma página."""
    dados = extrair_next_data(html)
    try:
        return dados["props"]["pageProps"]["data"]["searchAds"]
    except KeyError as e:
        raise ValueError(f"Estrutura inesperada no __NEXT_DATA__: falta {e}") from e


# --- Normalização de um anúncio -------------------------------------------


def _valor(dinheiro: dict | None) -> float | None:
    return dinheiro.get("value") if isinstance(dinheiro, dict) else None


def _data(valor: str | None) -> str | None:
    """Devolve a data, ou None se for a sentinela de 'desconhecida'."""
    if not valor or valor.startswith(DATA_SENTINELA):
        return None
    return valor


def _localizacao(item: dict) -> dict:
    """Achata a hierarquia distrito > concelho > freguesia > bairro."""
    niveis = {}
    locais = (
        item.get("location", {})
        .get("reverseGeocoding", {})
        .get("locations", [])
    )
    traducao = {
        "district": "distrito",
        "council": "concelho",
        "parish": "freguesia",
        "neighborhood": "bairro",
    }
    for local in locais:
        chave = traducao.get(local.get("locationLevel"))
        if chave:
            niveis[chave] = local.get("name")
            niveis[f"{chave}_id"] = local.get("id")
    return niveis


def normalizar_anuncio(item: dict, pesquisa: str) -> dict:
    """Converte um item do JSON no registo achatado que vai para o CSV."""
    area = item.get("areaInSquareMeters")
    preco = _valor(item.get("totalPrice"))
    agencia = item.get("agency") or {}
    dono = item.get("advertOwner") or {}

    registo = {
        "ad_id": item["id"],
        "slug": item["slug"],
        "url": f"https://www.imovirtual.com/pt/anuncio/{item['slug']}",
        "titulo": item.get("title"),
        "pesquisa": pesquisa,

        "preco_eur": preco,
        "preco_oculto": bool(item.get("hidePrice")),
        "area_m2": area,
        # Calculamos nós; `preco_m2_site` fica ao lado como controlo cruzado.
        "preco_m2": round(preco / area, 2) if preco and area else None,
        "preco_m2_site": _valor(item.get("pricePerSquareMeter")),

        "tipologia": ROOMS_PARA_TIPOLOGIA.get(item.get("roomsNumber")),
        "divisoes_raw": item.get("roomsNumber"),
        "piso": FLOOR_PARA_NUMERO.get(item.get("floorNumber")),
        "piso_raw": item.get("floorNumber"),

        "tipo_imovel": item.get("estate"),
        "transacao": item.get("transaction"),

        # dateCreated é a data da última republicação (o site refresca-a);
        # createdAtFirst é a 1ª publicação real -> é esta que dá tempo em mercado.
        "data_publicacao": _data(item.get("createdAtFirst")),
        "data_republicacao": _data(item.get("dateCreated")),

        "agencia": agencia.get("name") or dono.get("name") or None,
        "agencia_id": agencia.get("id"),
        "particular": bool(item.get("isPrivateOwner")),
        "promovido": bool(item.get("isPromoted")),
        "origem": item.get("source"),

        "n_fotos": item.get("totalPossibleImages"),
        "tags": "|".join(t["value"] for t in (item.get("tags") or [])) or None,
    }
    registo.update(_localizacao(item))
    return registo


def marcar_suspeito(df: pd.DataFrame) -> pd.DataFrame:
    """
    Marca anúncios cujo título contradiz a categoria em que foram listados.

    O `estate` do JSON separa bem apartamentos (FLAT) de moradias (HOUSE) —
    as pesquisas de moradia devolveram HOUSE em 246 de 246. O que o `estate`
    NÃO apanha é o ruído dentro de cada categoria: prédios inteiros, terrenos
    e armazéns aparecem listados como FLAT porque foi assim que o anunciante
    os categorizou, e o site limita-se a propagar o erro. Verificámos um a um:
    "Terreno para construção" e "Prédio com 8,7% Yield" vêm ambos como FLAT.

    Daí a marcação ser feita contra o título, e depender da categoria:
      - prédio/terreno/lote/armazém/loja não são habitação em nenhuma das duas;
      - "moradia" só é contraditório num anúncio listado como apartamento.

    Marcamos em vez de apagar: quem analisa decide, e fica registado quanto
    ruído tinha a fonte.
    """
    titulo = df["titulo"].fillna("")
    e_apartamento = df["tipo_imovel"] == "FLAT"

    df["suspeito_tipo_errado"] = (
        titulo.str.contains(PADRAO_NAO_HABITACAO)
        # Um T9+ com área grande listado como apartamento é quase sempre um
        # prédio inteiro; numa moradia é apenas uma moradia grande.
        | (e_apartamento & (df["tipologia"] == "T9+") & (df["area_m2"] > 250))
        | (e_apartamento & titulo.str.contains(PADRAO_MORADIA))
    )
    df["suspeito_arrendamento"] = titulo.str.contains(PADRAO_ARRENDAMENTO)
    return df


# --- Recolha ---------------------------------------------------------------


def caminho_html(pesquisa: str, pagina: int) -> Path:
    return HTML / f"{pesquisa}_pagina_{pagina}.html"


def buscar_pagina(base_url: str, pagina: int, pesquisa: str) -> str:
    """Descarrega uma página de resultados e guarda uma cópia local."""
    resp = requests.get(
        base_url, params={"page": pagina}, headers=HEADERS, timeout=20
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    caminho_html(pesquisa, pagina).write_text(resp.text, encoding="utf-8")
    return resp.text


def scrape_pesquisa(pesquisa: str, base_url: str, offline: bool = False) -> pd.DataFrame:
    """
    Percorre as páginas de uma pesquisa, guiada por `pagination.totalPages`.

    Quando se pede uma página acima da última, o Imovirtual devolve a última
    página outra vez — cheia. Uma heurística baseada no nº de anúncios por
    página nunca detecta isso. Por isso paramos por duas vias explícitas:
    o `totalPages` declarado, e a verificação de que o `currentPage` devolvido
    é mesmo o que pedimos.
    """
    anuncios: dict[int, dict] = {}   # ad_id -> registo, deduplica à cabeça
    total_paginas = None
    total_itens = None
    pagina = 1

    while pagina <= LIMITE_PAGINAS:
        if offline:
            caminho = caminho_html(pesquisa, pagina)
            if not caminho.exists():
                break
            html = caminho.read_text(encoding="utf-8")
        else:
            print(f"[{pesquisa}] página {pagina}"
                  + (f"/{total_paginas}" if total_paginas else ""))
            try:
                html = buscar_pagina(base_url, pagina, pesquisa)
            except requests.RequestException as e:
                print(f"  ! falhou a página {pagina}: {e}")
                break

        try:
            search_ads = extrair_search_ads(html)
        except ValueError as e:
            print(f"  ! {pesquisa} página {pagina}: {e}")
            break

        paginacao = search_ads.get("pagination", {})
        total_paginas = paginacao.get("totalPages")
        total_itens = paginacao.get("totalItems")
        pagina_devolvida = paginacao.get("currentPage")

        # O site devolveu outra página que não a pedida -> passámos do fim.
        if pagina_devolvida != pagina:
            print(f"  pedimos a página {pagina}, o site devolveu a "
                  f"{pagina_devolvida} -> fim dos resultados.")
            break

        # Pesquisa sem resultados. Tem de ser testado explicitamente: com
        # `totalPages == 0`, um teste por veracidade trata o zero como falso e
        # o ciclo corre até ao limite de segurança a descarregar páginas vazias.
        if not search_ads.get("items"):
            print(f"  sem anúncios nesta zona -> nada a recolher.")
            break

        novos = 0
        for item in search_ads.get("items", []):
            if item["id"] not in anuncios:
                anuncios[item["id"]] = normalizar_anuncio(item, pesquisa)
                novos += 1

        if not offline:
            print(f"  -> {len(search_ads.get('items', []))} anúncios "
                  f"({novos} novos, {len(anuncios)} acumulados)")

        if total_paginas is not None and pagina >= total_paginas:
            break

        pagina += 1
        if not offline:
            time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))

    df = pd.DataFrame(list(anuncios.values()))
    if not df.empty:
        df = marcar_suspeito(df)

    print(f"[{pesquisa}] {len(df)} anúncios únicos em "
          f"{total_paginas} páginas (o site declara {total_itens})")
    if total_itens and len(df) > total_itens:
        # Normal: o site injeta anúncios promovidos de zonas vizinhas que não
        # entram na contagem oficial da pesquisa.
        print(f"  (+{len(df) - total_itens} face ao declarado — anúncios "
              f"promovidos de fora da zona)")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pesquisa", action="append", choices=sorted(PESQUISAS),
        help="pesquisa a correr (repetível). Por omissão, as 5 freguesias.",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="reprocessa o HTML já guardado em data/raw/, sem fazer pedidos.",
    )
    parser.add_argument(
        "--saida", default=None,
        help="nome do CSV combinado (por omissão anuncios_listagem.csv).",
    )
    args = parser.parse_args()

    HTML.mkdir(parents=True, exist_ok=True)
    escolhidas = args.pesquisa or PESQUISAS_POR_OMISSAO

    if args.offline:
        print("Modo offline: a reprocessar o HTML em disco, sem pedidos.\n")

    dfs = []
    for pesquisa in escolhidas:
        df = scrape_pesquisa(pesquisa, PESQUISAS[pesquisa], offline=args.offline)
        if df.empty:
            print(f"[{pesquisa}] nada extraído — confirma o URL.\n")
            continue
        dfs.append(df)
        print()

    if not dfs:
        print("Nada foi extraído em nenhuma pesquisa.")
        return

    combinado = pd.concat(dfs, ignore_index=True)
    antes = len(combinado)
    # Um anúncio de fronteira pode surgir em mais do que uma pesquisa, e os
    # promovidos aparecem em zonas vizinhas. Dedup final por ad_id.
    combinado = combinado.drop_duplicates(subset="ad_id", keep="first")

    INTERIM.mkdir(parents=True, exist_ok=True)
    saida = INTERIM / (args.saida or "anuncios_listagem.csv")
    combinado.to_csv(saida, index=False, encoding="utf-8")

    print("=" * 64)
    print(f"{saida.name}: {len(combinado)} anúncios únicos "
          f"({antes - len(combinado)} repetidos entre pesquisas)")
    print(f"  com preço e área ......... {combinado[['preco_eur', 'area_m2']].notna().all(axis=1).sum()}")
    print(f"  possíveis tipo errado ..... {combinado['suspeito_tipo_errado'].sum()}")
    print(f"  possíveis arrendamentos .. {combinado['suspeito_arrendamento'].sum()}")
    print(f"  bairros distintos ........ {combinado['bairro'].nunique()}")


if __name__ == "__main__":
    main()
