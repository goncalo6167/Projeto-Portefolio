"""
Enriquecimento dos anúncios com os dados da página de detalhe.

A página de listagem não traz coordenadas. A página de cada anúncio traz, no
mesmo `__NEXT_DATA__`, `location.coordinates` com latitude/longitude — e ainda
`build_year`, `energy_certificate`, `construction_status`, `bathrooms_num`,
que são features fortes para modelar preço e não existem na listagem.

Isto custa 1 pedido por anúncio (~1300 pedidos, ~1 hora com pausas educadas),
por isso o script é desenhado para ser interrompível:

  - cada anúncio é gravado em `data/raw/detalhes_cache.jsonl` mal chega;
  - ao arrancar, lê o que já lá está e salta esses anúncios;
  - um Ctrl+C ou uma falha de rede a meio não custa nada — basta voltar a correr.

Anúncios que já expiraram ou dão 404 ficam registados na cache como falhados,
para não serem repetidos em cada execução.

COMO USAR:
    python -m src.scraping.imovirtual_detalhes --limite 20   # testar
    python -m src.scraping.imovirtual_detalhes               # recolha completa
    python -m src.scraping.imovirtual_detalhes --juntar      # só juntar, sem pedidos
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

from src.config import INTERIM, RAW

ENTRADA = INTERIM / "anuncios_listagem.csv"
CACHE = RAW / "detalhes_cache.jsonl"
SAIDA = INTERIM / "anuncios_detalhe.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9",
}

PAUSA_MIN, PAUSA_MAX = 1.5, 3.5
TENTATIVAS = 3
ESPERA_BACKOFF = 20        # segundos, duplica a cada nova tentativa

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
_TAG_HTML_RE = re.compile(r"<[^>]+>")

# Chaves de `characteristics` que queremos como colunas. O site devolve muitas
# outras dependendo do anúncio; ficamo-nos por estas para o CSV não explodir.
CARACTERISTICAS = {
    "build_year": "ano_construcao",
    "energy_certificate": "certificado_energetico",
    "construction_status": "estado_conservacao",
    "building_type": "tipo_edificio",
    "building_floors_num": "n_pisos_edificio",
    "heating": "aquecimento",
    "windows_type": "tipo_janelas",
    "market": "mercado",
}


def limpar_html(texto: str | None) -> str | None:
    """Converte a descrição HTML do anúncio em texto simples."""
    if not texto:
        return None
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = _TAG_HTML_RE.sub("", texto)
    texto = (
        texto.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    return re.sub(r"\n{3,}", "\n\n", texto).strip() or None


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def extrair_detalhe(html: str, ad_id: int) -> dict:
    """Extrai da página de detalhe os campos que a listagem não dá."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("__NEXT_DATA__ não encontrado (bloqueio ou captcha?)")

    ad = json.loads(match.group(1))["props"]["pageProps"].get("ad")
    if not ad:
        raise ValueError("página sem objecto `ad` (anúncio removido?)")

    localizacao = ad.get("location") or {}
    coords = localizacao.get("coordinates") or {}
    mapa = localizacao.get("mapDetails") or {}
    alvo = ad.get("target") or {}

    registo = {
        "ad_id": ad_id,
        "ok": True,
        "lat": coords.get("latitude"),
        "lon": coords.get("longitude"),
        # 0 = coordenada exacta; 100 = o site difundiu o ponto num raio de 100 m.
        # Guardar isto é o que permite ser honesto sobre a precisão a jusante.
        "raio_precisao_m": mapa.get("radius"),
        "estado_anuncio": ad.get("status"),
        "data_modificacao": ad.get("modifiedAt"),
        "n_casas_banho": _numero((alvo.get("Bathrooms_num") or [None])[0]),
        "extras": "|".join(alvo.get("Extras_types") or []) or None,
        "seguranca": "|".join(alvo.get("Security_types") or []) or None,
        "descricao": limpar_html(ad.get("description")),
    }

    caracteristicas = {
        c["key"]: c.get("value") for c in (ad.get("characteristics") or [])
    }
    for chave_site, nome in CARACTERISTICAS.items():
        registo[nome] = caracteristicas.get(chave_site)

    registo["ano_construcao"] = _numero(registo["ano_construcao"])
    registo["n_pisos_edificio"] = _numero(registo["n_pisos_edificio"])
    return registo


# --- Cache incremental -----------------------------------------------------


def ler_cache() -> dict[int, dict]:
    """Carrega a cache. Linhas corrompidas (Ctrl+C a meio da escrita) são ignoradas."""
    if not CACHE.exists():
        return {}
    registos = {}
    with CACHE.open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                registo = json.loads(linha)
            except json.JSONDecodeError:
                continue
            registos[registo["ad_id"]] = registo
    return registos


def gravar_cache(registo: dict) -> None:
    """Acrescenta um registo à cache e força a escrita em disco."""
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registo, ensure_ascii=False) + "\n")
        f.flush()


# --- Recolha ---------------------------------------------------------------


def buscar_detalhe(url: str, ad_id: int) -> dict:
    """Vai buscar uma página de detalhe, com re-tentativas em erros transitórios."""
    espera = ESPERA_BACKOFF
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
        except requests.RequestException as e:
            if tentativa == TENTATIVAS:
                return {"ad_id": ad_id, "ok": False, "erro": f"rede: {e}"}
            time.sleep(espera)
            espera *= 2
            continue

        # 404/410: o anúncio já não existe. Não vale a pena repetir — fica
        # marcado como falhado permanente para não voltar a ser pedido.
        if resp.status_code in (404, 410):
            return {"ad_id": ad_id, "ok": False, "erro": f"http {resp.status_code}"}

        if resp.status_code in (429, 500, 502, 503, 504):
            if tentativa == TENTATIVAS:
                return {"ad_id": ad_id, "ok": False,
                        "erro": f"http {resp.status_code} após {TENTATIVAS} tentativas"}
            print(f"    http {resp.status_code}, a esperar {espera}s...")
            time.sleep(espera)
            espera *= 2
            continue

        resp.encoding = "utf-8"
        try:
            return extrair_detalhe(resp.text, ad_id)
        except (ValueError, KeyError) as e:
            return {"ad_id": ad_id, "ok": False, "erro": str(e)}

    return {"ad_id": ad_id, "ok": False, "erro": "tentativas esgotadas"}


def recolher(limite: int | None = None) -> None:
    if not ENTRADA.exists():
        raise SystemExit(
            f"Falta {ENTRADA.name}. Corre primeiro:\n"
            f"  python -m src.scraping.imovirtual_listagens"
        )

    anuncios = pd.read_csv(ENTRADA)[["ad_id", "url"]].drop_duplicates("ad_id")
    cache = ler_cache()

    pendentes = anuncios[~anuncios["ad_id"].isin(cache)]
    if limite:
        pendentes = pendentes.head(limite)

    ja_feitos = len(anuncios) - len(anuncios[~anuncios["ad_id"].isin(cache)])
    print(f"{len(anuncios)} anúncios | {ja_feitos} já em cache | "
          f"{len(pendentes)} a recolher agora")
    if len(pendentes):
        segundos = len(pendentes) * (PAUSA_MIN + PAUSA_MAX) / 2
        print(f"Estimativa: ~{segundos / 60:.0f} min. "
              f"Podes interromper com Ctrl+C — o progresso fica gravado.\n")

    falhas = 0
    for i, (_, linha) in enumerate(pendentes.iterrows(), start=1):
        registo = buscar_detalhe(linha["url"], int(linha["ad_id"]))
        gravar_cache(registo)

        if not registo.get("ok"):
            falhas += 1
            print(f"  [{i}/{len(pendentes)}] {linha['ad_id']} FALHOU: "
                  f"{registo.get('erro')}")
        elif i % 25 == 0 or i == len(pendentes):
            print(f"  [{i}/{len(pendentes)}] {i - falhas} ok, {falhas} falhados")

        if i < len(pendentes):
            time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))


# --- Junção ----------------------------------------------------------------


def juntar() -> None:
    """Junta a cache de detalhes ao CSV da listagem e escreve o dataset final."""
    cache = ler_cache()
    if not cache:
        raise SystemExit("Cache vazia. Corre a recolha primeiro.")

    anuncios = pd.read_csv(ENTRADA)
    detalhes = pd.DataFrame(list(cache.values()))

    bons = detalhes[detalhes["ok"] == True].drop(columns=["ok"], errors="ignore")  # noqa: E712
    maus = detalhes[detalhes["ok"] != True]  # noqa: E712

    juntos = anuncios.merge(bons, on="ad_id", how="left", validate="one_to_one")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    juntos.to_csv(SAIDA, index=False, encoding="utf-8")

    com_coords = juntos["lat"].notna().sum()
    print("=" * 64)
    print(f"{SAIDA}: {len(juntos)} anúncios, {juntos.shape[1]} colunas")
    print(f"  com coordenadas .......... {com_coords} "
          f"({100 * com_coords / len(juntos):.1f}%)")
    if com_coords:
        exactas = (juntos["raio_precisao_m"] == 0).sum()
        print(f"    coordenada exacta ...... {exactas}")
        print(f"    difundida (raio > 0) ... {com_coords - exactas}")
        print(f"  pontos distintos ......... "
              f"{juntos.dropna(subset=['lat']).groupby(['lat', 'lon']).ngroups}")
    print(f"  com ano de construção .... {juntos['ano_construcao'].notna().sum()}")
    print(f"  com cert. energético ..... {juntos['certificado_energetico'].notna().sum()}")
    if len(maus):
        print(f"  sem detalhe (falhados) ... {len(maus)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int, default=None,
                        help="recolher apenas N anúncios (para testar).")
    parser.add_argument("--juntar", action="store_true",
                        help="só juntar a cache existente, sem fazer pedidos.")
    args = parser.parse_args()

    if not args.juntar:
        try:
            recolher(limite=args.limite)
        except KeyboardInterrupt:
            print("\nInterrompido. O progresso está gravado — volta a correr "
                  "para continuar de onde ficou.")
            return
    juntar()


if __name__ == "__main__":
    main()
