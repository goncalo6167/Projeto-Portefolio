"""
Configuração partilhada do projeto: âmbito geográfico e caminhos.

Existe para que a lista de freguesias tenha um único dono. Antes estava
duplicada entre o scraper e o script do INE, o que é a receita para as duas
cópias divergirem sem ninguém dar por isso.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

DATA = RAIZ / "data"
RAW = DATA / "raw"
HTML = RAW / "html"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
OUTPUTS = RAIZ / "outputs"

# ÂMBITO: as 5 freguesias do núcleo urbano de Coimbra.
#
# Porquê estas e não o concelho inteiro: as outras 13 são periurbanas ou
# rurais e o mercado de habitação em altura aí é residual. Uma recolha
# exploratória às 8 periurbanas devolveu 32 anúncios no total, com Souselas
# e Botão a zero. Um modelo de preço por m² assente em células de 2 a 8
# observações não é defensável.
#
# Estas 5 concentram a procura (universidade, hospitais, serviços), têm
# volume por bairro e formam um mercado coerente entre si.
#
# Os slugs vêm de `searchLinksRelatedLocations[].location` no JSON do próprio
# Imovirtual, não de adivinhação a partir do nome.
FREGUESIAS = {
    "santo_antonio_olivais": "santo-antonio-dos-olivais",
    "eiras_sao_paulo_frades": "eiras-e-sao-paulo-de-frades",
    "coimbra_centro": "se-nova-santa-cruz-almedina-e-sao-bartolomeu",
    "santa_clara_castelo_viegas": "santa-clara-e-castelo-viegas",
    "sao_martinho_bispo": "sao-martinho-do-bispo-e-ribeira-de-frades",
}
