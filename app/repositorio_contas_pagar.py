"""Acesso ao banco para contas a pagar: gravação dos dados extraídos, override
manual por linha ("considerar sim/não") e regras fixas de exclusão por
categoria/subcategoria.

Regra de precedência: se a linha tem override manual (considerar_manual não
nulo), ele vale. Senão, a linha é excluída automaticamente se a categoria
primária OU a subcategoria dela estiver nas regras de exclusão.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import auditoria
from app.db import get_conn
from app.dinheiro import para_centavos, para_reais
from app.ordenacao import ordenar_linhas
from app.visao import (ANO_MINIMO, FILTRO_SQL_CONTAS, SEM_VALOR, casa_data,
                       formatar_valor, rotulo_consideracao)

COLUNAS = [
    "empresa", "id", "fornecedor", "data_emissao", "data_vencimento", "data_liquidacao",
    "valor", "saldo", "pago", "situacao", "numero_documento", "categoria",
    "categoria_primaria", "subcategoria", "centro_custo", "forma_pagamento", "forma_pagamento_texto",
    "historico", "competencia",
]

# Colunas monetárias: no banco em centavos (valor_centavos...), na linha lida
# em reais Decimal (valor...). Ver app/dinheiro.py.
MONETARIAS = ("valor", "saldo", "pago")


def _para_banco(linha: dict) -> dict:
    """Linha no formato do código (reais) -> parâmetros do INSERT (centavos)."""
    dados = {c: linha.get(c) for c in COLUNAS if c not in MONETARIAS}
    for c in MONETARIAS:
        dados[f"{c}_centavos"] = para_centavos(linha.get(c))
    return dados


def _em_reais(linha: dict) -> dict:
    """Linha lida do banco (centavos) -> linha do código, com `valor`, `saldo`
    e `pago` em reais Decimal. As colunas *_centavos continuam na linha para
    quem precisar somar inteiro."""
    for c in MONETARIAS:
        linha[c] = para_reais(linha.get(f"{c}_centavos"))
    return linha


# Colunas lidas pelas LISTAGENS (Despesas, Dashboard, funis). Fica de fora o
# que só a sincronização e a conferência usam (historico, forma de pagamento
# em texto, centro de custo extraído do histórico, número do documento).
COLUNAS_LISTAGEM = ", ".join(
    [
        "empresa", "id", "fornecedor", "data_emissao", "data_vencimento", "data_liquidacao",
        "valor_centavos", "saldo_centavos", "pago_centavos", "situacao", "categoria",
        "categoria_primaria", "subcategoria", "forma_pagamento", "competencia",
        "considerar_manual", "atualizado_em",
    ]
)

COLUNAS_FILTRO_VALIDAS = {"empresa", "fornecedor", "categoria_primaria", "subcategoria", "situacao"}
COLUNAS_DATA_FILTRAVEIS = {"data_emissao", "data_vencimento", "data_liquidacao"}









def upsert_contas(linhas: list[dict]) -> None:
    """Insere/atualiza contas, preservando o override manual (considerar_manual)
    que já existir para linhas repetidas (re-extração não deve apagar sua escolha)."""
    if not linhas:
        return

    agora = datetime.now(timezone.utc).isoformat()
    # Nomes de coluna do BANCO (com *_centavos), escritos no código — nunca
    # vindos de fora; por isso a montagem com f-string é segura.
    colunas_banco = list(_para_banco({}))
    placeholders = ", ".join(f":{c}" for c in colunas_banco)
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in colunas_banco if c not in ("empresa", "id")
    )

    sql = f"""
        INSERT INTO contas_pagar ({", ".join(colunas_banco)}, atualizado_em)
        VALUES ({placeholders}, :atualizado_em)
        ON CONFLICT(empresa, id) DO UPDATE SET {set_clause}, atualizado_em=excluded.atualizado_em
    """

    conn = get_conn()
    try:
        for linha in linhas:
            dados = _para_banco(linha)
            dados["atualizado_em"] = agora
            conn.execute(sql, dados)
        conn.commit()
    finally:
        conn.close()


def mapa_por_id(empresa: str) -> dict[str, dict]:
    """{id: linha} do que já está gravado, para comparar com o que veio da API."""
    conn = get_conn()
    try:
        linhas = conn.execute(
            "SELECT * FROM contas_pagar WHERE empresa = ?", (empresa,)
        ).fetchall()
    finally:
        conn.close()
    return {str(l["id"]): _em_reais(dict(l)) for l in linhas}


def definir_manual(empresa: str, id_conta: str, considerar: bool | None) -> bool:
    """Grava o override Considerar/Desconsiderar da conta, com auditoria.

    Devolve False se a conta não existe (nada é gravado nem auditado)."""
    valor = None if considerar is None else (1 if considerar else 0)
    conn = get_conn()
    try:
        linha = conn.execute(
            "SELECT considerar_manual FROM contas_pagar WHERE empresa=? AND id=?",
            (empresa, id_conta),
        ).fetchone()
        if linha is None:
            return False
        conn.execute(
            "UPDATE contas_pagar SET considerar_manual=? WHERE empresa=? AND id=?",
            (valor, empresa, id_conta),
        )
        auditoria.registrar(
            conn, "marcar", "conta", str(id_conta), empresa,
            {"considerar_manual": linha["considerar_manual"]}, {"considerar_manual": valor},
        )
        conn.commit()
        return True
    finally:
        conn.close()


def listar_regras_exclusao() -> dict[str, list[str]]:
    conn = get_conn()
    try:
        linhas = conn.execute("SELECT tipo, valor FROM regras_exclusao").fetchall()
    finally:
        conn.close()

    resultado: dict[str, list[str]] = {"categoria_primaria": [], "subcategoria": []}
    for linha in linhas:
        resultado.setdefault(linha["tipo"], []).append(linha["valor"])
    return resultado


def definir_regras_exclusao(tipo: str, valores: list[str]) -> None:
    if tipo not in ("categoria_primaria", "subcategoria"):
        raise ValueError(f"tipo inválido: {tipo}")

    conn = get_conn()
    try:
        antes = sorted(
            r[0] for r in conn.execute("SELECT valor FROM regras_exclusao WHERE tipo=?", (tipo,))
        )
        depois = sorted(set(valores))
        if antes == depois:
            return  # nada mudou: não regrava nem polui a auditoria
        conn.execute("DELETE FROM regras_exclusao WHERE tipo=?", (tipo,))
        conn.executemany(
            "INSERT INTO regras_exclusao (tipo, valor) VALUES (?, ?)",
            [(tipo, v) for v in depois],
        )
        auditoria.registrar(conn, "regras_exclusao", "regras_exclusao", tipo, None, antes, depois)
        conn.commit()
    finally:
        conn.close()


def listar_valores_distintos(coluna: str) -> list[str]:
    if coluna not in COLUNAS_FILTRO_VALIDAS:
        raise ValueError(f"coluna inválida: {coluna}")

    conn = get_conn()
    try:
        linhas = conn.execute(
            f"SELECT DISTINCT {coluna} FROM contas_pagar "
            f"WHERE {coluna} IS NOT NULL AND {FILTRO_SQL_CONTAS} ORDER BY {coluna}"
        ).fetchall()
    finally:
        conn.close()
    return [linha[0] for linha in linhas]


TIPOS_ORDENACAO = {
    "considerar_efetivo": "booleano",
    "empresa": "texto",
    "fornecedor": "texto",
    "data_emissao": "data_br",
    "data_vencimento": "data_br",
    "data_liquidacao": "data_br",
    "competencia": "competencia",
    "valor": "numero",
    "categoria_primaria": "texto",
    "subcategoria": "texto",
    "situacao": "texto",
}
COLUNAS_ORDENAVEIS = set(TIPOS_ORDENACAO)


def _considerar_efetivo(linha: dict, regras: dict[str, list[str]]) -> bool:
    if linha["considerar_manual"] is not None:
        return bool(linha["considerar_manual"])
    if linha["categoria_primaria"] in regras.get("categoria_primaria", []):
        return False
    if linha["subcategoria"] in regras.get("subcategoria", []):
        return False
    return True


def listar_contas(
    filtros: dict | None = None,
    filtros_data: dict | None = None,
    ordenar: str | None = None,
    direcao: str = "asc",
    competencias: set[str] | None = None,
    consideracao: set[str] | None = None,
    valores_sel: set[str] | None = None,
    ordenado: bool = True,
) -> list[dict]:
    """filtros: valores exatos (empresa, competencia, categoria_primaria, subcategoria).
    filtros_data: {"data_emissao": {"05/08/2026", "08/2026", "(vazio)", ...}, ...} — conjunto exato de
    seleção da árvore Ano > Mês > Dia, colapsada (ver visao.casa_data), como o filtro do Excel (com
    checkbox). Uma coluna ausente do dict = sem filtro nessa coluna (mostra tudo).
    ordenar/direcao: coluna de ordenação e "asc"/"desc" (padrão: vencimento crescente)."""
    filtros = filtros or {}
    filtros_data = filtros_data or {}

    condicoes: list[str] = []
    parametros: list = []
    for chave, valor in filtros.items():
        if chave not in COLUNAS_FILTRO_VALIDAS:
            raise ValueError(f"filtro inválido: {chave}")
        if not valor:
            continue
        # Aceita um valor só (dropdown) ou vários (filtro de coluna, seleção múltipla).
        valores = [v for v in valor if v] if isinstance(valor, (list, set, tuple)) else [valor]
        if not valores:
            continue
        # "(vazio)" representa as células em branco, que não casam com IN.
        vazio = SEM_VALOR in valores
        valores = [v for v in valores if v != SEM_VALOR]
        partes = []
        if valores:
            partes.append(f"{chave} IN ({', '.join('?' * len(valores))})")
            parametros.extend(valores)
        if vazio:
            partes.append(f"({chave} IS NULL OR TRIM({chave}) = '')")
        condicoes.append("(" + " OR ".join(partes) + ")")

    # Só o período que o sistema exibe — o resto continua no banco, mas fora da visão.
    condicoes.append(FILTRO_SQL_CONTAS)

    # Colunas explícitas em vez de SELECT *: o `historico` é texto livre longo,
    # nenhuma listagem o usa, e trazê-lo nas 15 mil linhas era o maior custo
    # de leitura do Dashboard. A lista é fixa no código (nada vem de fora).
    sql = f"SELECT {COLUNAS_LISTAGEM} FROM contas_pagar WHERE " + " AND ".join(condicoes)

    conn = get_conn()
    try:
        linhas = [_em_reais(dict(r)) for r in conn.execute(sql, parametros).fetchall()]
    finally:
        conn.close()

    if competencias is not None:
        linhas = [
            l for l in linhas
            if casa_data(l["competencia"], competencias)
        ]

    # Valor: o funil manda o número já formatado (1.234,50), igual ao da célula.
    # Comparar texto evita a armadilha do float — 0.1 + 0.2 nunca casaria com
    # "0,30" numa comparação numérica direta.
    if valores_sel:
        linhas = [
            l for l in linhas
            if (SEM_VALOR in valores_sel if l["valor"] is None
                else formatar_valor(l["valor"]) in valores_sel)
        ]

    for campo, datas_selecionadas in filtros_data.items():
        if campo not in COLUNAS_DATA_FILTRAVEIS:
            raise ValueError(f"filtro de data inválido: {campo}")
        if datas_selecionadas is None:
            continue  # sem filtro nessa coluna

        linhas = [l for l in linhas if casa_data(l[campo], datas_selecionadas)]

    regras = listar_regras_exclusao()
    for linha in linhas:
        linha["considerar_efetivo"] = _considerar_efetivo(linha, regras)

    # Filtro da coluna "Considerar": só dá para aplicar depois de calcular, já
    # que o valor mistura o override da linha com as regras de exclusão.
    if consideracao:
        linhas = [
            l for l in linhas
            if rotulo_consideracao(l["considerar_efetivo"]) in consideracao
        ]

    # O funil de coluna só precisa do CONJUNTO de valores: ordenar 15 mil
    # linhas para descartar a ordem era metade do tempo da lista.
    if not ordenado:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO, "data_vencimento")


def competencias_disponiveis() -> list[str]:
    """Competências existentes (despesas + receitas), em ordem cronológica.

    Junta as duas pontas porque o slicer do dashboard filtra os dois lados: um
    mês que só tem receita precisa aparecer na lista."""
    conn = get_conn()
    try:
        das_contas = {
            r[0] for r in conn.execute(
                f"SELECT DISTINCT competencia FROM contas_pagar "
                # Competência vazia passa pelo filtro de visão (aparece em
                # Despesas), mas não é opção de slicer: não é um mês.
                f"WHERE TRIM(COALESCE(competencia, '')) <> '' AND {FILTRO_SQL_CONTAS}"
            ).fetchall()
        }
        das_notas = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT COALESCE(competencia_manual, competencia) FROM notas "
                "WHERE COALESCE(competencia_manual, competencia) IS NOT NULL "
                f"AND substr(COALESCE(competencia_manual, competencia), 4, 4) >= '{ANO_MINIMO}'"
            ).fetchall()
        }
    finally:
        conn.close()

    def ordem(texto):
        mes, _, ano = str(texto).partition("/")
        return (int(ano), int(mes)) if mes.isdigit() and ano.isdigit() else (9999, 99)

    return sorted(das_contas | das_notas, key=ordem)
