-- Migração 1: o esquema como ele existia antes da Fase 1 (23/09/2026).
--
-- IF NOT EXISTS de propósito: num banco que já existia (o local, com dados
-- reais), esta migração não faz nada — só passa a constar em schema_versao.
-- Num banco novo, cria as tabelas no formato antigo, e as migrações seguintes
-- levam os dois casos ao mesmo ponto.
--
-- NUNCA editar esta migração: ela já foi aplicada. Mudança = nova migração.

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
    forma_pagamento TEXT,
    historico TEXT,
    competencia TEXT,
    considerar_manual INTEGER,
    atualizado_em TEXT NOT NULL,
    forma_pagamento_texto TEXT,
    PRIMARY KEY (empresa, id)
);

CREATE TABLE IF NOT EXISTS notas (
    empresa TEXT NOT NULL,
    tipo_nota TEXT NOT NULL,
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
    categoria TEXT,
    categoria_primaria TEXT,
    subcategoria TEXT,
    marcadores TEXT,
    competencia TEXT,
    competencia_manual TEXT,
    categoria_manual TEXT,
    atualizado_em TEXT NOT NULL,
    considerar_manual INTEGER,
    PRIMARY KEY (empresa, tipo_nota, id)
);

CREATE TABLE IF NOT EXISTS regras_exclusao (
    tipo TEXT NOT NULL,
    valor TEXT NOT NULL,
    PRIMARY KEY (tipo, valor)
);

CREATE TABLE IF NOT EXISTS trava_sincronizacao (
    empresa TEXT PRIMARY KEY,
    dono TEXT NOT NULL,
    iniciada_em TEXT NOT NULL,
    visto_em TEXT NOT NULL
);
