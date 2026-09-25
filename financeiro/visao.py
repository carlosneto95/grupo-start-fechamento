"""Recorte de competência visível no sistema.

O sistema trata do fechamento de 2026 em diante. Lançamentos de competência
anterior continuam GRAVADOS (o banco é espelho do Tiny e não apagamos nada),
mas ficam fora das telas, dos filtros e dos totais — senão poluem a análise com
anos que não interessam.

Para passar a exibir outro período, muda-se só o ANO_MINIMO aqui.
"""

from __future__ import annotations

ANO_MINIMO = 2026

# A competência é guardada como texto "MM/AAAA", então o ano são os 4 caracteres
# a partir da 4ª posição. Comparação de texto funciona porque são todos 4 dígitos.
#
# Conta SEM competência passa (decisão do Neto, Fase 1, 24/09/2026), com a
# mesma regra que as notas de serviço já seguiam: antes, o substr de um texto
# vazio dava '' e a conta sumia de Despesas, do Dashboard e dos funis sem
# aviso — 134 contas no banco de 23/09/2026. Agora ela aparece com a
# competência "(vazio)" no funil, pedindo correção no Tiny.
FILTRO_SQL_CONTAS = (
    f"(TRIM(COALESCE(competencia, '')) = '' OR substr(competencia, 4, 4) >= '{ANO_MINIMO}')"
)

# Nota de serviço chega da API SEM competência (decisão de 25/08/2026: a emissão
# quase nunca é o mês de competência, então derivar produzia número errado). Ela
# precisa aparecer na tela para alguém preencher — se o filtro cortasse a
# competência vazia, toda NF nova sumiria em silêncio, e ninguém procura o que
# não sabe que existe. Por isso a vazia passa; é ela que vai pedir preenchimento.
_COMPETENCIA_NOTA = "COALESCE(competencia_manual, competencia)"
FILTRO_SQL_NOTAS = (
    f"(TRIM(COALESCE({_COMPETENCIA_NOTA}, '')) = ''"
    f" OR substr({_COMPETENCIA_NOTA}, 4, 4) >= '{ANO_MINIMO}')"
)


def competencia_visivel(competencia: str | None) -> bool:
    """True se a competência entra na visão do sistema."""
    if not competencia:
        return False
    _, _, ano = str(competencia).partition("/")
    return ano.isdigit() and int(ano) >= ANO_MINIMO


# Rótulo das células em branco na lista do filtro de coluna (como o "(Vazias)" do Excel).
SEM_VALOR = "(vazio)"

# A coluna "considerar" virou texto na tela e valor no filtro. Como ela é
# derivada (override manual + regras de exclusão), o rótulo é o dado — não
# existe coluna equivalente no banco.
CONSIDERAR_SIM = "Considerar"
CONSIDERAR_NAO = "Desconsiderar"


def formatar_valor(valor) -> str:
    """1234.5 -> "1.234,50". O filtro da coluna Valor casa pelo texto formatado,
    então este é o mesmo formato que aparece na célula — se divergir, marcar um
    valor no funil não encontraria a linha."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return "0,00"
    return f"{numero:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def rotulo_consideracao(considerar: bool) -> str:
    return CONSIDERAR_SIM if considerar else CONSIDERAR_NAO


def casa_data(bruto: str | None, selecionadas) -> bool:
    """A árvore Ano > Mês > Dia manda a seleção colapsada: um ano inteiro vem
    como "2026", um mês como "08/2026" e um dia como "05/08/2026". Sem isso a
    URL estouraria ao marcar um ano (365 parâmetros). Aqui a linha casa se
    qualquer um dos três níveis dela estiver marcado.

    Vale para data (dd/mm/aaaa) e para competência (mm/aaaa)."""
    bruto = (bruto or "").strip()
    if not bruto:
        return SEM_VALOR in selecionadas
    if bruto in selecionadas:
        return True
    # Sobe um nível a cada barra: 05/08/2026 -> 08/2026 -> 2026
    resto = bruto
    while "/" in resto:
        resto = resto.split("/", 1)[1]
        if resto in selecionadas:
            return True
    return False
