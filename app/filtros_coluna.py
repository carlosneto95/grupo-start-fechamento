"""Filtro por coluna no estilo do AutoFiltro do Excel, com cascata.

Cada coluna filtravel tem um funil no cabecalho que abre uma lista com busca e
selecao multipla. Os valores da lista sao carregados sob demanda, nao junto com
a pagina: so a coluna "fornecedor" tem 1.467 valores distintos, e renderizar
todas as colunas de uma vez somaria milhares de elementos numa tela que ja
carrega 15 mil linhas.

**Cascata.** A lista de um funil mostra so o que existe no recorte atual, como
no Excel: com empresa=MSV marcado, a coluna Categoria cai de 43 para 14 valores.
Por isso os valores saem das linhas ja filtradas, e nao de um SELECT DISTINCT na
tabela inteira.

A regra tem uma excecao que a faz funcionar: o funil da coluna X ignora **o
filtro da propria X**. Sem isso, ao marcar um fornecedor a lista passaria a ter
so ele, e nunca mais daria para acrescentar outro nem trocar de ideia.

Cada coluna declara de onde tirar o valor. A maioria e coluna direta da linha;
valor e "considerar" sao derivadas e precisam do mesmo formato que a tela mostra
(ver _valor_da_linha).
"""
from __future__ import annotations

from app.visao import SEM_VALOR, formatar_valor, rotulo_consideracao

# Colunas filtraveis por tabela. O valor de cada uma sai da propria linha
# (ver _valor_da_linha) — nao ha mais expressao SQL aqui.
COLUNAS = {
    "despesas": {
        "considerar_efetivo": None,
        "empresa": None,
        "fornecedor": None,
        "competencia": None,
        "valor": None,
        "categoria_primaria": None,
        "subcategoria": None,
        "situacao": None,
        "data_emissao": None,
        "data_vencimento": None,
        "data_liquidacao": None,
    },
    "receitas": {
        "considerar_efetivo": None,
        "empresa": None,
        "tipo_nota": None,
        "numero": None,
        "data_emissao": None,
        "cliente_nome": None,
        "valor": None,
        "descricao_situacao": None,
        # Derivadas: o ajuste manual tem precedencia sobre o valor do ERP.
        "competencia_efetiva": None,
        "categoria_primaria_efetiva": None,
    },
}

# Receitas foi partida em duas telas (venda e servico). Cada uma precisa da sua
# CHAVE DE TABELA propria, e nao de um "receitas" compartilhado: a lista do funil
# vem em cascata, do recorte que a tela mostra. Com chave compartilhada, o funil
# de Cliente na tela de Vendas listaria tambem os clientes que so tem nota de
# servico — valores que, marcados, esvaziariam a tabela sem explicacao.
#
# "tipo_nota" sai das duas: numa tela onde ele e constante, o funil teria um
# valor so e ocuparia espaco de cabecalho sem filtrar nada.
COLUNAS["receitas_vendas"] = {
    c: v for c, v in COLUNAS["receitas"].items() if c != "tipo_nota"
}
COLUNAS["receitas_servicos"] = dict(COLUNAS["receitas_vendas"])

# Teto de itens devolvidos. Com a busca embutida, ninguém precisa rolar mais que
# isso — e evita despejar 1.500 checkboxes de uma vez no navegador.
LIMITE = 400



def _e_data(coluna: str) -> bool:
    return coluna.startswith("data_")


def _e_competencia(coluna: str) -> bool:
    return coluna.startswith("competencia")


def _chave_ordem(valor: str, coluna: str):
    """Datas e competências ordenam cronologicamente, não alfabeticamente."""
    if _e_data(coluna) and len(valor) == 10:
        return valor[6:10] + valor[3:5] + valor[0:2]
    if _e_competencia(coluna) and len(valor) == 7:
        return valor[3:7] + valor[0:2]
    return valor.casefold()


MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")


def _nome_do_mes(mm: str) -> str:
    """Aceita mês fora de 01-12 sem quebrar: o ERP às vezes traz sujeira e a
    regra do projeto é mostrar o que está lá, não corrigir."""
    try:
        return MESES[int(mm) - 1]
    except (ValueError, IndexError):
        return mm


def _montar_arvore(ordenados: list[str], coluna: str, tem_vazio: bool) -> list[dict]:
    """Agrupa as datas em Ano > Mês > Dia (competência para em Ano > Mês).

    Cada nó carrega o valor que vai para a URL quando ele é marcado inteiro:
    o ano manda "2026", o mês manda "08/2026" e o dia manda "05/08/2026". É o
    que impede a URL de estourar — marcar um ano inteiro vira um parâmetro só,
    em vez dos 365 dias. O servidor casa a linha por qualquer um dos três."""
    anos: dict[str, dict[str, list[str]]] = {}
    soltos: list[str] = []  # valor fora do formato esperado: vira folha na raiz

    for v in ordenados:
        if _e_data(coluna) and len(v) == 10 and v[2] == "/" and v[5] == "/":
            anos.setdefault(v[6:10], {}).setdefault(v[3:5], []).append(v)
        elif _e_competencia(coluna) and len(v) == 7 and v[2] == "/":
            anos.setdefault(v[3:7], {}).setdefault(v[0:2], [])
        else:
            soltos.append(v)

    arvore = []
    for ano in sorted(anos):
        meses = []
        for mm in sorted(anos[ano]):
            dias = [
                {"valor": d, "rotulo": d[0:2]}
                for d in sorted(anos[ano][mm], key=lambda x: x[0:2])
            ]
            meses.append({"valor": f"{mm}/{ano}", "rotulo": _nome_do_mes(mm), "filhos": dias})
        arvore.append({"valor": ano, "rotulo": ano, "filhos": meses})

    arvore += [{"valor": v, "rotulo": v} for v in soltos]
    if tem_vazio:
        arvore.append({"valor": SEM_VALOR, "rotulo": SEM_VALOR})
    return arvore


def _valor_da_linha(coluna: str, linha: dict) -> str:
    """O valor da coluna nesta linha, no mesmo formato que a celula mostra.

    Tem que ser identico ao da tela: o filtro casa por texto, entao qualquer
    divergencia de formatacao faria marcar um valor no funil nao encontrar a
    linha correspondente."""
    if coluna == "considerar_efetivo":
        return rotulo_consideracao(linha["considerar_efetivo"])
    if coluna == "valor":
        return "" if linha.get("valor") is None else formatar_valor(linha["valor"])
    return str(linha.get(coluna) or "").strip()


def valores(tabela: str, coluna: str, linhas: list[dict], busca: str = "",
            selecionados: list[str] | None = None) -> dict:
    """Valores distintos de uma coluna dentro das linhas recebidas.

    `linhas` ja vem filtrada por todas as outras colunas (a cascata) e sem o
    filtro desta — quem monta esse recorte e a rota /api/valores-filtro.

    `selecionados` sao os valores que a coluna ja filtra. Entram na lista mesmo
    sem linha por tras: um valor marcado que sumisse da tela continuaria
    filtrando em silencio, e a tabela ficaria vazia sem explicacao.

    Colunas de data e competencia devolvem uma arvore Ano > Mes > Dia
    ({"tipo": "arvore"}); as demais devolvem lista simples, cortada em LIMITE
    itens — o total permite avisar na tela quando a lista foi cortada."""
    if tabela not in COLUNAS or coluna not in COLUNAS[tabela]:
        raise ValueError(f"coluna não filtrável: {tabela}.{coluna}")

    brutos = {_valor_da_linha(coluna, linha) for linha in linhas}
    tem_vazio = "" in brutos
    brutos.discard("")

    # O que ja filtra aparece sempre, mesmo fora do recorte das outras colunas.
    for marcado in (selecionados or []):
        if marcado == SEM_VALOR:
            tem_vazio = True
        elif marcado:
            brutos.add(marcado)

    if busca:
        alvo = busca.casefold()
        brutos = {v for v in brutos if alvo in v.casefold()}

    # Desempate pelo texto cru: "Fulano" e "FULANO" empatam no casefold, e o
    # conjunto `brutos` não tem ordem estável entre execuções — sem o
    # desempate, a lista saía numa ordem diferente a cada processo (achado do
    # golden master na Fase 0; corrigido na Fase 1 com aval do Neto).
    ordenados = sorted(brutos, key=lambda v: (_chave_ordem(v, coluna), v))
    mostrar_vazio = tem_vazio and (not busca or busca.casefold() in SEM_VALOR)

    # A arvore nao e cortada: ela ja nasce recolhida, entao o custo de ter
    # muitos dias escondidos e baixo, e cortar quebraria a hierarquia.
    if _e_data(coluna) or _e_competencia(coluna):
        return {
            "tipo": "arvore",
            "arvore": _montar_arvore(ordenados, coluna, mostrar_vazio),
            "total": len(ordenados) + (1 if mostrar_vazio else 0),
        }

    cortados = ordenados[:LIMITE]
    total = len(ordenados) + (1 if mostrar_vazio else 0)
    if mostrar_vazio:
        cortados.append(SEM_VALOR)

    return {"tipo": "lista", "valores": cortados, "total": total,
            "truncado": total > len(cortados)}
