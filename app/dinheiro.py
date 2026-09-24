"""Dinheiro: centavos no banco, Decimal no cálculo, uma regra de arredondamento.

Convenção (igual à do Controle de Impostos):
  - no BANCO, todo valor monetário é INTEGER em centavos (coluna *_centavos);
  - no CÓDIGO, a linha lida do banco traz o valor em reais como Decimal
    (`valor`, `saldo`, `pago`), exato ao centavo, sem ruído de float;
  - float só aparece na borda — ao ler o que a API ou a planilha manda.

REGRA DE ARREDONDAMENTO: meio centavo sobe (ROUND_HALF_UP), o arredondamento
comercial que a contabilidade usa. Vale para imposto calculado e para cada
parte de rateio. Quando um total é repartido, a soma das partes arredondadas
pode diferir do total por alguns centavos; o resíduo vai para a MAIOR parte
(ver `ratear`), para que as partes somem exatamente o total rateado.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")
ZERO = Decimal("0.00")


def arredondar(valor: Decimal) -> Decimal:
    """Arredonda ao centavo pela regra do sistema (meio centavo sobe)."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def como_decimal(valor) -> Decimal:
    """Qualquer número (ou None) -> Decimal, para somar sem misturar tipos.
    Float passa pelo texto (repr), como em para_centavos. None -> zero."""
    if valor is None:
        return ZERO
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def para_centavos(valor) -> int | None:
    """Reais (str, float, int ou Decimal) -> centavos inteiros.

    Float é convertido pelo `repr` (str), não pelo valor binário: 0.1 vira
    Decimal("0.1") e não 0.1000000000000000055511151231257827... — é o texto
    que o Tiny mandou que queremos preservar. Vazio ou ilegível -> None."""
    if valor is None or valor == "":
        return None
    try:
        reais = valor if isinstance(valor, Decimal) else Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    if not reais.is_finite():
        return None
    return int(arredondar(reais) * 100)


def para_reais(centavos) -> Decimal | None:
    """Centavos inteiros -> reais em Decimal com 2 casas. None continua None."""
    if centavos is None:
        return None
    return (Decimal(int(centavos)) / 100).quantize(CENTAVO)


def ratear(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte `total` na proporção de `pesos`, com as partes somando EXATAMENTE
    o total.

    Cada parte é arredondada ao centavo; o que sobra (ou falta) pelo
    arredondamento vai para a parte de MAIOR peso — a que mais absorve sem
    distorcer, e a mesma escolha de qualquer planilha de rateio séria.
    Empate de peso: a primeira da lista (a ordem de quem chama é estável).

    Pesos todos zero (ou lista vazia): não há base de rateio e todas as partes
    são zero — o total NÃO é distribuído. Quem chama decide o que fazer com
    ele (ver centros_de_custo.separar)."""
    total = arredondar(total)
    base = sum(pesos, Decimal(0))
    if not pesos or base == 0:
        return [ZERO for _ in pesos]
    partes = [arredondar(total * p / base) for p in pesos]
    residuo = total - sum(partes, Decimal(0))
    if residuo:
        maior = max(range(len(pesos)), key=lambda i: (pesos[i], -i))
        partes[maior] += residuo
    return partes
