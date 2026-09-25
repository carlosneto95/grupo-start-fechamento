"""Fotografia dos números do fechamento, tirada pelas próprias rotas da tela.

É o juiz das Fases 1 em diante: qualquer refatoração (centavos, blueprints,
SQL novo) tem de produzir a MESMA fotografia sobre o MESMO banco congelado.

Por que pelas rotas e não chamando as funções direto: o que o usuário vê é o
que a rota monta — inclusive os filtros que moram nela (competência do
dashboard, tipo de nota fixo das telas de receita). Chamar as funções por fora
deixaria esse pedaço sem juiz.

O número é capturado no contexto que a rota entrega ao template (sinal
`template_rendered`), não raspado do HTML: a Fase 3 muda o layout inteiro e o
golden não pode quebrar por isso.

Este arquivo vai para o git; ele NÃO contém nenhum número real. Os números
ficam em tests/golden/esperado/, fora do git.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

EMPRESAS = ("MSV", "START", "GTF")
# 01/2026 até a última competência com movimento no banco congelado. A lista
# sai do próprio banco (ver _competencias_fechadas) para não fixar mês no código.
ANO_INICIAL = 2026


def _competencias_fechadas(conn: sqlite3.Connection, ate: str | None) -> list[str]:
    """Competências de 01/2026 até `ate` (MM/AAAA), inclusive.

    `ate` padrão = a última competência que tem NOTA (receita). Despesa tem
    parcela lançada até 2032, então o fim da receita é o melhor sinal de
    "último mês com movimento" que o banco oferece."""
    if ate is None:
        linha = conn.execute(
            "SELECT MAX(substr(k, 4, 4) || substr(k, 1, 2)) FROM ("
            " SELECT COALESCE(competencia_manual, competencia) AS k FROM notas)"
            " WHERE k GLOB '[0-1][0-9]/[0-9][0-9][0-9][0-9]'"
        ).fetchone()[0]
        ate = f"{linha[4:6]}/{linha[0:4]}"
    mes_fim, ano_fim = int(ate[:2]), int(ate[3:])
    saida = []
    ano, mes = ANO_INICIAL, 1
    while (ano, mes) <= (ano_fim, mes_fim):
        saida.append(f"{mes:02d}/{ano}")
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    return saida


# --------------------------------------------------------------------------
# Normalização: tudo vira JSON estável, com float arredondado
# --------------------------------------------------------------------------


def _limpo(valor):
    """Converte para JSON. Float com 6 casas: guarda mais que o centavo para a
    comparação poder dizer "mudou 0,004" em vez de esconder na arredondada."""
    # Decimal (dinheiro desde a Fase 1) e float comparam na mesma escala: a
    # fotografia é de NÚMEROS, não de tipos — o golden da Fase 0 foi tirado
    # com float e tem de continuar valendo como juiz.
    if isinstance(valor, (float, Decimal)):
        return round(float(valor), 6)
    if isinstance(valor, dict):
        return {str(k): _limpo(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpo(v) for v in valor]
    if isinstance(valor, (set, frozenset)):
        return sorted(_limpo(v) for v in valor)
    return valor


def _soma(linhas, campo="valor"):
    return sum(l.get(campo) or 0 for l in linhas)


def _resumo_despesas(ctx: dict) -> dict:
    contas = ctx["contas"]
    consideradas = [c for c in contas if c["considerar_efetivo"]]
    return {
        "linhas": len(contas),
        "consideradas": len(consideradas),
        "total_considerado": ctx["total_considerado"],
        "total_todas": _soma(contas),
        # Por empresa dentro do recorte: aponta de onde veio uma diferença.
        "por_empresa": {
            e: {
                "linhas": sum(1 for c in consideradas if c["empresa"] == e),
                "total": _soma(c for c in consideradas if c["empresa"] == e),
            }
            for e in sorted({c["empresa"] for c in contas})
        },
    }


def _resumo_receitas(ctx: dict) -> dict:
    return {
        "linhas": len(ctx["notas"]),
        "quantidade": ctx["quantidade"],
        "excluidas": ctx["excluidas"],
        "total_receita": ctx["total_receita"],
        "total_excluido": ctx["total_excluido"],
    }


def _resumo_dashboard(ctx: dict) -> dict:
    blocos = ctx["blocos"]
    campos = (
        "nome",
        "receita",
        "despesa",
        "imposto",
        "adm1",
        "adm2",
        "custo_total",
        "resultado",
        "margem",
        "qtd_receita",
        "qtd_despesa",
    )

    def linhas(bloco):
        # Chaveado por nome: a diferença aparece como "servicos.OBRA X.adm1",
        # que é a explicação linha a linha que o prompt exige.
        return {l["nome"]: {c: l.get(c) for c in campos} for l in bloco["linhas"]}

    return {
        "total_receita": ctx["total_receita"],
        "total_despesa": ctx["total_despesa"],
        "resultado": ctx["resultado"],
        "margem": ctx["margem"],
        "quantidade_notas": ctx["quantidade_notas"],
        "quantidade_contas": ctx["quantidade_contas"],
        "total": {c: blocos["total"].get(c) for c in campos},
        "resumo": [{c: r.get(c) for c in campos} for r in blocos["resumo"]],
        "vendas": linhas(blocos["vendas"]),
        "servicos": linhas(blocos["servicos"]),
        "sem_classificacao": linhas(blocos["sem_classificacao"]),
        "rateio": blocos["rateio"],
        # A ordem das linhas também é comportamento (padrão: movimento desc).
        "ordem_vendas": [l["nome"] for l in blocos["vendas"]["linhas"]],
        "ordem_servicos": [l["nome"] for l in blocos["servicos"]["linhas"]],
        "arvore_total": ctx["arvore"]["total"],
        "arvore_primeiro_nivel": {
            i["nome"]: [i["valor"], i["quantidade"]] for i in ctx["arvore"]["itens"]
        },
    }


def _resumo_analise(ctx: dict) -> dict:
    g = ctx["grade"]
    return {
        "total": g["total"],
        "quantidade": g["quantidade"],
        "meses": g["meses"],
        "competencias": g["competencias"],
        "blocos": {
            b["titulo"]: {
                "total": b["total"],
                "linhas": {l["nome"]: [l["total"], l["quantidade"]] for l in b["linhas"]},
                "colunas": {c["competencia"]: [c["total"], c["quantidade"]] for c in b["colunas"]},
            }
            for b in g["blocos"]
        },
    }


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------


@contextmanager
def _banco_temporario(origem: Path):
    """Copia o banco congelado para uma pasta temporária e aponta o app para lá.

    O banco congelado nunca é aberto em modo escrita: o app faz
    `PRAGMA journal_mode=WAL` e `CREATE TABLE IF NOT EXISTS` ao conectar, e a
    Fase 1 vai aplicar migrações — tudo isso acontece na cópia."""
    import app.db as db
    from app.db import abrir_somente_leitura

    pasta = Path(tempfile.mkdtemp(prefix="gsf_golden_"))
    destino = pasta / "golden.db"
    origem_conn = abrir_somente_leitura(origem)
    destino_conn = sqlite3.connect(destino)
    try:
        origem_conn.backup(destino_conn)
    finally:
        destino_conn.close()
        origem_conn.close()

    anterior = db.DB_PATH
    db.DB_PATH = destino
    try:
        yield destino
    finally:
        db.DB_PATH = anterior
        shutil.rmtree(pasta, ignore_errors=True)


def tirar(caminho_db: Path, ate: str | None = None, progresso=print) -> dict:
    """Roda todos os cenários sobre uma cópia de `caminho_db` e devolve a fotografia."""
    from flask import template_rendered

    from tests.conftest import cliente_para

    with _banco_temporario(Path(caminho_db)) as copia:
        with sqlite3.connect(copia) as conn:
            competencias = _competencias_fechadas(conn, ate)

        cliente = cliente_para(copia)
        app = cliente.application
        capturados: list[dict] = []

        def receptor(sender, template, context, **extra):
            capturados.append(context)

        def tela(caminho: str, **params) -> dict:
            capturados.clear()
            url = caminho + ("?" + urlencode(params, doseq=True) if params else "")
            resposta = cliente.get(url)
            if resposta.status_code != 200:
                raise RuntimeError(f"{url} respondeu {resposta.status_code}")
            return capturados[0]

        foto: dict = {"competencias": competencias, "cenarios": {}}
        cen = foto["cenarios"]
        template_rendered.connect(receptor, app)
        try:
            # 1) Telas com os filtros padrão (o que abre ao clicar no menu).
            progresso("telas padrão")
            cen["despesas|padrao"] = _resumo_despesas(tela("/despesas"))
            cen["receitas_vendas|padrao"] = _resumo_receitas(tela("/receitas/vendas"))
            cen["receitas_servicos|padrao"] = _resumo_receitas(tela("/receitas/servicos"))
            cen["dashboard|padrao"] = _resumo_dashboard(tela("/dashboard"))
            cen["analise|padrao"] = _resumo_analise(tela("/analise-receitas"))

            # 2) Empresa × competência. "TODAS" = sem slicer de empresa: o
            #    rateio do Adm mistura empresas, então o consolidado do mês não
            #    é a soma das três — precisa de fotografia própria.
            for empresa in ("TODAS",) + EMPRESAS:
                filtro_emp = {} if empresa == "TODAS" else {"empresa": empresa}
                progresso(f"empresa {empresa}")
                for comp in [None] + competencias:
                    rotulo = f"{empresa}|{comp or 'todas'}"
                    filtro_comp = {"competencia": comp} if comp else {}
                    cen[f"dashboard|{rotulo}"] = _resumo_dashboard(
                        tela("/dashboard", **filtro_emp, **filtro_comp)
                    )
                    cen[f"despesas|{rotulo}"] = _resumo_despesas(
                        tela("/despesas", **filtro_emp, **filtro_comp)
                    )
                    filtro_nota = {**filtro_emp}
                    if comp:
                        filtro_nota["competencia_efetiva"] = comp
                    cen[f"receitas_vendas|{rotulo}"] = _resumo_receitas(
                        tela("/receitas/vendas", **filtro_nota)
                    )
                    cen[f"receitas_servicos|{rotulo}"] = _resumo_receitas(
                        tela("/receitas/servicos", **filtro_nota)
                    )
        finally:
            template_rendered.disconnect(receptor, app)

        # 3) Listas dos funis com os filtros padrão (a cascata sem recorte) e
        #    com empresa marcada (a cascata cortando).
        progresso("funis")
        from app.filtros_coluna import COLUNAS

        for tabela, colunas in COLUNAS.items():
            # Usuários (Fase 2) não são dado do fechamento: o golden fotografa
            # números, e esta tabela só teria o usuário sintético do teste.
            # Diferenças pós-fechamento (Fase 4.2) dependem de um fechamento
            # existir: não são número do fechamento, e têm testes próprios.
            # O detalhe da DRE (Fase 4.3) só existe com período+componente na URL.
            # Alertas (Fase 4.5) dependem da data de hoje e de limites editáveis.
            if tabela in ("usuarios", "diferencas", "dre_linhas", "alertas"):
                continue
            for coluna in colunas:
                for empresa in (None, "MSV"):
                    params = {"tabela": tabela, "coluna": coluna}
                    if empresa and coluna != "empresa":
                        params["empresa"] = empresa
                    r = cliente.get("/api/valores-filtro", query_string=params).get_json()
                    # Desde a Fase 1 a ordem da lista é determinística
                    # (desempate pelo texto cru em filtros_coluna.valores), e
                    # passa a ser julgada pelo golden como está na tela.
                    cen[f"funil|{tabela}|{coluna}|{empresa or 'todas'}"] = r

    return _limpo(foto)


# --------------------------------------------------------------------------
# Comparação: devolve cada diferença com o caminho até ela
# --------------------------------------------------------------------------

TOLERANCIA = 0.005  # meio centavo: abaixo disso é ruído de float, não mudança


def comparar(esperado, obtido, caminho: str = "") -> list[str]:
    """Lista legível de diferenças. Vazia = fotografias iguais ao centavo."""
    difs: list[str] = []
    if isinstance(esperado, dict) and isinstance(obtido, dict):
        for chave in sorted(set(esperado) | set(obtido)):
            aqui = f"{caminho}.{chave}" if caminho else chave
            if chave not in obtido:
                difs.append(f"{aqui}: sumiu (era {_curto(esperado[chave])})")
            elif chave not in esperado:
                difs.append(f"{aqui}: apareceu ({_curto(obtido[chave])})")
            else:
                difs += comparar(esperado[chave], obtido[chave], aqui)
        return difs
    if isinstance(esperado, list) and isinstance(obtido, list):
        if len(esperado) != len(obtido):
            return [f"{caminho}: {len(esperado)} itens -> {len(obtido)} itens"]
        for i, (a, b) in enumerate(zip(esperado, obtido)):
            difs += comparar(a, b, f"{caminho}[{i}]")
        return difs
    numeros = (int, float)
    if (
        isinstance(esperado, numeros)
        and isinstance(obtido, numeros)
        and not isinstance(esperado, bool)
        and not isinstance(obtido, bool)
    ):
        if abs(esperado - obtido) > TOLERANCIA:
            return [f"{caminho}: {esperado} -> {obtido} (diferença {obtido - esperado:+.2f})"]
        return []
    if esperado != obtido:
        return [f"{caminho}: {_curto(esperado)} -> {_curto(obtido)}"]
    return []


def _curto(valor) -> str:
    texto = repr(valor)
    return texto if len(texto) <= 80 else texto[:77] + "..."
