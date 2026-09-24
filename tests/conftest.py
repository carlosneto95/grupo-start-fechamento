"""Infraestrutura comum dos testes.

Duas regras que valem para toda a suíte:

1. **Nenhum teste toca o banco real.** O `app.db.get_conn()` lê o caminho do
   banco de `app.db.DB_PATH` a cada chamada. Aqui ele é redirecionado para uma
   pasta temporária já na coleta, e todo app de teste nasce de `cliente_para`,
   que passa um banco temporário explícito para a fábrica.

2. **Teste versionado não contém valor real** (regra herdada do Controle de
   Impostos). Os dados daqui são sintéticos: empresas, fornecedores e valores
   inventados. Os números reais ficam só em `tests/golden/esperado/`, fora do git.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import app.db as db  # noqa: E402  (precisa do sys.path acima)

# Redireciona já na coleta: qualquer import que chame init_db() cai aqui, nunca
# em data/app.db. Cada teste que precisa de banco troca de novo por um próprio.
_PASTA_SESSAO = Path(tempfile.mkdtemp(prefix="gsf_testes_"))
db.DB_PATH = _PASTA_SESSAO / "coleta.db"


# Chave só de teste: a fábrica recusa subir sem 32+ caracteres, e os testes não
# podem depender do .env da máquina (o CI não tem .env).
CHAVE_TESTE = "chave-de-teste-" + "x" * 32


def cliente_para(caminho_db: Path, **config):
    """Cliente de teste do Flask apontando para `caminho_db`.

    Ponto ÚNICO de montagem do app nos testes, no golden master e na medição
    de desempenho. Na Fase 0 ele carregava o app.py; desde a Fase 1 chama a
    fábrica criar_app() — e o golden continuou medindo a mesma coisa.

    Os logs vão para a pasta temporária da sessão, não para logs/ do projeto."""
    from app import criar_app

    app = criar_app(
        {
            "SECRET_KEY": CHAVE_TESTE,
            "CAMINHO_BANCO": str(caminho_db),
            "PASTA_LOGS": str(_PASTA_SESSAO / "logs"),
            "PASTA_BACKUPS": str(Path(caminho_db).parent / "backups"),
            "TESTING": True,
            **config,
        }
    )
    return app.test_client()


# --------------------------------------------------------------------------
# Banco sintético
# --------------------------------------------------------------------------


def _conta(empresa, id_, categoria, valor, competencia, **extra):
    """Uma conta a pagar sintética. `categoria` vem no formato do Tiny
    ("PRIMARIA-Sub"), e a separação é feita aqui como o sincronizador faz."""
    primaria, _, sub = (categoria or "").partition("-")
    linha = {
        "empresa": empresa,
        "id": str(id_),
        "fornecedor": extra.get("fornecedor", "Fornecedor X"),
        "data_emissao": extra.get("data_emissao", "05/01/2026"),
        "data_vencimento": extra.get("data_vencimento", "10/01/2026"),
        "data_liquidacao": extra.get("data_liquidacao"),
        "valor": valor,
        "saldo": 0.0,
        "pago": valor,
        "situacao": extra.get("situacao", "pago"),
        "numero_documento": None,
        "categoria": categoria,
        "categoria_primaria": primaria or None,
        "subcategoria": sub or None,
        "centro_custo": None,
        "forma_pagamento": None,
        "forma_pagamento_texto": None,
        "historico": None,
        "competencia": competencia,
        "considerar_manual": extra.get("considerar_manual"),
        "atualizado_em": "2026-01-01T00:00:00+00:00",
    }
    return linha


def _nota(empresa, tipo, id_, categoria, valor, competencia, **extra):
    primaria, _, sub = (categoria or "").partition("-")
    return {
        "empresa": empresa,
        "tipo_nota": tipo,
        "id": str(id_),
        "numero": str(id_),
        "serie": "1",
        "numero_rps": None,
        "data_emissao": extra.get("data_emissao", "15/01/2026"),
        "cliente_nome": extra.get("cliente_nome", "Cliente Y"),
        "cliente_cpf_cnpj": None,
        "valor": valor,
        "situacao": "7",
        "descricao_situacao": extra.get("descricao_situacao", "Emitida DANFE"),
        "vendedor": None,
        "categoria": categoria,
        "categoria_primaria": primaria or None,
        "subcategoria": sub or None,
        "marcadores": None,
        "competencia": competencia,
        "competencia_manual": extra.get("competencia_manual"),
        "categoria_manual": extra.get("categoria_manual"),
        "considerar_manual": extra.get("considerar_manual"),
        "atualizado_em": "2026-01-01T00:00:00+00:00",
    }


def gravar(caminho: Path, contas=(), notas=(), regras=()):
    """Insere as linhas sintéticas direto no SQLite, sem passar pelo upsert —
    o objetivo é montar o estado do banco, não testar a gravação."""
    conn = sqlite3.connect(caminho)
    try:
        for tabela, linhas in (("contas_pagar", contas), ("notas", notas)):
            for linha in linhas:
                colunas = ", ".join(linha)
                marcadores = ", ".join(f":{c}" for c in linha)
                conn.execute(f"INSERT INTO {tabela} ({colunas}) VALUES ({marcadores})", linha)
        conn.executemany("INSERT INTO regras_exclusao (tipo, valor) VALUES (?, ?)", regras)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Banco vazio com o schema atual, isolado por teste."""
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(db, "DB_PATH", caminho)
    db.init_db()
    return caminho


@pytest.fixture
def banco_exemplo(banco):
    """Um grupo em miniatura, com um caso de cada regra do fechamento:
    regra de exclusão, override manual, nota cancelada, ajuste manual de
    competência, as três categorias de Adm, categoria sem receita e conta sem
    categoria. Valores redondos para a conta caber de cabeça."""
    contas = [
        _conta("ALFA", 1, "COMERCIO-Frete", 1000.0, "01/2026", fornecedor="Transportes A"),
        _conta("ALFA", 2, "ADM MSV-Aluguel", 500.0, "01/2026", fornecedor="Imobiliária B"),
        _conta("ALFA", 3, "ADM GERAL-Contador", 2000.0, "01/2026", fornecedor="Contábil C"),
        _conta("BETA", 4, "OBRA X-Material", 3000.0, "01/2026", fornecedor="Loja D"),
        _conta("BETA", 5, "ADM START GTF-Sistema", 900.0, "01/2026", fornecedor="Software E"),
        _conta("BETA", 6, "IMPOSTO-ISS", 777.0, "01/2026", fornecedor="Prefeitura"),
        _conta("BETA", 7, "APORTE-Sócio", 5000.0, "02/2026", fornecedor="Sócio"),
        # Override manual: seria excluída pela regra (IMPOSTO), mas foi marcada.
        _conta("BETA", 8, "IMPOSTO-PIS", 100.0, "02/2026", considerar_manual=1),
        # Override manual ao contrário: seria considerada, mas foi desmarcada.
        _conta("ALFA", 9, "COMERCIO-Frete", 250.0, "02/2026", considerar_manual=0),
        _conta("BETA", 10, "OBRA SEM RECEITA-Material", 400.0, "01/2026"),
        _conta("BETA", 11, None, 60.0, "01/2026", fornecedor="Sem Categoria SA"),
        # Fora da visão (antes de ANO_MINIMO): gravada, mas não aparece.
        _conta("ALFA", 12, "COMERCIO-Frete", 99999.0, "12/2025"),
    ]
    notas = [
        _nota("ALFA", "venda", 101, "COMERCIO-RECEITA", 10000.0, "01/2026"),
        _nota("BETA", "servico", 201, "OBRA X-RECEITA", 20000.0, "01/2026"),
        _nota(
            "BETA",
            "servico",
            202,
            "OBRA X-RECEITA",
            5000.0,
            "01/2026",
            descricao_situacao="Cancelada",
        ),
        # Serviço com competência ajustada à mão: o ERP não tem, a tela mostra 02/2026.
        _nota("BETA", "servico", 203, "OBRA X-RECEITA", 1000.0, None, competencia_manual="02/2026"),
        # Serviço ainda sem competência: precisa aparecer para ser preenchido.
        _nota("BETA", "servico", 204, "OBRA X-RECEITA", 700.0, None),
    ]
    regras = [
        ("categoria_primaria", "APORTE"),
        ("categoria_primaria", "IMPOSTO"),
        ("subcategoria", "APORTE"),
    ]
    gravar(banco, contas, notas, regras)
    return banco


@pytest.fixture
def cliente(banco_exemplo):
    """Cliente de teste do Flask sobre o banco de exemplo."""
    return cliente_para(banco_exemplo)
