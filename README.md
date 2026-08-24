# Preços de Imóveis - Coimbra

Projeto de ciência de dados: análise de preços de imóveis por m² em Coimbra,
deteção de anúncios sub/sobrevalorizados face à zona, cruzando dados de
scraping (Imovirtual/Idealista) com dados socioeconómicos do INE/Pordata.

## Estrutura
- `data/raw/` - HTML e CSVs brutos do scraping
- `data/external/` - dados do INE/Pordata
- `data/processed/` - dataset limpo, pronto a modelar
- `src/scraping/` - scrapers
- `src/features/` - geocoding, joins, engenharia de features
- `src/models/` - treino e avaliação
- `notebooks/` - EDA e protótipos
- `app/` - dashboard Streamlit
- `outputs/` - figuras, modelo treinado, relatório

## Como correr o scraper

```
pip install -r requirements.txt
python src/scraping/imovirtual_scraper.py
```

Escreve `data/raw/imovirtual_anuncios.csv` (35 colunas, uma linha por anuncio)
mais um CSV por pesquisa.

O scraper le o JSON `__NEXT_DATA__` que o Imovirtual (Next.js) embute em cada
pagina de resultados, em vez de raspar o HTML renderizado. Isso da acesso ao
`pagination.totalPages` (paginacao exacta), ao `id` estavel de cada anuncio
(deduplicacao fiavel) e a campos que o HTML nao expoe: bairro, data da 1a
publicacao, agencia, preco/m2 calculado pelo site.

Opcoes:

```
python src/scraping/imovirtual_scraper.py --pesquisa coimbra_concelho
python src/scraping/imovirtual_scraper.py --offline
```

`--pesquisa` escolhe a zona (repetivel); `coimbra_concelho` cobre as 18
freguesias numa so pesquisa. `--offline` reprocessa o HTML ja guardado em
`data/raw/` sem fazer um unico pedido — util para validar alteracoes ao parser.
