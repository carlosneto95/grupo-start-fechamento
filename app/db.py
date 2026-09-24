"""Conexão com o SQLite e as migrações versionadas do esquema.

Evoluir o banco: criar `app/migracoes/000N_nome.sql` (e, se precisar de
cálculo, uma função Python) e acrescentar a linha em MIGRACOES. NUNCA editar
uma migração já aplicada — o banco de produção já passou por ela.

`migrar()` roda na subida do app (criar_app), faz backup verificado antes de
qualquer migração pendente num banco com dados e aplica cada migração numa
transação única: ou entra inteira, ou o banco fica exatamente como estava.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("app.db")

RAIZ = Path(__file__).resolve().parent.parent
DB_PATH = RAIZ / "data" / "app.db"
PASTA_BACKUPS = RAIZ / "backups"
PASTA_MIGRACOES = Path(__file__).resolve().parent / "migracoes"

# Horário de Brasília. O Brasil não tem horário de verão desde 2019: o
# deslocamento fixo de -3h é exato e dispensa a base tzdata no Windows.
FUSO_BRASILIA = timezone(timedelta(hours=-3))


def agora_brasilia() -> str:
    """'AAAA-MM-DDTHH:MM:SS' no horário de Brasília (padrão do Impostos)."""
    return datetime.now(FUSO_BRASILIA).replace(tzinfo=None).isoformat(timespec="seconds")


def configurar(caminho: str | Path, pasta_backups: str | Path | None = None) -> None:
    """Define o banco do processo. Chamado por criar_app() com o valor de
    GSF_BANCO (ou data/app.db); os testes apontam para uma cópia temporária."""
    global DB_PATH, PASTA_BACKUPS
    DB_PATH = Path(caminho)
    if pasta_backups:
        PASTA_BACKUPS = Path(pasta_backups)


def _abrir(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # timeout: com a sincronização gravando numa thread, a tela pode tentar ler
    # no mesmo instante. Em vez de falhar na hora, espera a vez.
    conn = sqlite3.connect(caminho, timeout=30)
    conn.row_factory = sqlite3.Row
    # O SQLite vem com chave estrangeira DESLIGADA por padrão, conexão a conexão.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def abrir_somente_leitura(caminho: str | Path) -> sqlite3.Connection:
    """Abre o banco SEM poder escrever (relatórios, golden master).

    Usa Path.as_uri(), que codifica espaço e acento: o projeto mora em
    "Grupo Start - Fechamento", e um "file:C:/.../Grupo Start - Fechamento/..."
    montado à mão falha com "unable to open database file"."""
    return sqlite3.connect(Path(caminho).resolve().as_uri() + "?mode=ro", uri=True)


def get_conn() -> sqlite3.Connection:
    """Conexão com o banco configurado.

    Sem `PRAGMA journal_mode=WAL` desde a Fase 1: o banco fica no modo padrão
    (DELETE), o mesmo que o Controle de Impostos usa em produção no
    PythonAnywhere. WAL depende de memória compartilhada entre processos, que
    sistema de arquivos em rede não garante; na dúvida, vale o que já roda lá."""
    return _abrir(Path(DB_PATH))


# --------------------------------------------------------------------------
# Migrações
# --------------------------------------------------------------------------


def _centavos(conn: sqlite3.Connection) -> None:
    """Migração 3: dinheiro em centavos, com prova de reconciliação."""
    from app.migracao_centavos import migrar_para_centavos

    migrar_para_centavos(conn)


# (versão, arquivo .sql ou None, função Python opcional). A função roda DEPOIS
# do SQL, na MESMA transação: se ela levantar erro, o SQL também é desfeito.
MIGRACOES: list[tuple[int, str | None, object]] = [
    (1, "0001_esquema_inicial.sql", None),
    (2, "0002_integridade_auditoria.sql", None),
    (3, None, _centavos),
]


def _tem_dados(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        > 0
    )


def fazer_backup(caminho: Path, motivo: str, pasta: Path | None = None) -> Path:
    """Cópia consistente (API de backup do SQLite, funciona com o banco aberto)
    com PRAGMA integrity_check na CÓPIA. Cópia corrompida não serve de backup:
    aborta antes de qualquer escrita."""
    pasta = Path(pasta or PASTA_BACKUPS)
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(FUSO_BRASILIA).strftime("%Y%m%d_%H%M%S")
    destino = pasta / f"{Path(caminho).stem}_{carimbo}_{motivo}.db"
    origem = sqlite3.connect(caminho, timeout=30)
    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
        resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copia.close()
        origem.close()
    if resultado != "ok":
        raise RuntimeError(f"Backup {destino} com integridade {resultado!r}: abortado.")
    log.info("Backup gravado em %s", destino)
    return destino


def versao_atual(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_versao "
        "(versao INTEGER PRIMARY KEY, aplicado_em TEXT NOT NULL)"
    )
    return conn.execute("SELECT COALESCE(MAX(versao), 0) FROM schema_versao").fetchone()[0]


def migrar(caminho: str | Path | None = None, pasta_backups: str | Path | None = None) -> int:
    """Aplica as migrações pendentes e devolve a versão final do esquema."""
    caminho = Path(caminho or DB_PATH)
    conn = _abrir(caminho)
    try:
        tinha_dados = _tem_dados(conn)
        atual = versao_atual(conn)
        conn.commit()
        pendentes = [m for m in MIGRACOES if m[0] > atual]
        if not pendentes:
            return atual

        if tinha_dados:
            conn.close()
            fazer_backup(caminho, f"antes_v{pendentes[0][0]}", pasta_backups)
            conn = _abrir(caminho)

        # Sai do WAL (se o banco vier dele) antes de tudo: só dá para trocar o
        # modo fora de transação, e as migrações recriam tabelas inteiras.
        conn.execute("PRAGMA journal_mode = DELETE")

        for versao, arquivo, funcao in pendentes:
            script = (PASTA_MIGRACOES / arquivo).read_text(encoding="utf-8") if arquivo else ""
            # Chave estrangeira desligada durante o script: recriar tabela
            # (DROP + RENAME) dispararia a checagem no meio. No fim,
            # foreign_key_check confere que nenhuma referência ficou quebrada.
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.executescript("BEGIN;\n" + script)
                if funcao:
                    funcao(conn)
                quebradas = conn.execute("PRAGMA foreign_key_check").fetchall()
                if quebradas:
                    raise RuntimeError(f"Migração {versao}: referências quebradas {quebradas[:5]}")
                conn.execute(
                    "INSERT INTO schema_versao (versao, aplicado_em) VALUES (?, ?)",
                    (versao, agora_brasilia()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("Migração %s falhou; banco mantido na versão anterior", versao)
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
            log.info("Migração %s aplicada", versao)
        # Recriar tabela (migrações 2 e 3) deixa as páginas antigas livres no
        # arquivo: o banco dobrava de tamanho. VACUUM devolve o espaço; roda
        # fora de transação e só quando alguma migração foi aplicada.
        conn.execute("VACUUM")
        return pendentes[-1][0]
    finally:
        conn.close()


def init_db() -> None:
    """Entrada dos SCRIPTS de linha de comando: banco e pasta de backups vêm do
    .env (GSF_BANCO, GSF_BACKUPS), como no app — antes os scripts gravavam
    sempre em data/app.db, ignorando a configuração. Depois, migra.

    Os testes NÃO usam esta função (ela leria o .env da máquina): chamam
    `migrar(caminho)` com um banco temporário explícito."""
    from app.configuracao import variaveis

    v = variaveis()
    configurar(
        v.get("GSF_BANCO") or RAIZ / "data" / "app.db",
        v.get("GSF_BACKUPS") or RAIZ / "backups",
    )
    migrar()
