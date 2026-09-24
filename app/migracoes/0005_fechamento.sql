-- Migração 5: fechamento de competência (Fase 4.2).
--
-- Fechar um mês grava uma FOTO: cada conta e nota daquela competência, com
-- valor, se era considerada e a categoria. Depois disso:
--   - o Dashboard continua vivo, mas avisa quando o atual difere do fechado
--     (decisão do Neto: número vivo + alerta);
--   - os ajustes manuais daquele mês ficam travados até um Admin reabrir
--     (decisão do Neto), com motivo e auditoria;
--   - mudança vinda do Tiny não dá para travar (espelho do ERP): aparece como
--     "diferença pós-fechamento", com a linha que mudou.
--
-- A foto é imutável: triggers recusam UPDATE e DELETE nas linhas e no
-- fechamento — a única mudança aceita é a reabertura, uma vez.

CREATE TABLE fechamentos (
    id INTEGER PRIMARY KEY,
    competencia TEXT NOT NULL CHECK (
        competencia GLOB '[0-1][0-9]/[0-9][0-9][0-9][0-9]'
        AND substr(competencia, 1, 2) BETWEEN '01' AND '12'
    ),
    fechado_em TEXT NOT NULL,
    fechado_por TEXT NOT NULL,
    -- Resultado consolidado no momento do fechamento (JSON), para registro.
    resumo TEXT NOT NULL,
    reaberto_em TEXT,
    reaberto_por TEXT,
    motivo_reabertura TEXT,
    CHECK ((reaberto_em IS NULL) = (reaberto_por IS NULL)),
    CHECK (reaberto_em IS NULL OR length(trim(motivo_reabertura)) >= 5)
);
-- No máximo UM fechamento vigente por competência (reaberto não conta).
CREATE UNIQUE INDEX ux_fechamento_vigente ON fechamentos (competencia) WHERE reaberto_em IS NULL;

CREATE TABLE fechamento_linhas (
    fechamento_id INTEGER NOT NULL REFERENCES fechamentos (id),
    tabela TEXT NOT NULL CHECK (tabela IN ('conta', 'nota')),
    empresa TEXT NOT NULL,
    -- conta: id do Tiny; nota: "tipo:id" (a chave da nota inclui o tipo).
    chave TEXT NOT NULL,
    descricao TEXT,                -- fornecedor ou cliente, para a tela de diferenças
    valor_centavos INTEGER CHECK (valor_centavos IS NULL OR typeof(valor_centavos) = 'integer'),
    considerar INTEGER NOT NULL CHECK (considerar IN (0, 1)),
    categoria TEXT,                -- categoria primária (efetiva, no caso da nota)
    PRIMARY KEY (fechamento_id, tabela, empresa, chave)
);
CREATE INDEX ix_fechamento_linhas_empresa ON fechamento_linhas (fechamento_id, empresa);

CREATE TRIGGER fechamento_linhas_sem_update BEFORE UPDATE ON fechamento_linhas
BEGIN SELECT RAISE(ABORT, 'foto do fechamento nao pode ser alterada'); END;
CREATE TRIGGER fechamento_linhas_sem_delete BEFORE DELETE ON fechamento_linhas
BEGIN SELECT RAISE(ABORT, 'foto do fechamento nao pode ser apagada'); END;

-- Fechamento: só a reabertura (uma vez) pode ser gravada; o resto é imutável.
CREATE TRIGGER fechamentos_so_reabre BEFORE UPDATE ON fechamentos
WHEN OLD.reaberto_em IS NOT NULL
  OR NEW.competencia IS NOT OLD.competencia
  OR NEW.fechado_em IS NOT OLD.fechado_em
  OR NEW.fechado_por IS NOT OLD.fechado_por
  OR NEW.resumo IS NOT OLD.resumo
BEGIN SELECT RAISE(ABORT, 'fechamento so aceita a reabertura'); END;
CREATE TRIGGER fechamentos_sem_delete BEFORE DELETE ON fechamentos
BEGIN SELECT RAISE(ABORT, 'fechamento nao pode ser apagado'); END;
