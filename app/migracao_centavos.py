"""Migração 3: valores monetários de REAL (float) para INTEGER (centavos).

Roda dentro da transação da migração (app/db.py:migrar). A prova de
reconciliação é feita em DUAS camadas, e qualquer diferença levanta erro — o
que desfaz a transação inteira e deixa o banco como estava (e o backup
verificado já foi gravado antes):

  1. LINHA A LINHA: o centavo gravado pelo SQL (ROUND(valor * 100)) tem de
     ser igual à conversão EXATA feita em Python a partir do texto do float
     (app/dinheiro.para_centavos). E a conversão tem de ser reversível: o
     valor antigo não pode ter mais de 2 casas (senão perderia informação).
  2. POR GRUPO: contagem e soma por tabela × empresa × competência, antes e
     depois, idênticas ao centavo.

Por que os nomes mudam (valor -> valor_centavos): uma coluna chamada `valor`
guardando centavos é uma armadilha — quem ler o banco direto (planilha,
script, DB Browser) veria 12345 e acharia que são R$ 12.345,00. O sufixo
deixa a unidade explícita.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from decimal import Decimal

from app.dinheiro import para_centavos

log = logging.getLogger("app.db")

# (tabela, colunas monetárias, expressão da competência usada no agrupamento)
TABELAS = (
    ("contas_pagar", ("valor", "saldo", "pago"), "competencia"),
    ("notas", ("valor",), "COALESCE(competencia_manual, competencia)"),
)


class ReconciliacaoFalhou(RuntimeError):
    """Os números antes e depois não bateram: a migração é desfeita."""


def _chave_primaria(tabela: str) -> str:
    return "empresa, id" if tabela == "contas_pagar" else "empresa, tipo_nota, id"


def _fotografar_antes(conn, tabela, colunas, competencia):
    """{pk: {coluna: centavos exatos}} e {(empresa, competencia, coluna): [n, soma]}."""
    pk = _chave_primaria(tabela)
    por_linha, por_grupo = {}, defaultdict(lambda: [0, 0])
    sql = f"SELECT {pk}, {competencia} AS comp, {', '.join(colunas)} FROM {tabela}"
    for r in conn.execute(sql):
        chave = tuple(r[: pk.count(",") + 1])
        linha = {}
        for c in colunas:
            bruto = r[c]
            if bruto is None:
                linha[c] = None
                continue
            centavos = para_centavos(repr(float(bruto)))
            # Reversível? Se o valor tinha fração de centavo DE VERDADE (ex.:
            # 10.005), converter perderia informação — e a regra é não perder
            # dado do Tiny: aborta. Ruído de float (0.30000000000000004, fruto
            # de uma subtração em Python) não é informação: a diferença fica na
            # 17ª casa. O corte é um milionésimo de real.
            if abs(Decimal(repr(float(bruto))) - Decimal(centavos) / 100) > Decimal("0.000001"):
                raise ReconciliacaoFalhou(
                    f"{tabela} {chave}: {c}={bruto!r} tem mais de 2 casas decimais"
                )
            linha[c] = centavos
            grupo = por_grupo[(r["empresa"], r["comp"], c)]
            grupo[0] += 1
            grupo[1] += centavos
        por_linha[chave] = linha
    return por_linha, dict(por_grupo)


def _executar_varios(conn: sqlite3.Connection, script: str) -> None:
    """Executa comando a comando, DENTRO da transação aberta pela migração.

    Não usar `executescript` aqui: ele faz COMMIT da transação pendente antes
    de rodar (documentação do módulo sqlite3), e a reconciliação que vem
    depois não conseguiria mais desfazer a conversão."""
    for comando in script.split(";\n"):
        if comando.strip():
            conn.execute(comando)


def _recriar(conn, tabela: str) -> None:
    """Recria a tabela com as colunas *_centavos. O restante do esquema é o
    da migração 2, repetido aqui porque o SQLite não altera tipo de coluna."""
    if tabela == "contas_pagar":
        _executar_varios(
            conn,
            """
            CREATE TABLE contas_pagar_nova (
                empresa TEXT NOT NULL CHECK (trim(empresa) <> ''),
                id TEXT NOT NULL CHECK (trim(id) <> ''),
                fornecedor TEXT,
                data_emissao TEXT,
                data_vencimento TEXT,
                data_liquidacao TEXT,
                -- Dinheiro em CENTAVOS inteiros. typeof garante que ninguém
                -- grava 12.5 (float) nem '12,50' (texto) por engano.
                valor_centavos INTEGER CHECK (valor_centavos IS NULL OR typeof(valor_centavos) = 'integer'),
                saldo_centavos INTEGER CHECK (saldo_centavos IS NULL OR typeof(saldo_centavos) = 'integer'),
                pago_centavos INTEGER CHECK (pago_centavos IS NULL OR typeof(pago_centavos) = 'integer'),
                situacao TEXT,
                numero_documento TEXT,
                categoria TEXT,
                categoria_primaria TEXT,
                subcategoria TEXT,
                centro_custo TEXT,
                forma_pagamento TEXT,
                forma_pagamento_texto TEXT,
                historico TEXT,
                competencia TEXT,
                considerar_manual INTEGER CHECK (considerar_manual IS NULL OR considerar_manual IN (0, 1)),
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (empresa, id)
            );
            INSERT INTO contas_pagar_nova
            SELECT empresa, id, fornecedor, data_emissao, data_vencimento, data_liquidacao,
                   CAST(ROUND(valor * 100) AS INTEGER),
                   CAST(ROUND(saldo * 100) AS INTEGER),
                   CAST(ROUND(pago * 100) AS INTEGER),
                   situacao, numero_documento, categoria, categoria_primaria, subcategoria,
                   centro_custo, forma_pagamento, forma_pagamento_texto, historico, competencia,
                   considerar_manual, atualizado_em
            FROM contas_pagar;
            DROP TABLE contas_pagar;
            ALTER TABLE contas_pagar_nova RENAME TO contas_pagar;
            CREATE INDEX ix_contas_ano_competencia ON contas_pagar (substr(competencia, 4, 4));
            CREATE INDEX ix_contas_competencia ON contas_pagar (competencia);
            CREATE INDEX ix_contas_categoria ON contas_pagar (categoria_primaria, subcategoria);
            CREATE INDEX ix_contas_fornecedor ON contas_pagar (fornecedor);
            """.replace("\n            ", "\n"),
        )
    else:
        _executar_varios(
            conn,
            """
            CREATE TABLE notas_nova (
                empresa TEXT NOT NULL CHECK (trim(empresa) <> ''),
                tipo_nota TEXT NOT NULL CHECK (tipo_nota IN ('venda', 'servico')),
                id TEXT NOT NULL CHECK (trim(id) <> ''),
                numero TEXT,
                serie TEXT,
                numero_rps TEXT,
                data_emissao TEXT,
                cliente_nome TEXT,
                cliente_cpf_cnpj TEXT,
                valor_centavos INTEGER CHECK (valor_centavos IS NULL OR typeof(valor_centavos) = 'integer'),
                situacao TEXT,
                descricao_situacao TEXT,
                vendedor TEXT,
                categoria TEXT,
                categoria_primaria TEXT,
                subcategoria TEXT,
                marcadores TEXT,
                competencia TEXT,
                competencia_manual TEXT CHECK (
                    competencia_manual IS NULL
                    OR (competencia_manual GLOB '[0-1][0-9]/[0-9][0-9][0-9][0-9]'
                        AND substr(competencia_manual, 1, 2) BETWEEN '01' AND '12')
                ),
                categoria_manual TEXT CHECK (categoria_manual IS NULL OR trim(categoria_manual) <> ''),
                considerar_manual INTEGER CHECK (considerar_manual IS NULL OR considerar_manual IN (0, 1)),
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (empresa, tipo_nota, id)
            );
            INSERT INTO notas_nova
            SELECT empresa, tipo_nota, id, numero, serie, numero_rps, data_emissao, cliente_nome,
                   cliente_cpf_cnpj, CAST(ROUND(valor * 100) AS INTEGER), situacao,
                   descricao_situacao, vendedor, categoria, categoria_primaria, subcategoria,
                   marcadores, competencia, competencia_manual, categoria_manual,
                   considerar_manual, atualizado_em
            FROM notas;
            DROP TABLE notas;
            ALTER TABLE notas_nova RENAME TO notas;
            CREATE INDEX ix_notas_competencia_efetiva ON notas (COALESCE(competencia_manual, competencia));
            CREATE INDEX ix_notas_tipo ON notas (tipo_nota, empresa);
            """.replace("\n            ", "\n"),
        )


def _conferir_depois(conn, tabela, colunas, competencia, por_linha, por_grupo) -> int:
    pk = _chave_primaria(tabela)
    novas = [f"{c}_centavos" for c in colunas]
    grupos = defaultdict(lambda: [0, 0])
    vistas = 0
    sql = f"SELECT {pk}, {competencia} AS comp, {', '.join(novas)} FROM {tabela}"
    for r in conn.execute(sql):
        chave = tuple(r[: pk.count(",") + 1])
        esperado = por_linha.get(chave)
        if esperado is None:
            raise ReconciliacaoFalhou(f"{tabela} {chave}: linha nova que não existia antes")
        for c in colunas:
            obtido = r[f"{c}_centavos"]
            if obtido != esperado[c]:
                raise ReconciliacaoFalhou(
                    f"{tabela} {chave}: {c} {esperado[c]} centavos antes, {obtido} depois"
                )
            if obtido is not None:
                g = grupos[(r["empresa"], r["comp"], c)]
                g[0] += 1
                g[1] += obtido
        vistas += 1
    if vistas != len(por_linha):
        raise ReconciliacaoFalhou(f"{tabela}: {len(por_linha)} linhas antes, {vistas} depois")
    if dict(grupos) != por_grupo:
        difs = {k for k in set(grupos) | set(por_grupo) if grupos.get(k) != por_grupo.get(k)}
        raise ReconciliacaoFalhou(f"{tabela}: soma por grupo divergiu em {sorted(difs)[:5]}")
    return vistas


def migrar_para_centavos(conn: sqlite3.Connection) -> dict:
    """Converte, reconcilia e devolve o resumo (vai para o log)."""
    resumo = {}
    for tabela, colunas, competencia in TABELAS:
        por_linha, por_grupo = _fotografar_antes(conn, tabela, colunas, competencia)
        _recriar(conn, tabela)
        linhas = _conferir_depois(conn, tabela, colunas, competencia, por_linha, por_grupo)
        resumo[tabela] = {"linhas": linhas, "grupos": len(por_grupo)}
        log.info(
            "Centavos: %s reconciliada — %d linhas e %d grupos (empresa × competência × coluna)"
            " idênticos ao centavo",
            tabela,
            linhas,
            len(por_grupo),
        )
    return resumo
