-- Migração 2: integridade no banco, auditoria e histórico de sincronização.
--
-- O SQLite não acrescenta CHECK a tabela existente: é preciso recriar. O
-- padrão é o da documentação do SQLite ("Making Other Kinds Of Table Schema
-- Changes"): cria a nova, copia, apaga a velha, renomeia. Roda dentro de uma
-- transação (app/db.py:migrar); se um CHECK recusar uma linha existente, TUDO
-- volta atrás e o banco fica como estava.
--
-- O que NÃO ganhou CHECK, de propósito: as colunas que vêm do Tiny. O banco é
-- espelho do ERP — uma competência "07/2800" existe lá e tem de existir aqui
-- para ser reportada. CHECK só nas colunas que ESTE sistema escreve.

-- ---- contas_pagar ------------------------------------------------------
CREATE TABLE contas_pagar_nova (
    empresa TEXT NOT NULL CHECK (trim(empresa) <> ''),
    id TEXT NOT NULL CHECK (trim(id) <> ''),
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
    -- forma_pagamento: valor padronizado (boleto, pix, credito...) usado nos
    -- filtros. forma_pagamento_texto: o texto cru do histórico, para conferência.
    forma_pagamento TEXT,
    forma_pagamento_texto TEXT,
    historico TEXT,
    competencia TEXT,
    -- Override manual: NULL = segue as regras de exclusão; 0/1 = decisão da tela.
    considerar_manual INTEGER CHECK (considerar_manual IS NULL OR considerar_manual IN (0, 1)),
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (empresa, id)
);
INSERT INTO contas_pagar_nova (
    empresa, id, fornecedor, data_emissao, data_vencimento, data_liquidacao, valor, saldo,
    pago, situacao, numero_documento, categoria, categoria_primaria, subcategoria,
    centro_custo, forma_pagamento, forma_pagamento_texto, historico, competencia,
    considerar_manual, atualizado_em)
SELECT
    empresa, id, fornecedor, data_emissao, data_vencimento, data_liquidacao, valor, saldo,
    pago, situacao, numero_documento, categoria, categoria_primaria, subcategoria,
    centro_custo, forma_pagamento, forma_pagamento_texto, historico, competencia,
    considerar_manual, atualizado_em
FROM contas_pagar;
DROP TABLE contas_pagar;
ALTER TABLE contas_pagar_nova RENAME TO contas_pagar;

-- ---- notas ---------------------------------------------------------------
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
    valor REAL,
    situacao TEXT,
    descricao_situacao TEXT,
    vendedor TEXT,
    -- Categoria como veio do ERP (só existe em nota de serviço).
    categoria TEXT,
    categoria_primaria TEXT,
    subcategoria TEXT,
    marcadores TEXT,
    -- Competência do ERP: SEM CHECK (espelho do Tiny, sujeira se reporta).
    competencia TEXT,
    -- Ajustes manuais, SEPARADOS do dado do ERP. Estes a tela escreve, então
    -- o formato é garantido aqui: MM/AAAA com mês de 01 a 12.
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
INSERT INTO notas_nova (
    empresa, tipo_nota, id, numero, serie, numero_rps, data_emissao, cliente_nome,
    cliente_cpf_cnpj, valor, situacao, descricao_situacao, vendedor, categoria,
    categoria_primaria, subcategoria, marcadores, competencia, competencia_manual,
    categoria_manual, considerar_manual, atualizado_em)
SELECT
    empresa, tipo_nota, id, numero, serie, numero_rps, data_emissao, cliente_nome,
    cliente_cpf_cnpj, valor, situacao, descricao_situacao, vendedor, categoria,
    categoria_primaria, subcategoria, marcadores, competencia, competencia_manual,
    categoria_manual, considerar_manual, atualizado_em
FROM notas;
DROP TABLE notas;
ALTER TABLE notas_nova RENAME TO notas;

-- ---- regras_exclusao -------------------------------------------------------
CREATE TABLE regras_exclusao_nova (
    tipo TEXT NOT NULL CHECK (tipo IN ('categoria_primaria', 'subcategoria')),
    valor TEXT NOT NULL CHECK (trim(valor) <> ''),
    PRIMARY KEY (tipo, valor)
);
INSERT INTO regras_exclusao_nova (tipo, valor) SELECT tipo, valor FROM regras_exclusao;
DROP TABLE regras_exclusao;
ALTER TABLE regras_exclusao_nova RENAME TO regras_exclusao;

-- ---- índices dos filtros usados pelas telas -------------------------------
-- O filtro de visão é substr(competencia, 4, 4) >= '2026' (app/visao.py): um
-- índice na MESMA expressão deixa o SQLite pular o que é anterior a 2026.
CREATE INDEX ix_contas_ano_competencia ON contas_pagar (substr(competencia, 4, 4));
CREATE INDEX ix_contas_competencia ON contas_pagar (competencia);
CREATE INDEX ix_contas_categoria ON contas_pagar (categoria_primaria, subcategoria);
CREATE INDEX ix_contas_fornecedor ON contas_pagar (fornecedor);
-- A competência efetiva da nota é o ajuste manual ou, sem ele, a do ERP.
CREATE INDEX ix_notas_competencia_efetiva ON notas (COALESCE(competencia_manual, competencia));
CREATE INDEX ix_notas_tipo ON notas (tipo_nota, empresa);

-- ---- auditoria (append-only) --------------------------------------------
-- Toda escrita manual grava aqui quem, quando, antes e depois. Os triggers
-- impedem UPDATE e DELETE mesmo por engano no código, como no Impostos.
CREATE TABLE auditoria (
    id INTEGER PRIMARY KEY,
    data_hora TEXT NOT NULL,             -- AAAA-MM-DDTHH:MM:SS, horário de Brasília
    usuario TEXT NOT NULL,               -- login (até a Fase 2: GSF_USUARIO_PADRAO)
    acao TEXT NOT NULL,                  -- marcar, ajustar, regras_exclusao...
    entidade TEXT NOT NULL,              -- conta, nota, regras_exclusao
    entidade_id TEXT,
    empresa TEXT,
    valor_anterior TEXT,                 -- JSON
    valor_novo TEXT,                     -- JSON
    ip TEXT
);
CREATE INDEX ix_auditoria_data ON auditoria (data_hora);
CREATE INDEX ix_auditoria_entidade ON auditoria (entidade, entidade_id);
CREATE TRIGGER auditoria_sem_update BEFORE UPDATE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria nao pode ser alterada'); END;
CREATE TRIGGER auditoria_sem_delete BEFORE DELETE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria nao pode ser apagada'); END;

-- ---- histórico de sincronizações -----------------------------------------
-- Uma linha por (execução × empresa × tipo). Responde "quando foi a última
-- sincronização que DEU CERTO", que hoje só se adivinha pelo atualizado_em.
CREATE TABLE sincronizacoes (
    id INTEGER PRIMARY KEY,
    lote TEXT NOT NULL,                  -- mesma execução = mesmo lote (uuid)
    origem TEXT NOT NULL CHECK (origem IN ('tela', 'cli', 'agendada')),
    empresa TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('contas', 'notas')),
    periodo_inicio TEXT,                 -- AAAA-MM-DD
    periodo_fim TEXT,
    forcado INTEGER NOT NULL DEFAULT 0 CHECK (forcado IN (0, 1)),
    iniciada_em TEXT NOT NULL,
    terminada_em TEXT,
    status TEXT NOT NULL CHECK (status IN ('rodando', 'ok', 'erro')),
    encontradas INTEGER,
    novas INTEGER,
    atualizadas INTEGER,
    erro TEXT                            -- mensagem já mascarada (sem token)
);
CREATE INDEX ix_sincronizacoes_empresa ON sincronizacoes (empresa, tipo, iniciada_em);
