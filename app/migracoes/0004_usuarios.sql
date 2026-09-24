-- Migração 4: usuários, perfis e empresas permitidas (Fase 2).
--
-- Mesmo modelo do Controle de Impostos, com o perfil Leitura a mais:
--   admin      — as três empresas, regras de exclusão, sincronização, usuários;
--   financeiro — só as empresas atribuídas; marca e ajusta;
--   leitura    — só as empresas atribuídas; só consulta.
--
-- O perfil e as empresas são LIDOS DO BANCO a cada requisição (app/seguranca.py):
-- o cookie guarda só o id do usuário e a versão da sessão.

CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE
        CHECK (length(login) BETWEEN 3 AND 40 AND login NOT GLOB '*[^a-z0-9._-]*'),
    nome TEXT NOT NULL CHECK (trim(nome) <> ''),
    -- Hash scrypt do werkzeug. A senha em si nunca é gravada.
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'financeiro', 'leitura')),
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    -- 1 = a próxima entrada exige trocar a senha (primeiro acesso, senha redefinida).
    deve_trocar_senha INTEGER NOT NULL DEFAULT 1 CHECK (deve_trocar_senha IN (0, 1)),
    tentativas_falhas INTEGER NOT NULL DEFAULT 0 CHECK (tentativas_falhas >= 0),
    bloqueado_ate TEXT,
    -- Sobe ao trocar senha, perfil, empresas ou ao desativar: derruba as
    -- sessões abertas, que carregam a versão antiga no cookie.
    sessao_versao INTEGER NOT NULL DEFAULT 1,
    ultimo_login TEXT,
    criado_em TEXT NOT NULL
);

-- Empresas que Financeiro e Leitura enxergam. Admin vê todas e não precisa de
-- linha aqui. A empresa é o NOME usado nas tabelas de dados (MSV, START, GTF).
CREATE TABLE usuario_empresa (
    usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    empresa TEXT NOT NULL CHECK (trim(empresa) <> ''),
    PRIMARY KEY (usuario_id, empresa)
);
