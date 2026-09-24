"""Ordenação de tabelas — usada por TODAS as telas do sistema.

Toda tabela do sistema deve poder ser ordenada clicando no cabeçalho. Para uma
tabela nova, basta:

  1. declarar aqui (ou na própria tela) o tipo de cada coluna ordenável;
  2. chamar `ordenar_linhas(...)` antes de mandar para o template;
  3. usar a macro `th_ordenavel` de `_ordenacao.html` no cabeçalho.

Ordenar pelo tipo certo importa: texto colocaria 01/2027 antes de 12/2026, e
"1.000" antes de "999". Cada tipo abaixo resolve um desses casos.
"""
from __future__ import annotations

from datetime import date, datetime

# Tipos aceitos em `tipos_por_coluna`:
#   "texto"       — comparação sem diferenciar maiúsculas/acentuação de caixa
#   "numero"      — valores numéricos
#   "data_br"     — "dd/mm/aaaa"
#   "competencia" — "mm/aaaa"
#   "booleano"    — verdadeiro/falso
#   "numero_texto"— texto que costuma ser número (ex: número de nota fiscal)
TIPOS = {"texto", "numero", "data_br", "competencia", "booleano", "numero_texto"}


def _chave(valor, tipo: str):
    """Devolve (esta_vazio, valor_comparavel).

    O primeiro elemento mantém linhas sem valor sempre no fim, em qualquer
    direção — uma conta sem data de liquidação não deve encabeçar a lista só
    porque foi invertida a ordem."""
    if tipo == "data_br":
        # Caminho rápido para o formato do Tiny (dd/mm/aaaa): fatiar e montar a
        # data custa ~1/20 do strptime, que dominava o tempo da tela de
        # Despesas (15 mil linhas). date() continua validando (31/02 é
        # inválida e vai para o fim, como antes). Qualquer outro formato cai
        # no strptime original, para a ordem sair idêntica à de antes.
        if isinstance(valor, str) and len(valor) == 10 and valor[2] == "/" and valor[5] == "/":
            try:
                return (False, date(int(valor[6:]), int(valor[3:5]), int(valor[:2])))
            except ValueError:
                pass
        try:
            return (False, datetime.strptime(valor, "%d/%m/%Y").date())
        except (TypeError, ValueError):
            return (True, date.min)

    if tipo == "competencia":
        if isinstance(valor, str) and "/" in valor:
            mes, _, ano = valor.partition("/")
            if mes.isdigit() and ano.isdigit():
                return (False, (int(ano), int(mes)))
        return (True, (0, 0))

    if tipo == "numero":
        try:
            return (valor is None, float(valor if valor is not None else 0))
        except (TypeError, ValueError):
            return (True, 0.0)

    if tipo == "booleano":
        return (False, bool(valor))

    if tipo == "numero_texto":
        texto = str(valor or "").strip()
        if not texto:
            return (True, (0, ""))
        # Os que são número ordenam numericamente; o resto vai depois, alfabético.
        return (False, (int(texto), "")) if texto.isdigit() else (False, (10**12, texto.casefold()))

    if valor in (None, ""):
        return (True, "")
    return (False, str(valor).casefold())


def ordenar_linhas(linhas: list[dict], coluna: str | None, direcao: str,
                   tipos_por_coluna: dict[str, str], padrao: str) -> list[dict]:
    """Ordena e devolve uma lista nova. Coluna desconhecida cai no padrão."""
    if coluna not in tipos_por_coluna:
        coluna = padrao
    tipo = tipos_por_coluna.get(coluna, "texto")

    chaves = {id(l): _chave(l.get(coluna), tipo) for l in linhas}
    com_valor = [l for l in linhas if not chaves[id(l)][0]]
    sem_valor = [l for l in linhas if chaves[id(l)][0]]
    com_valor.sort(key=lambda l: chaves[id(l)][1], reverse=(direcao == "desc"))
    return com_valor + sem_valor


def coluna_e_direcao(args, tipos_por_coluna: dict[str, str], padrao: str,
                     direcao_padrao: str = "asc") -> tuple[str, str]:
    """Lê ordenar/direcao da URL, com validação contra colunas inventadas."""
    coluna = args.get("ordenar") or padrao
    if coluna not in tipos_por_coluna:
        coluna = padrao
    pedida = args.get("direcao")
    direcao = pedida if pedida in ("asc", "desc") else direcao_padrao
    return coluna, direcao
