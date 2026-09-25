"""Fechamento de competência (Fase 4.2).

Fechar um mês grava uma FOTO de cada conta e nota daquela competência (valor,
considerada ou não, categoria) — de todas as empresas. A partir daí:

  - o Dashboard continua mostrando o dado atual, com um ALERTA quando ele
    difere do fechado (decisão do Neto: número vivo + alerta);
  - os ajustes manuais daquele mês ficam travados (financeiro/trava_fechamento.py);
  - a tela de diferenças mostra o resultado fechado ao lado do atual e cada
    linha que mudou depois.

O resultado "fechado" é RECALCULADO da foto pelo mesmo `separar()` do
Dashboard, filtrado pelo escopo de quem olha — um Financeiro da MSV vê o
fechamento da MSV, não o consolidado. O resumo consolidado também fica gravado
em JSON, para registro.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from financeiro import auditoria
from financeiro.centros_de_custo import separar
from financeiro.db import FUSO_BRASILIA, agora_brasilia, get_conn
from financeiro.dinheiro import ZERO, para_centavos, para_reais
from financeiro.escopo import SISTEMA, clausula, exigir_admin
from financeiro.receitas import listar_notas
from financeiro.repositorio_contas_pagar import listar_contas
from financeiro.visao import ANO_MINIMO

CAMPOS_TOTAIS = ("receita", "despesa", "imposto", "adm1", "adm2", "custo_total", "resultado")


class ErroFechamento(ValueError):
    """Operação recusada; a mensagem vai para a tela."""


# ---- leitura -----------------------------------------------------------------------


def competencias_fechaveis(hoje=None) -> list[str]:
    """De 01/ANO_MINIMO até o mês corrente, do mais recente para o mais antigo."""
    hoje = hoje or datetime.now(FUSO_BRASILIA).date()
    saida, ano, mes = [], ANO_MINIMO, 1
    while (ano, mes) <= (hoje.year, hoje.month):
        saida.append(f"{mes:02d}/{ano}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return saida[::-1]


def vigentes() -> dict[str, dict]:
    """{competência: fechamento vigente (não reaberto)}."""
    conn = get_conn()
    try:
        return {
            r["competencia"]: dict(r)
            for r in conn.execute("SELECT * FROM fechamentos WHERE reaberto_em IS NULL")
        }
    finally:
        conn.close()


def historico(competencia: str) -> list[dict]:
    conn = get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, fechado_em, fechado_por, reaberto_em, reaberto_por, motivo_reabertura"
                " FROM fechamentos WHERE competencia = ? ORDER BY id DESC",
                (competencia,),
            )
        ]
    finally:
        conn.close()


# ---- linhas: atuais e da foto -------------------------------------------------------


def _linha(descricao, valor, considerar, categoria, competencia=None) -> dict:
    return {
        "descricao": descricao,
        "valor": valor,
        "considerar": bool(considerar),
        "categoria": (categoria or "").strip() or None,
        "competencia": competencia,
    }


def _linhas_atuais(escopo, competencias: set[str], empresas=None, contas=None, notas=None):
    """{competência: {(tabela, empresa, chave): linha}} do dado ATUAL.

    `contas`/`notas` já carregadas podem ser reaproveitadas (o Dashboard as
    tem na mão); senão, lê do banco só as competências pedidas."""
    filtro_empresa = {"empresa": list(empresas)} if empresas else {}
    if contas is None:
        contas = listar_contas(escopo, filtro_empresa, competencias=competencias, ordenado=False)
    if notas is None:
        notas = listar_notas(
            escopo, dict(filtro_empresa), competencias=competencias, ordenado=False
        )
    saida: dict[str, dict] = defaultdict(dict)
    for c in contas:
        comp = (c["competencia"] or "").strip()
        if comp in competencias:
            saida[comp][("conta", c["empresa"], str(c["id"]))] = _linha(
                c["fornecedor"], c["valor"], c["considerar_efetivo"], c["categoria_primaria"], comp
            )
    for n in notas:
        comp = (n["competencia_efetiva"] or "").strip()
        if comp in competencias:
            saida[comp][("nota", n["empresa"], f"{n['tipo_nota']}:{n['id']}")] = _linha(
                n["cliente_nome"],
                n["valor"],
                n["considerar_efetivo"],
                n["categoria_primaria_efetiva"],
                comp,
            )
    return saida


def _linhas_da_foto(escopo, fechamento_id: int, empresas=None) -> dict:
    filtro, params = clausula(escopo)
    sql = f"SELECT * FROM fechamento_linhas WHERE fechamento_id = ? AND {filtro}"
    parametros = [fechamento_id, *params]
    if empresas:
        sql += f" AND empresa IN ({', '.join('?' * len(empresas))})"
        parametros += list(empresas)
    conn = get_conn()
    try:
        return {
            (r["tabela"], r["empresa"], r["chave"]): _linha(
                r["descricao"], para_reais(r["valor_centavos"]), r["considerar"], r["categoria"]
            )
            for r in conn.execute(sql, parametros)
        }
    finally:
        conn.close()


def resultado(linhas: dict) -> dict:
    """Totais do Dashboard (separar) sobre um conjunto de linhas."""
    notas = [
        {"categoria_primaria_efetiva": l["categoria"], "valor": l["valor"]}
        for (tabela, _, _), l in linhas.items()
        if tabela == "nota" and l["considerar"]
    ]
    contas = [
        {"categoria_primaria": l["categoria"], "valor": l["valor"]}
        for (tabela, _, _), l in linhas.items()
        if tabela == "conta" and l["considerar"]
    ]
    total = separar(notas, contas)["total"]
    return {campo: total[campo] or ZERO for campo in CAMPOS_TOTAIS}


# ---- fechar e reabrir ----------------------------------------------------------------


def fechar(escopo, competencia: str) -> int:
    """Grava a foto de TODAS as empresas (o fechamento é do grupo). Só Admin."""
    exigir_admin(escopo)
    if competencia not in competencias_fechaveis():
        raise ErroFechamento("Competência fora do período que pode ser fechado.")
    linhas = _linhas_atuais(SISTEMA, {competencia}).get(competencia, {})
    resumo = {k: str(v) for k, v in resultado(linhas).items()}
    resumo["linhas"] = len(linhas)
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM fechamentos WHERE competencia = ? AND reaberto_em IS NULL",
            (competencia,),
        ).fetchone():
            raise ErroFechamento(f"{competencia} já está fechada.")
        cur = conn.execute(
            "INSERT INTO fechamentos (competencia, fechado_em, fechado_por, resumo) VALUES (?, ?, ?, ?)",
            (competencia, agora_brasilia(), escopo.login, json.dumps(resumo, ensure_ascii=False)),
        )
        fid = cur.lastrowid
        conn.executemany(
            "INSERT INTO fechamento_linhas (fechamento_id, tabela, empresa, chave, descricao,"
            " valor_centavos, considerar, categoria) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    fid,
                    tabela,
                    empresa,
                    chave,
                    l["descricao"],
                    para_centavos(l["valor"]),
                    int(l["considerar"]),
                    l["categoria"],
                )
                for (tabela, empresa, chave), l in linhas.items()
            ],
        )
        auditoria.registrar(conn, "fechar", "fechamento", competencia, None, None, resumo)
        conn.commit()
        return fid
    finally:
        conn.close()


def reabrir(escopo, competencia: str, motivo: str) -> None:
    """Reabrir exige Admin e motivo (vai para a auditoria). A foto continua
    guardada: o histórico mostra que o mês foi fechado e por que reabriu."""
    exigir_admin(escopo)
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ErroFechamento("Informe o motivo da reabertura (mínimo 5 caracteres).")
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE fechamentos SET reaberto_em = ?, reaberto_por = ?, motivo_reabertura = ?"
            " WHERE competencia = ? AND reaberto_em IS NULL",
            (agora_brasilia(), escopo.login, motivo, competencia),
        )
        if not cur.rowcount:
            raise ErroFechamento(f"{competencia} não está fechada.")
        auditoria.registrar(
            conn, "reabrir", "fechamento", competencia, None, None, {"motivo": motivo}
        )
        conn.commit()
    finally:
        conn.close()


# ---- diferenças pós-fechamento -------------------------------------------------------


def _efeito(antes: dict | None, depois: dict | None) -> object:
    """Quanto a linha mexe no total considerado (receita ou despesa)."""

    def conta(l):
        return (l["valor"] or ZERO) if (l and l["considerar"]) else ZERO

    return conta(depois) - conta(antes)


def _comparar(foto: dict, atual: dict, fora: dict) -> list[dict]:
    """Uma linha por diferença. `fora` = estado atual das linhas que saíram da
    competência (mostra para onde foram)."""
    diferencas = []
    for chave in sorted(set(foto) | set(atual)):
        antes, depois = foto.get(chave), atual.get(chave)
        tabela, empresa, id_ = chave
        if antes and depois:
            mudou = [c for c in ("valor", "considerar", "categoria") if antes[c] != depois[c]]
            if not mudou:
                continue
            mudanca = "alterada: " + ", ".join(mudou)
        elif depois:
            mudanca = "entrou no mês"
        else:
            destino = fora.get(chave)
            mudanca = (
                f"saiu do mês (agora em {destino['competencia'] or 'sem competência'})"
                if destino
                else "saiu do mês (não encontrada)"
            )
        diferencas.append(
            {
                "tabela": tabela,
                "tipo": "despesa" if tabela == "conta" else "receita",
                "empresa": empresa,
                "chave": id_,
                "descricao": (depois or antes)["descricao"],
                "categoria": (depois or antes)["categoria"],
                "mudanca": mudanca,
                "antes": antes,
                "depois": depois,
                "efeito": _efeito(antes, depois),
            }
        )
    return diferencas


def _estado_atual_por_chave(escopo, chaves: list[tuple]) -> dict:
    """Onde estão hoje as linhas que saíram da competência (competência atual)."""
    if not chaves:
        return {}
    filtro, params = clausula(escopo)
    saida = {}
    conn = get_conn()
    try:
        for tabela, empresa, chave in chaves:
            if tabela == "conta":
                r = conn.execute(
                    f"SELECT competencia AS comp FROM contas_pagar WHERE empresa = ? AND id = ? AND {filtro}",
                    (empresa, chave, *params),
                ).fetchone()
            else:
                tipo, _, id_ = chave.partition(":")
                r = conn.execute(
                    "SELECT COALESCE(competencia_manual, competencia) AS comp FROM notas"
                    f" WHERE empresa = ? AND tipo_nota = ? AND id = ? AND {filtro}",
                    (empresa, tipo, id_, *params),
                ).fetchone()
            if r is not None:
                saida[(tabela, empresa, chave)] = {"competencia": r["comp"]}
    finally:
        conn.close()
    return saida


def diferencas(escopo, competencia: str, empresas=None) -> dict | None:
    """Fechado × atual de UMA competência, dentro do escopo. None se aberta."""
    fechamento = vigentes().get(competencia)
    if fechamento is None:
        return None
    foto = _linhas_da_foto(escopo, fechamento["id"], empresas)
    atual = _linhas_atuais(escopo, {competencia}, empresas).get(competencia, {})
    saidas = [k for k in foto if k not in atual]
    linhas = _comparar(foto, atual, _estado_atual_por_chave(escopo, saidas))
    return {
        "fechamento": fechamento,
        "no_fechamento": resultado(foto),
        "agora": resultado(atual),
        "diferencas": linhas,
        "efeito_receita": sum((d["efeito"] for d in linhas if d["tipo"] == "receita"), ZERO),
        "efeito_despesa": sum((d["efeito"] for d in linhas if d["tipo"] == "despesa"), ZERO),
    }


def alertas(escopo, competencias: set[str], empresas=None, contas=None, notas=None) -> list[dict]:
    """Para o Dashboard: meses FECHADOS do recorte cujo dado atual difere da
    foto. Uma leitura só do dado atual para todos os meses (ou o que o
    Dashboard já carregou)."""
    fechadas = {c: f for c, f in vigentes().items() if c in (competencias or set())}
    if not fechadas:
        return []
    atuais = _linhas_atuais(escopo, set(fechadas), empresas, contas, notas)
    saida = []
    for comp in sorted(fechadas, key=lambda c: (c[3:], c[:2])):
        foto = _linhas_da_foto(escopo, fechadas[comp]["id"], empresas)
        difs = _comparar(foto, atuais.get(comp, {}), {})
        saida.append(
            {
                "competencia": comp,
                "fechado_em": fechadas[comp]["fechado_em"],
                "diferencas": len(difs),
                "efeito_receita": sum((d["efeito"] for d in difs if d["tipo"] == "receita"), ZERO),
                "efeito_despesa": sum((d["efeito"] for d in difs if d["tipo"] == "despesa"), ZERO),
            }
        )
    return saida
