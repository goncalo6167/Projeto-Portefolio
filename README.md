# Preços de habitação em Coimbra

Análise do preço por m² no núcleo urbano de Coimbra, com o objetivo de
identificar anúncios sub e sobrevalorizados face ao que seria de esperar para
aquelas características. A referência é construída a partir do próprio
mercado — bairro, tipologia, área, idade do edifício e distância aos polos de
atracção da cidade.

**Estado:** recolha, limpeza e modelo concluídos. Dashboard por fazer.

| | |
|---|---|
| Fonte | Imovirtual |
| Âmbito | 5 freguesias do núcleo urbano de Coimbra, apartamentos e moradias, venda |
| Recolhidos | 1 548 anúncios |
| Depois da limpeza | **1 377** (89%), 23 bairros |
| Coordenadas | 1 360 (98,8%) |
| Modelo | HistGradientBoosting — **R² 0,75**, erro mediano de **7%** |

---

## O que o projeto faz

1. **Recolhe** anúncios do Imovirtual, lendo o JSON que o site usa internamente
2. **Enriquece** cada anúncio com as coordenadas e características da sua página
3. **Limpa** — remove o que não é habitação e corrige o que está mal registado
4. **Modela** o preço por m² e analisa os resíduos para encontrar desvios

O produto final não é o modelo. É a **lista de anúncios que se afastam do
padrão** — e a compreensão de quando essa lista é de confiança.

### Porquê estas 5 freguesias

O concelho de Coimbra tem 18 freguesias. Uma recolha exploratória às 8
periurbanas devolveu **32 anúncios no total**, com Souselas e Botão a zero:
fora do núcleo urbano o mercado de habitação em altura é residual. Um modelo
de preço por m² assente em células de 2 a 8 observações não seria defensável.

---

## Como está organizado

```
data/
├── raw/                    como o site devolveu
│   ├── html/               páginas de listagem (não versionado, 41 MB)
│   └── detalhes_cache.jsonl
├── interim/                parseado, ainda por limpar
└── processed/              limpo, pronto a modelar
src/
├── config.py               âmbito e caminhos
├── scraping/               os dois scrapers
├── features/               distâncias
└── models/
notebooks/
├── 01_eda.ipynb            o que está partido nestes dados?
├── 02_limpeza.ipynb        que regras aplicar, e porquê
└── 03_modelo.ipynb         modelo e análise de resíduos
outputs/  figuras/ modelos/
```

## Como correr

```
pip install -r requirements.txt
```

Os módulos correm com `python -m` a partir da raiz:

```
python -m src.scraping.imovirtual_listagens
```

```
python -m src.scraping.imovirtual_detalhes
```

```
python -m src.features.distancias
```

A segunda fase demora ~1 hora (um pedido por anúncio, com pausas). Pode ser
interrompida com Ctrl+C e retomada — o progresso fica gravado numa cache.

Para reprocessar sem tocar na rede:

```
python -m src.scraping.imovirtual_listagens --offline
```

---

## As dificuldades, e como foram resolvidas

Esta é a parte honesta do projeto. Quase nada correu à primeira.

### O scraper apanhava 46% de linhas repetidas

A primeira versão pedia sempre 20 páginas por zona. O problema: quando se pede
uma página que não existe, o Imovirtual devolve a última **outra vez, cheia** —
e uma regra do tipo "parar quando a página vier vazia" nunca dispara.

Resultado: 2 420 linhas para 1 302 anúncios reais.

**Solução:** cada página do site traz um bloco de dados em JSON
(`__NEXT_DATA__`) que diz quantas páginas existem e dá um número único a cada
anúncio. Passei a ler esse bloco em vez de interpretar o HTML. Os duplicados
desapareceram e os pedidos ao site caíram de 100 para 38.

### As coordenadas estavam erradas em 39% dos casos

A versão inicial obtinha a localização enviando o texto da morada a um serviço
gratuito. Falhava em 39% dos anúncios e, nos restantes, colocava 147 anúncios
diferentes exactamente no mesmo ponto.

Medi o erro: **379 metros de mediana**, com 39% dos anúncios a mais de 500 m do
sítio real. Numa cidade onde a distância ao centro anda nos 2 km, isso destrói
a variável.

**Solução:** a página de cada anúncio traz as coordenadas do próprio site.
Custa um pedido por anúncio, mas passou-se de 61% para **98,8% de cobertura**.
O site indica também se a coordenada é exacta ou foi difundida num raio —
coluna que guardei para saber com que precisão estou a trabalhar.

### As coordenadas de referência estavam inventadas

As distâncias eram calculadas a quatro pontos da cidade. Ao verificá-los, dois
estavam errados: o hospital a **2,8 km** do sítio real e o Pólo II a 1,1 km.
Ambos os valores errados começavam por `40.196` — números com aspecto
plausível, escolhidos sem confirmar.

Este tipo de erro nunca dá mensagem de erro: as distâncias continuam a parecer
razoáveis e o modelo treina na mesma.

**Solução:** confirmei cada ponto contra fonte externa e escolhi o conjunto
final medindo quais explicavam mais o preço sem se repetirem entre si. A Baixa
saiu porque fica a 400 m da Universidade — a correlação entre as duas
distâncias era 0,98, ou seja a mesma variável duas vezes.

### O site diz que terrenos e prédios são apartamentos

O campo que identifica o tipo de imóvel é preenchido pelo anunciante, e o site
limita-se a propagá-lo. Verifiquei: **1 301 dos 1 302 anúncios** vinham como
apartamento, incluindo "Terreno para construção" e "Prédio com 8,7% de yield".

Filtrar por esse campo não resolvia nada.

**Solução:** marcação por padrões no título, validada à mão. E validar era
indispensável — a primeira versão da regra tinha **13 falsos positivos** em
118, apanhando apartamentos legítimos porque o título dizia "em prédio com
elevador" ou "Lote 29" (o lote dentro do empreendimento, não um terreno).

### O mesmo anúncio com dois identificadores

O scraper removia duplicados pelo número do anúncio. Mas o site atribui **dois
números ao mesmo anúncio** — um normal e outro, com 14 dígitos, vindo dos
feeds de parceiros. Eram 47 anúncios contados a dobrar.

**Solução:** deduplicar pelo endereço do anúncio, que é único de verdade.

### Datas que não existem

38 anúncios tinham como data de publicação **29 de Fevereiro de 1999** — que
nem sequer é uma data válida, porque 1999 não foi ano bissexto. É o valor que
o site usa para "não sei". Sem tratamento, davam 27 anos de tempo em mercado.

### O modelo previa o preço a partir do preço

O alvo é `preço ÷ área`. Dar ao modelo o preço **e** a área é dar-lhe a
resposta: um teste com só essas duas colunas deu **R² de 0,96** sem o modelo
aprender nada sobre o mercado.

**Solução:** uma lista explícita das colunas que entram no modelo, em vez de
remover as que não devem entrar. Com uma lista, uma coluna nova fica de fora
por omissão; com remoções, entra sempre que alguém se esquece.

### Empreendimentos com dezenas de frações iguais

Há condomínios com 17 apartamentos T2 idênticos, ao mesmo preço. Numa divisão
aleatória entre treino e teste, 13 ficam de um lado e 4 do outro — e o modelo
"acerta" nos 4 porque decorou os 13. O resultado sairia melhor do que é, sem
nada dar erro.

**Solução:** dividir por grupo de empreendimento, não ao acaso.

### A análise de resíduos revelou falhas na limpeza

A parte mais interessante. Ao olhar para os anúncios que mais se afastavam da
previsão, o que apareceu não foram oportunidades — foram erros que a limpeza
não tinha apanhado. Cinco voltas ao ciclo:

| volta | o que apareceu |
|---|---|
| 1 | casas para recuperar que o padrão não apanhava (+51 anúncios) |
| 2 | frações vendidas em conjunto, disfarçadas de `T8 (T0+T3+T4)` |
| 3 | área desalinhada da tipologia — virou feature nova, **+0,019 de R²** |
| 4 | "venda conjunta de 2 moradias, uma ocupada", só visível na descrição |
| 5 | tipologias inflacionadas pelo formato `T3+1` |

A cada volta a contaminação ficou mais rara e mais subtil. Parei quando os
candidatos passaram a ser maioritariamente imóveis legítimos.

### O modelo é enviesado nas pontas

Sobrestima os imóveis baratos em cerca de 13% e subestima os caros. É
regressão à média, comportamento normal — mas com uma consequência prática: a
lista dos maiores desvios seria simplesmente a lista dos imóveis mais baratos.

**Solução:** medir o desvio face ao viés típico de cada faixa de preço, e
comparar cada imóvel dentro do seu segmento. Casas para recuperar comparam-se
com casas para recuperar, não com o mercado geral — valem 61% menos por m².

---

## Coisas que testei e não usei

Registadas porque saber o que **não** funciona também é resultado.

- **Dados do INE por freguesia.** Com apenas 5 freguesias, qualquer indicador
  teria 5 valores distintos para 1 548 anúncios — informação que a coluna
  `bairro` (23 níveis) já contém de forma mais fina.
- **Features extraídas do texto dos anúncios.** Treze indicadores (luxo, obra
  nova, vista, condomínio...) acrescentaram **+0,006 de R²**, dentro do desvio
  da validação cruzada. Isoladamente pareciam fortes, mas diziam o mesmo que a
  idade do edifício, que o modelo já tinha.
- **As características do imóvel** (elevador, garagem, ar condicionado):
  +0,003. São proxies da idade do edifício. Ficam no dataset por serem úteis
  como filtros, não por poder preditivo.
- **Transformação logarítmica do alvo.** Depois da limpeza a distribuição ficou
  simétrica (assimetria de 3,7 para −0,04) e o log só piorava.

---

## Limitações

- É preço **pedido**, não preço de venda. O modelo aprende o que os vendedores
  pedem, que não é o que os compradores pagam.
- Não vê o interior, a vista, o ruído nem a exposição solar — factores reais de
  valorização que só existem nas fotografias e no texto.
- Uma recolha única, de Agosto de 2026. Não capta evolução temporal.
- As distâncias são fiáveis ao nível do bairro, não da rua: 793 pontos
  distintos para 1 514 anúncios, porque o site agrupa coordenadas próximas.

## Por fazer

- [ ] Passar as funções de limpeza dos notebooks para `src/features/limpeza.py`
- [ ] Dashboard Streamlit com mapa e lista de desvios
- [ ] Recolha periódica, para acompanhar a evolução dos preços
