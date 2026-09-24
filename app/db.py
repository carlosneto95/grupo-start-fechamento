"""Conexão e schema do banco SQLite (dados de contas a pagar + regras de exclusão)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS contas_pagar (
    empresa TEXT NOT NULL,
    id TEXT NOT NULL,
    fornecedor TEXT,
    data_emissao TEXT,
    data_vencimento TEXT,
    data_liquidacao TEXT,
    valor REAL,
    saldo REAL,
    pago REAL,
    situacao TEXT,
    numero_documento TEXT,
    categoria TEXT,
    categoria_primaria TEXT,
    subcategoria TEXT,
    centro_custo TEXT,
    -- forma_pagamento: valor padronizado (boleto, pix, credito...) usado nos filtros.
    -- Vem do campo oficial do ERP quando a conta veio de planilha; quando veio só
    -- da API (que não expõe esse campo), é inferido do texto do histórico.
    forma_pagamento TEXT,
    -- o texto cru escrito no histórico, para conferência
    forma_pagamento_texto TEXT,
    historico TEXT,
    competencia TEXT,
    considerar_manual INTEGER,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (empresa, id)
);

-- Receitas: notas fiscais emitidas. São dois tipos com origens diferentes na API
-- (NF-e de venda e NFS-e de serviço), guardados na mesma tabela porque para o
-- fechamento são a mesma coisa: receita.
CREATE TABLE IF NOT EXISTS notas (
    empresa TEXT NOT NULL,
    tipo_nota TEXT NOT NULL,          -- 'venda' ou 'servico'
    id TEXT NOT NULL,
    numero TEXT,
    serie TEXT,
    numero_rps TEXT,
    data_emissao TEXT,
    cliente_nome TEXT,
    cliente_cpf_cnpj TEXT,
    valor REAL,
    situacao TEXT,
    descricao_situacao TEXT,
    vendedor TEXT,
    -- categoria como veio do ERP (só existe em nota de serviço; a de venda vem vazia)
    categoria TEXT,
    categoria_primaria TEXT,
    subcategoria TEXT,
    marcadores TEXT,                  -- só nota de venda; separados por " | "
    -- competência derivada da data de emissão
    competencia TEXT,
    -- Ajustes manuais. Ficam SEPARADOS do que veio do ERP para o banco continuar
    -- espelho fiel do Tiny: o valor de origem nunca é sobrescrito, e ressincronizar
    -- não apaga a edição. A tela usa o manual quando existe, senão o do ERP.
    competencia_manual TEXT,
    categoria_manual TEXT,
    -- Override "considerar/desconsiderar" da linha. NULL = segue a situação do
    -- ERP (cancelada/rejeitada/pendente já entram como desconsideradas).
    considerar_manual INTEGER,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (empresa, tipo_nota, id)
);

CREATE TABLE IF NOT EXISTS regras_exclusao (
    tipo TEXT NOT NULL,
    valor TEXT NOT NULL,
    PRIMARY KEY (tipo, valor)
);

-- Trava para não rodar duas sincronizações da MESMA empresa ao mesmo tempo:
-- elas disputariam a mesma cota de chamadas por minuto e uma faria a outra tomar
-- bloqueio. Empresas diferentes têm contas (e cotas) separadas no Tiny, então
-- podem — e devem — rodar em paralelo.
CREATE TABLE IF NOT EXISTS trava_sincronizacao (
    empresa TEXT PRIMARY KEY,
    dono TEXT NOT NULL,
    iniciada_em TEXT NOT NULL,
    visto_em TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: com empresas sincronizando em paralelo, dois processos podem tentar
    # gravar ao mesmo tempo. Em vez de falhar na hora, espera a vez.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL deixa leitura e escrita conviverem sem uma travar a outra.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
