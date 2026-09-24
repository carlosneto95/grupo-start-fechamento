"""Receitas: notas fiscais emitidas (NF-e de venda e NFS-e de serviço).

Diferenças importantes em relação a contas a pagar:

  - A listagem já traz valor, data, cliente e situação. O detalhe só acrescenta
    categoria (serviço) e marcadores (venda). Como o volume é pequeno (~1.100
    notas em dois anos), detalhamos todas.

  - Não existe campo de competência: ela é derivada da data de emissão. Para
    venda isso já é o correto. Para serviço a competência é flutuante e no Tiny
    fica no MARCADOR — que a API v2 não expõe em nota de serviço. Por isso a
    competência é editável na tela (ver competencia_manual).

  - Nota cancelada, rejeitada ou denegada NÃO é receita. Guardamos todas (o banco
    é espelho do Tiny) e a exclusão acontece na hora de somar.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import auditoria
from app.db import get_conn
from app.dinheiro import para_centavos, para_reais
from app.ordenacao import ordenar_linhas
from app.visao import (FILTRO_SQL_NOTAS, SEM_VALOR, casa_data,
                       formatar_valor, rotulo_consideracao)
from app.reports.contas_pagar import _separar_categoria

# Situações que não representam receita realizada. Comparadas em maiúsculas
# contra a descrição que o Tiny devolve.
#   - Cancelada/Rejeitada/Denegada/Excluída: a nota não vale.
#   - Pendente: ainda não foi emitida de fato, então não é receita realizada.
# As situações que CONTAM hoje são "Emitida", "Emitida DANFE" e "Autorizada".
SITUACOES_SEM_RECEITA = {"CANCELADA", "REJEITADA", "DENEGADA", "EXCLUIDA", "PENDENTE"}

# Rótulo das notas sem categoria — precisa ser o mesmo no filtro e na tela.
SEM_CATEGORIA_ROTULO = "(sem categoria)"

COLUNAS = [
    "empresa", "tipo_nota", "id", "numero", "serie", "numero_rps", "data_emissao",
    "cliente_nome", "cliente_cpf_cnpj", "valor", "situacao", "descricao_situacao",
    "vendedor", "categoria", "categoria_primaria", "subcategoria", "marcadores",
    "competencia",
]


def _competencia_da_data(data_br: str | None) -> str | None:
    """"03/07/2026" -> "07/2026". Competência padrão = mês da emissão."""
    if not data_br:
        return None
    try:
        d = datetime.strptime(data_br, "%d/%m/%Y")
    except ValueError:
        return None
    return d.strftime("%m/%Y")


def _texto(valor) -> str | None:
    if valor is None:
        return None
    t = str(valor).strip()
    return t or None


def _numero(valor) -> float | None:
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def _marcadores_em_texto(marcadores) -> str | None:
    """A API devolve [{"marcador": {"descricao": ...}}, ...]; guardamos só as
    descrições, separadas por " | ", que é o que interessa para leitura."""
    if not marcadores:
        return None
    descricoes = []
    for m in marcadores:
        item = m.get("marcador", m) if isinstance(m, dict) else {}
        desc = _texto(item.get("descricao"))
        if desc:
            descricoes.append(desc)
    return " | ".join(descricoes) or None


def linha_de_venda(resumo: dict, detalhe: dict, empresa: str) -> dict:
    cliente = detalhe.get("cliente") or resumo.get("cliente") or {}
    data_emissao = _texto(resumo.get("data_emissao")) or _texto(detalhe.get("data_emissao"))
    return {
        "empresa": empresa,
        "tipo_nota": "venda",
        "id": str(resumo.get("id")),
        "numero": _texto(resumo.get("numero")),
        "serie": _texto(resumo.get("serie")),
        "numero_rps": None,
        "data_emissao": data_emissao,
        "cliente_nome": _texto(cliente.get("nome")) or _texto(resumo.get("nome")),
        "cliente_cpf_cnpj": _texto(cliente.get("cpf_cnpj")),
        "valor": _numero(resumo.get("valor")),
        "situacao": _texto(resumo.get("situacao")),
        "descricao_situacao": _texto(resumo.get("descricao_situacao")),
        "vendedor": _texto(detalhe.get("nome_vendedor")) or _texto(resumo.get("nome_vendedor")),
        # NF-e não tem categoria financeira no Tiny — fica em branco de propósito.
        "categoria": None,
        "categoria_primaria": None,
        "subcategoria": None,
        "marcadores": _marcadores_em_texto(detalhe.get("marcadores")),
        "competencia": _competencia_da_data(data_emissao),
    }


def valor_bruto_de_servico(detalhe: dict) -> float | None:
    """Valor BRUTO da nota de serviço, que é o que entra como receita.

    O `total_nota` da API não é sempre o bruto. Quando o ISS é retido na fonte
    (`descontar_iss_total == "S"`), o Tiny já devolve o valor com o ISS
    subtraído — é o "Valor líquido" que aparece na tela da nota. O bruto, que a
    tela chama de "Valor total", é `total_nota + valor_iss`.

    Conferido numa NFS-e real da START em 07/2026 (os valores abaixo são
    ILUSTRATIVOS, com a mesma aritmética: o repositório é público e não leva
    valor de nota real):
        Valor total     10.000,00   <- bruto, o que queremos
        Valor ISS          300,00   ISS Retido: Sim
        Valor líquido    9.700,00   <- o que a API devolve em total_nota

    E a aritmética fecha: o ISS é sempre 3% do BRUTO. Com a flag em "S",
    300,00 / 10.000,00 = 3,00%. Com a flag em "N", o mesmo percentual bate
    sobre o próprio total_nota — porque aí ele já é o bruto e nada foi
    descontado.

    Cuidado ao mexer aqui: o `valor` da LISTAGEM tem o mesmo problema (também
    vem líquido quando há retenção), então não adianta usá-lo como alternativa.
    Só o par total_nota + valor_iss do detalhe reconstrói o bruto.
    """
    total = _numero(detalhe.get("total_nota"))
    if total is None:
        return None
    if _texto(detalhe.get("descontar_iss_total")) == "S":
        return round(total + (_numero(detalhe.get("valor_iss")) or 0), 2)
    return total


def linha_de_servico(resumo: dict, detalhe: dict, empresa: str) -> dict:
    cliente = detalhe.get("cliente") or {}
    data_emissao = _texto(resumo.get("data_emissao")) or _texto(detalhe.get("data_emissao"))
    categoria = _texto(detalhe.get("categoria_financeira"))
    primaria, sub = _separar_categoria(categoria)
    return {
        "empresa": empresa,
        "tipo_nota": "servico",
        "id": str(resumo.get("id")),
        "numero": _texto(resumo.get("numero")),
        "serie": _texto(detalhe.get("serie")),
        "numero_rps": _texto(resumo.get("numero_rps")) or _texto(detalhe.get("numeroRPS")),
        "data_emissao": data_emissao,
        "cliente_nome": _texto(cliente.get("nome")) or _texto(resumo.get("nome")),
        "cliente_cpf_cnpj": _texto(cliente.get("cpf_cnpj")),
        # Bruto, reconstruído do detalhe — ver valor_bruto_de_servico. O `valor`
        # da listagem NÃO serve aqui: vem líquido quando o ISS é retido.
        "valor": valor_bruto_de_servico(detalhe),
        "situacao": _texto(resumo.get("situacao")),
        "descricao_situacao": _texto(resumo.get("descricao_situacao")),
        "vendedor": _texto(resumo.get("nome_vendedor")) or _texto(detalhe.get("nome_vendedor")),
        "categoria": categoria,
        "categoria_primaria": primaria,
        "subcategoria": sub,
        "marcadores": None,  # a API v2 não expõe marcadores em nota de serviço
        # Competência EM BRANCO de propósito (decisão de 25/08/2026). Em nota de
        # serviço a emissão quase nunca é o mês de competência: o serviço é
        # prestado num mês e faturado em outro, às vezes com meses de distância
        # (há nota emitida em 03/2026 para competência 10/2025). Derivar da
        # emissão produzia um número plausível e errado, que ninguém revisava
        # porque parecia preenchido. Em branco, a nota aparece na tela pedindo
        # preenchimento — ver FILTRO_SQL_NOTAS em app/visao.py, que deixa passar
        # a competência vazia justamente para ela não sumir.
        # Nota de VENDA continua derivando da emissão: lá as duas coincidem.
        "competencia": None,
    }


def upsert_notas(linhas: list[dict]) -> None:
    """Grava preservando os ajustes manuais (competencia_manual, categoria_manual,
    considerar_manual): nenhuma delas está em COLUNAS, então o ON CONFLICT não as
    toca — ressincronizar não pode apagar o que o usuário editou."""
    if not linhas:
        return
    agora = datetime.now(timezone.utc).isoformat()
    # `valor` (reais, no código) é gravado como `valor_centavos` (banco).
    colunas_banco = ["valor_centavos" if c == "valor" else c for c in COLUNAS]
    placeholders = ", ".join(f":{c}" for c in colunas_banco)
    chaves = ("empresa", "tipo_nota", "id")

    def atualizacao(coluna: str) -> str:
        # `competencia` nunca é apagada por uma ressincronização. Nota de serviço
        # passou a chegar da API com ela em branco (ver linha_de_servico), e um
        # UPDATE cru zeraria a competência de todas as notas já preenchidas —
        # inclusive as que vieram das planilhas de correção. COALESCE faz o
        # valor novo valer só quando ele existe.
        if coluna == "competencia":
            return "competencia=COALESCE(excluded.competencia, notas.competencia)"
        return f"{coluna}=excluded.{coluna}"

    set_clause = ", ".join(atualizacao(c) for c in colunas_banco if c not in chaves)

    sql = f"""
        INSERT INTO notas ({", ".join(colunas_banco)}, atualizado_em)
        VALUES ({placeholders}, :atualizado_em)
        ON CONFLICT(empresa, tipo_nota, id)
        DO UPDATE SET {set_clause}, atualizado_em=excluded.atualizado_em
    """
    conn = get_conn()
    try:
        for linha in linhas:
            dados = {c: linha.get(c) for c in COLUNAS if c != "valor"}
            dados["valor_centavos"] = para_centavos(linha.get("valor"))
            dados["atualizado_em"] = agora
            conn.execute(sql, dados)
        conn.commit()
    finally:
        conn.close()


def definir_ajuste(empresa: str, tipo_nota: str, id_nota: str,
                   competencia: str | None = None, categoria: str | None = None) -> bool:
    """Grava a edição manual, com auditoria. String vazia limpa o ajuste (volta
    ao do ERP). Devolve False se a nota não existe.

    O formato da competência (MM/AAAA, mês 01-12) é garantido pelo CHECK da
    migração 2: valor torto levanta sqlite3.IntegrityError e nada é gravado."""
    campos: dict[str, str | None] = {}
    if competencia is not None:
        campos["competencia_manual"] = competencia or None
    if categoria is not None:
        campos["categoria_manual"] = categoria or None
    if not campos:
        return True

    conn = get_conn()
    try:
        chave = (empresa, tipo_nota, str(id_nota))
        linha = conn.execute(
            "SELECT competencia_manual, categoria_manual FROM notas"
            " WHERE empresa=? AND tipo_nota=? AND id=?",
            chave,
        ).fetchone()
        if linha is None:
            return False
        # Os nomes de coluna vêm do dicionário acima, escrito no código — nunca
        # da requisição. Por isso a f-string aqui é segura.
        atribuicoes = ", ".join(f"{c} = ?" for c in campos)
        conn.execute(
            f"UPDATE notas SET {atribuicoes} WHERE empresa=? AND tipo_nota=? AND id=?",
            [*campos.values(), *chave],
        )
        auditoria.registrar(
            conn, "ajustar", "nota", f"{tipo_nota}:{id_nota}", empresa,
            {c: linha[c] for c in campos}, campos,
        )
        conn.commit()
        return True
    finally:
        conn.close()


def definir_marcacao(empresa: str, tipo_nota: str, id_nota: str,
                     considerar: bool | None) -> bool:
    """Grava o override da linha, com auditoria. None devolve a nota ao padrão
    da situação. Devolve False se a nota não existe."""
    valor = None if considerar is None else int(bool(considerar))
    conn = get_conn()
    try:
        chave = (empresa, tipo_nota, str(id_nota))
        linha = conn.execute(
            "SELECT considerar_manual FROM notas WHERE empresa=? AND tipo_nota=? AND id=?",
            chave,
        ).fetchone()
        if linha is None:
            return False
        conn.execute(
            "UPDATE notas SET considerar_manual=? WHERE empresa=? AND tipo_nota=? AND id=?",
            (valor, *chave),
        )
        auditoria.registrar(
            conn, "marcar", "nota", f"{tipo_nota}:{id_nota}", empresa,
            {"considerar_manual": linha["considerar_manual"]}, {"considerar_manual": valor},
        )
        conn.commit()
        return True
    finally:
        conn.close()


def e_receita(linha: dict) -> bool:
    """Nota cancelada/rejeitada/denegada não entra no faturamento.

    É o padrão da linha, não a palavra final: o override manual tem precedência
    (ver _considerar_efetivo)."""
    descricao = (linha.get("descricao_situacao") or "").upper()
    return not any(s in descricao for s in SITUACOES_SEM_RECEITA)


def _considerar_efetivo(linha: dict) -> bool:
    """Mesma precedência das despesas: override manual manda; sem ele, vale a
    situação da nota no Tiny."""
    if linha.get("considerar_manual") is not None:
        return bool(linha["considerar_manual"])
    return e_receita(linha)


def _enriquecer(linha: dict) -> dict:
    """Aplica a precedência do ajuste manual sobre o dado do ERP, e traz o
    valor do banco (centavos) para reais Decimal."""
    if "valor_centavos" in linha:
        linha["valor"] = para_reais(linha["valor_centavos"])
    linha["competencia_efetiva"] = linha.get("competencia_manual") or linha.get("competencia")
    categoria_efetiva = linha.get("categoria_manual") or linha.get("categoria")
    linha["categoria_efetiva"] = categoria_efetiva
    primaria, sub = _separar_categoria(categoria_efetiva)
    linha["categoria_primaria_efetiva"] = primaria
    linha["subcategoria_efetiva"] = sub
    linha["editada"] = bool(linha.get("competencia_manual") or linha.get("categoria_manual"))
    linha["e_receita"] = e_receita(linha)
    linha["considerar_efetivo"] = _considerar_efetivo(linha)
    return linha


def mapa_por_id(empresa: str) -> dict[tuple[str, str], dict]:
    conn = get_conn()
    try:
        linhas = conn.execute("SELECT * FROM notas WHERE empresa = ?", (empresa,)).fetchall()
    finally:
        conn.close()
    return {(l["tipo_nota"], str(l["id"])): _enriquecer(dict(l)) for l in linhas}


def listar_notas(filtros: dict | None = None, competencias: set[str] | None = None,
                 ordenar: str | None = None, direcao: str = "desc",
                 categorias: set[str] | None = None,
                 consideracao: set[str] | None = None,
                 valores_sel: set[str] | None = None,
                 ordenado: bool = True) -> list[dict]:
    filtros = filtros or {}
    # Colunas cruas da tabela que o filtro de cabeçalho pode restringir. As
    # derivadas (competência e categoria efetivas) são tratadas mais abaixo.
    validos = {"empresa", "tipo_nota", "situacao", "descricao_situacao",
               "numero", "cliente_nome"}

    # A emissão é filtrada pela árvore Ano > Mês > Dia, em Python: a seleção
    # chega colapsada e não daria para casar com um IN de SQL.
    emissoes = set(filtros.pop("data_emissao", None) or []) or None

    condicoes: list[str] = []
    parametros: list = []
    for chave, valor in filtros.items():
        if chave not in validos:
            raise ValueError(f"filtro inválido: {chave}")
        if not valor:
            continue
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

    condicoes.append(FILTRO_SQL_NOTAS)
    sql = "SELECT * FROM notas WHERE " + " AND ".join(condicoes)

    conn = get_conn()
    try:
        linhas = [_enriquecer(dict(r)) for r in conn.execute(sql, parametros).fetchall()]
    finally:
        conn.close()

    # Ver o comentário gêmeo em repositorio_contas_pagar: casa pelo texto.
    if valores_sel:
        linhas = [
            l for l in linhas
            if (SEM_VALOR in valores_sel if l["valor"] is None
                else formatar_valor(l["valor"]) in valores_sel)
        ]

    if emissoes is not None:
        linhas = [l for l in linhas if casa_data(l["data_emissao"], emissoes)]

    if competencias is not None:
        linhas = [l for l in linhas if casa_data(l["competencia_efetiva"], competencias)]

    # A categoria efetiva combina o valor do ERP com o ajuste manual, então é
    # calculada em Python — o filtro tem que vir depois de montar as linhas.
    if categorias:
        linhas = [
            l for l in linhas
            if ((l["categoria_primaria_efetiva"] or "").strip() or SEM_VALOR) in categorias
            or (l["categoria_primaria_efetiva"] or SEM_CATEGORIA_ROTULO) in categorias
        ]

    # Filtro da coluna "Considerar": só dá para aplicar depois de calcular, já
    # que o valor mistura o override da linha com a situação vinda do ERP.
    if consideracao:
        linhas = [
            l for l in linhas
            if rotulo_consideracao(l["considerar_efetivo"]) in consideracao
        ]

    # O funil de coluna só precisa do CONJUNTO de valores: ordenar 15 mil
    # linhas para descartar a ordem era metade do tempo da lista.
    if not ordenado:
        return linhas
    return ordenar_linhas(linhas, ordenar, direcao, TIPOS_ORDENACAO, "data_emissao")


def sincronizar_notas(cliente, empresa_nome: str, data_ini, data_fim, progresso=None) -> dict:
    """Traz as notas do período e grava. Detalha todas (o volume é pequeno) para
    obter categoria nas de serviço e marcadores nas de venda."""
    def avisar(feitos, total, etapa):
        if progresso:
            progresso(feitos, total, etapa)

    avisar(0, 0, "Listando notas emitidas...")
    vendas = cliente.listar_notas_venda(data_ini, data_fim)
    servicos = cliente.listar_notas_servico(data_ini, data_fim)

    tarefas = [("venda", r) for r in vendas] + [("servico", r) for r in servicos]
    total = len(tarefas)
    avisar(0, total, "Buscando detalhe de cada nota...")

    ja_gravadas = mapa_por_id(empresa_nome)
    lote, novas, atualizadas = [], 0, 0

    for i, (tipo, resumo) in enumerate(tarefas, start=1):
        id_nota = str(resumo.get("id"))
        if tipo == "venda":
            detalhe = cliente.obter_nota_venda(id_nota)
            linha = linha_de_venda(resumo, detalhe, empresa_nome)
        else:
            detalhe = cliente.obter_nota_servico(id_nota)
            linha = linha_de_servico(resumo, detalhe, empresa_nome)

        if (tipo, id_nota) in ja_gravadas:
            atualizadas += 1
        else:
            novas += 1

        lote.append(linha)
        if len(lote) >= 25:
            upsert_notas(lote)
            lote = []
        avisar(i, total, "Buscando detalhe de cada nota...")

    upsert_notas(lote)

    receita = sum(l["valor"] or 0 for l in listar_notas({"empresa": empresa_nome})
                  if l["considerar_efetivo"])
    return {
        "encontradas": total,
        "vendas": len(vendas),
        "servicos": len(servicos),
        "novas": novas,
        "atualizadas": atualizadas,
        "receita_total_empresa": receita,
    }


def arvore_competencias_notas() -> dict:
    """Anos e meses presentes nas notas, para o filtro em árvore (igual despesas).

    Usa a competência EFETIVA (com o ajuste manual aplicado), senão uma nota
    reclassificada continuaria aparecendo no mês antigo do filtro."""
    conn = get_conn()
    try:
        valores = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT COALESCE(competencia_manual, competencia) FROM notas "
                f"WHERE COALESCE(competencia_manual, competencia) IS NOT NULL AND {FILTRO_SQL_NOTAS}"
            ).fetchall()
        ]
    finally:
        conn.close()

    from app.repositorio_contas_pagar import MESES_PT

    pares = []
    tem_vazio = False
    for v in valores:
        mes, _, ano = str(v).partition("/")
        if mes.isdigit() and ano.isdigit():
            pares.append((int(ano), int(mes), v))
        else:
            tem_vazio = True

    arvore: dict[int, list[tuple[int, str, str]]] = {}
    for ano, mes, texto in sorted(pares):
        arvore.setdefault(ano, []).append((mes, MESES_PT[mes - 1], texto))
    return {"anos": arvore, "tem_sem_data": tem_vazio}


def valores_distintos(coluna: str) -> list[str]:
    permitidas = {"empresa", "tipo_nota", "descricao_situacao", "vendedor"}
    if coluna not in permitidas:
        raise ValueError(f"coluna inválida: {coluna}")
    conn = get_conn()
    try:
        return [
            r[0] for r in conn.execute(
                f"SELECT DISTINCT {coluna} FROM notas "
                f"WHERE {coluna} IS NOT NULL AND {FILTRO_SQL_NOTAS} ORDER BY {coluna}"
            ).fetchall()
        ]
    finally:
        conn.close()


def categorias_conhecidas() -> list[str]:
    """Categorias PRIMÁRIAS disponíveis para escolher ao editar uma nota.

    Junta as que aparecem em notas e em contas a pagar, porque as duas pontas
    usam o mesmo vocabulário no Tiny e é assim que o dashboard as confronta.
    Só a primária: a subcategoria não é usada nesta coluna."""
    conn = get_conn()
    try:
        de_notas = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT categoria_primaria FROM notas WHERE categoria_primaria IS NOT NULL"
            ).fetchall()
        }
        manuais = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT categoria_manual FROM notas WHERE categoria_manual IS NOT NULL"
            ).fetchall()
        }
        de_contas = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT categoria_primaria FROM contas_pagar "
                "WHERE categoria_primaria IS NOT NULL"
            ).fetchall()
        }
    finally:
        conn.close()

    return sorted({c.strip() for c in (de_notas | manuais | de_contas) if c and c.strip()})


TIPOS_ORDENACAO = {
    "considerar_efetivo": "booleano",
    "empresa": "texto",
    "tipo_nota": "texto",
    "numero": "numero_texto",
    "data_emissao": "data_br",
    "cliente_nome": "texto",
    "valor": "numero",
    "descricao_situacao": "texto",
    "competencia_efetiva": "competencia",
    "categoria_primaria_efetiva": "texto",
}
COLUNAS_ORDENAVEIS = set(TIPOS_ORDENACAO)


def categorias_primarias_das_notas() -> list[str]:
    """Categorias primárias presentes nas notas, já considerando o ajuste manual.

    Inclui o rótulo de "sem categoria" quando houver nota sem classificar, para
    dar como filtrá-las e resolvê-las."""
    linhas = listar_notas()
    valores = {l["categoria_primaria_efetiva"] for l in linhas if l["categoria_primaria_efetiva"]}
    lista = sorted(valores)
    if any(not l["categoria_primaria_efetiva"] for l in linhas):
        lista.append(SEM_CATEGORIA_ROTULO)
    return lista
