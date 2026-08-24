# Preços de habitação em Coimbra

Análise do preço por m² no núcleo urbano de Coimbra, com o objetivo de
identificar anúncios sub e sobrevalorizados face à sua zona. A referência é
construída a partir do próprio mercado — bairro, tipologia, área, idade do
edifício e distância aos polos de atracção da cidade.

**Estado:** recolha e enriquecimento concluídos (1548 anúncios). Limpeza,
modelação e dashboard por fazer.

## Dados

| | |
|---|---|
| Fonte | Imovirtual |
| Âmbito | 5 freguesias do núcleo urbano de Coimbra, apartamentos e moradias, venda |
| Volume | 1548 anúncios, 23 bairros |
| Coordenadas | 1530 (98,8%), das quais 787 exactas |

### Porquê estas 5 freguesias

O concelho de Coimbra tem 18 freguesias. Uma recolha exploratória às 8
periurbanas devolveu **32 anúncios no total**, com Souselas e Botão a zero —
fora do núcleo urbano o mercado de habitação em altura é residual. Um modelo
de preço por m² assente em células de 2 a 8 observações não seria defensável.
As 5 escolhidas concentram a procura (universidade, hospitais, serviços) e têm
volume por bairro.

## Como funciona a recolha

O Imovirtual é uma aplicação Next.js: cada página embute um
`<script id="__NEXT_DATA__">` com o JSON que alimenta o React. O scraper lê
esse JSON em vez de raspar o HTML renderizado.

Isso dá acesso a coisas que os seletores CSS não dão:

- `pagination.totalPages` — fim da paginação às cegas
- `id` estável por anúncio — deduplicação fiável
- `totalPrice` e `areaInSquareMeters` já numéricos — zero parsing de `"265 000 €"`
- `reverseGeocoding` — distrito/concelho/freguesia/**bairro** com IDs estáveis
- `createdAtFirst` — data da 1ª publicação, logo tempo em mercado

As coordenadas não estão na listagem, só na página de cada anúncio. Daí a
recolha ter duas fases. A segunda usa uma cache incremental: pode ser
interrompida e retomada sem repetir pedidos.

## Estrutura

```
data/
├── raw/                    dados como o site os devolveu
│   ├── html/               páginas de listagem (não versionado)
│   └── detalhes_cache.jsonl
├── interim/                parseado, ainda por limpar
└── processed/              limpo, pronto a modelar
src/
├── config.py               âmbito e caminhos, dono único
├── scraping/
├── features/
└── models/
notebooks/
outputs/  figuras/ modelos/
```

## Como correr

```
pip install -r requirements.txt
```

Os módulos correm com `python -m` a partir da raiz do projeto:

```
python -m src.scraping.imovirtual_listagens
```

```
python -m src.scraping.imovirtual_detalhes
```

```
python -m src.features.distancias
```

Pela ordem: listagens → `interim/anuncios_listagem.csv`; detalhes acrescenta
coordenadas e características → `interim/anuncios_detalhe.csv`; distâncias
acrescenta a distância aos polos → `interim/anuncios_completo.csv`.

A segunda fase demora ~1 hora (1 pedido por anúncio, com pausas). Pode ser
interrompida com Ctrl+C e retomada.

Para reprocessar sem fazer pedidos ao site:

```
python -m src.scraping.imovirtual_listagens --offline
```

## Notas sobre a qualidade dos dados

Coisas encontradas na fonte que condicionam a análise:

- **A categoria do imóvel não é de confiar.** Terrenos e prédios inteiros
  vêm categorizados como `FLAT`, porque foi assim que o anunciante os
  registou. Filtrar por `estate == "FLAT"` não resolve — foi preciso marcar
  por heurística sobre o título (coluna `suspeito_tipo_errado`, 118 casos).
- **`1999-02-29` é o sentinela de data desconhecida.** Não é sequer uma data
  válida — 1999 não foi bissexto. Sem tratamento, dava ~27 anos em mercado a
  38 anúncios.
- **Nem todas as coordenadas são exactas.** O site difunde parte delas num
  raio de 100 m. A coluna `raio_precisao_m` regista quais, e
  `distancia_exacta` propaga isso para as distâncias.
- **18 anúncios devolveram HTTP 410** entre a recolha da listagem e a das
  páginas de detalhe — foram vendidos ou retirados no intervalo. Ficam sem
  coordenadas.

## Sobre os polos de referência

As distâncias são medidas a 3 pontos: Universidade (núcleo histórico), Solum
(centro moderno) e HUC/Celas (cluster de saúde). A escolha foi feita por
sinal e por independência entre features — a Baixa ficou de fora por estar a
400 m da Universidade, com correlação de 0,98 entre as duas distâncias.

Dados socioeconómicos do INE foram considerados e descartados: são publicados
ao nível da freguesia, e com apenas 5 freguesias no âmbito qualquer indicador
teria 5 valores distintos para 1548 anúncios — informação que a coluna
`bairro` (23 níveis, 21,7% da variação do preço, contra 13,2% da freguesia)
já contém de forma mais fina.

## Por fazer

- [ ] Camada de limpeza → `data/processed/`
- [ ] EDA
- [ ] Modelo de preço e análise de resíduos
- [ ] Dashboard Streamlit
