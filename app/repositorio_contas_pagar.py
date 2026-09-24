"""Acesso ao banco para contas a pagar: gravação dos dados extraídos, override
manual por linha ("considerar sim/não") e regras fixas de exclusão por
categoria/subcategoria.

Regra de precedência: se a linha tem override manual (considerar_manual não
nulo), ele vale. Senão, a linha é excluída automaticamente se a categoria
primária OU a subcategoria dela estiver nas regras de exclusão.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.db import get_conn
from app.ordenacao import ordenar_linhas
from app.visao import (ANO_MINIMO, FILTRO_SQL_CONTAS, SEM_VALOR, casa_data,
                       formatar_valor, rotulo_consideracao)

COLUNAS = [
    "empresa", "id", "fornecedor", "data_emissao", "data_vencimento", "data_liquidacao",
    "valor", "saldo", "pago", "situacao", "numero_documento", "categoria",
    "categoria_primaria", "subcategoria", "centro_custo", "forma_pagamento", "forma_pagamento_texto",
    "historico", "competencia",
]

COLUNAS_FILTRO_VALIDAS = {"empresa", "fornecedor", "categoria_primaria", "subcategoria", "situacao"}
COLUNAS_DATA_FILTRAVEIS = {"data_emissao", "data_vencimento", "data_liquidacao"}
SEM_DATA = "SEM_DATA"

MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _parse_data_br(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%d/%m/%Y").date()
    except ValueError:
        return None


def arvore_datas(coluna: str) -> dict:
    """Monta {ano: {(mes_num, nome_mes): [(dia, iso), ...]}} + se existe alguma linha
    sem data nessa coluna, pra montar o filtro tipo Excel (Ano > Mês > Dia)."""
    if coluna not in COLUNAS_DATA_FILTRAVEIS:
        raise ValueError(f"coluna inválida: {coluna}")

    conn = get_conn()
    try:
        valores = [
            r[0] for r in conn.execute(
                f"SELECT {coluna} FROM contas_pagar WHERE {FILTRO_SQL_CONTAS}"
            ).fetchall()
        ]
    finally:
        conn.close()

    tem_sem_data = any(not v for v in valores)
    datas = sorted({d for d in (_parse_data_br(v) for v in valores) if d is not None})

    arvore: dict[int, dict[tuple[int, str], list[tuple[int, str]]]] = {}
    for d in datas:
        mes_chave = (d.month, MESES_PT[d.month - 1])
        arvore.setdefault(d.year, {}).setdefault(mes_chave, []).append((d.day, d.isoformat()))

    return {"anos": arvore, "tem_sem_data": tem_sem_data}


def arvore_competencias() -> dict:
    """Monta {ano: [(mes_num, nome_mes, "MM/AAAA")]} para o filtro de competência.

    Competência é guardada como texto "MM/AAAA", que ordenado alfabeticamente sai
    errado (01/2027 viria antes de 12/2026). Aqui é ordenado como data de verdade."""
    conn = get_conn()
    try:
        valores = [r[0] for r in conn.execute(
            "SELECT DISTINCT competencia FROM contas_pagar "
            f"WHERE competencia IS NOT NULL AND {FILTRO_SQL_CONTAS}"
        ).fetchall()]
    finally:
        conn.close()

    pares = []
    tem_sem_competencia = False
    for v in valores:
        mes, _, ano = str(v).partition("/")
        if mes.isdigit() and ano.isdigit():
            pares.append((int(ano), int(mes), v))
        else:
            tem_sem_competencia = True

    arvore: dict[int, list[tuple[int, str, str]]] = {}
    for ano, mes, texto in sorted(pares):
        arvore.setdefault(ano, []).append((mes, MESES_PT[mes - 1], texto))

    return {"anos": arvore, "tem_sem_data": tem_sem_competencia}


def upsert_contas(linhas: list[dict]) -> None:
    """Insere/atualiza contas, preservando o override manual (considerar_manual)
    que já existir para linhas repetidas (re-extração não deve apagar sua escolha)."""
    if not linhas:
        return

    agora = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join(f":{c}" for c in COLUNAS)
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in COLUNAS if c not in ("empresa", "id"))

    sql = f"""
        INSERT INTO contas_pagar ({", ".join(COLUNAS)}, atualizado_em)
        VALUES ({placeholders}, :atualizado_em)
        ON CONFLICT(empresa, id) DO UPDATE SET {set_clause}, atualizado_em=excluded.atualizado_em
    """

    conn = get_conn()
    try:
        for linha in linhas:
            dados = {c: linha.get(c) for c in COLUNAS}
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
    return {str(l["id"]): dict(l) for l in linhas}


def definir_manual(empresa: str, id_conta: str, considerar: bool | None) -> None:
    valor = None if considerar is None else (1 if considerar else 0)
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE contas_pagar SET considerar_manual=? WHERE empresa=? AND id=?",
            (valor, empresa, id_conta),
        )
        conn.commit()
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
        conn.execute("DELETE FROM regras_exclusao WHERE tipo=?", (tipo,))
        conn.executemany(
            "INSERT INTO regras_exclusao (tipo, valor) VALUES (?, ?)",
            [(tipo, v) for v in valores],
        )
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
) -> list[dict]:
    """filtros: valores exatos (empresa, competencia, categoria_primaria, subcategoria).
    filtros_data: {"data_emissao": {"2026-08-05", ..., SEM_DATA}, ...} — conjunto exato de
    datas (formato ISO) a manter, tipo o filtro de data do Excel (Ano > Mês > Dia com
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

    sql = "SELECT * FROM contas_pagar WHERE " + " AND ".join(condicoes)

    conn = get_conn()
    try:
        linhas = [dict(r) for r in conn.execute(sql, parametros).fetchall()]
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
                f"WHERE competencia IS NOT NULL AND {FILTRO_SQL_CONTAS}"
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
