-- Migração 6: alertas de anomalia (Fase 4.5).
--
-- Os LIMITES dos alertas moram aqui, em tabela, e são editados pelo Admin na
-- tela de Configurações (com auditoria) — nada fixo no código. Os valores
-- iniciais foram calibrados contra o banco real de 25/09/2026:
--   - duplicidade com histórico igual e janela de 7 dias: 9 alertas
--     (sem exigir histórico igual eram mais de mil — placas e ordens de
--     compra diferentes, todos legítimos);
--   - fornecedor novo em 30 dias com total acima de R$ 5.000: 15 fornecedores
--     (primeira aparição em todo o histórico, inclusive antes de 2026);
--   - categoria com variação >= 50% e >= R$ 20.000 contra a média dos 3
--     meses anteriores: 23 alertas de 04 a 08/2026.
-- Tudo inteiro: dinheiro em centavos, percentual inteiro, booleano 0/1.

CREATE TABLE parametros_alerta (
    chave TEXT PRIMARY KEY,
    valor INTEGER NOT NULL CHECK (typeof(valor) = 'integer' AND valor >= 0),
    alterado_em TEXT,
    alterado_por TEXT
);

INSERT INTO parametros_alerta (chave, valor) VALUES
    ('duplicado_janela_dias', 7),
    ('duplicado_exigir_historico_igual', 1),
    ('fornecedor_novo_dias', 30),
    ('fornecedor_novo_valor_minimo_centavos', 500000),
    ('categoria_variacao_pct', 50),
    ('categoria_variacao_valor_minimo_centavos', 2000000);

-- Alerta revisado e dispensado ("é legítimo") some da lista de ativos, mas
-- continua visível no filtro "dispensado", com quem, quando e por quê. A
-- chave identifica o alerta de forma estável entre recálculos (ex.:
-- "duplicado:MSV:123:456"). Reativar apaga a linha — e fica na auditoria.
CREATE TABLE alertas_dispensados (
    chave TEXT PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('duplicado', 'fornecedor_novo', 'categoria')),
    empresa TEXT NOT NULL,
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) >= 5),
    dispensado_em TEXT NOT NULL,
    dispensado_por TEXT NOT NULL
);
