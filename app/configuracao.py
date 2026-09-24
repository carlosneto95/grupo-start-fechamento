"""Configuração do sistema: SÓ do .env do projeto, com prefixo GSF_.

Por que não `os.environ` nem `load_dotenv`: no PythonAnywhere este sistema
divide o processo com outros quatro (/demandas, /fechamento, /adba, /impostos),
e o WSGI da conta põe segredos DELES em `os.environ` — inclusive uma
`SECRET_KEY`. Ler o ambiente herdaria a chave de outro sistema. Por isso:

  1. todo nome tem o prefixo GSF_ (Grupo Start Fechamento);
  2. o arquivo .env deste projeto é lido direto com `dotenv_values`, sem
     tocar em `os.environ` (o `load_dotenv` antigo espalhava os tokens do
     Tiny no ambiente do processo, visíveis para os outros sistemas);
  3. do ambiente, só se aceita o que começa com GSF_ — é o que permite a um
     teste ou à tarefa agendada sobrescrever algo sem editar o arquivo.

Mesmo padrão de `sistema/__init__.py:_variaveis` do Controle de Impostos.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
PREFIXO = "GSF_"

# Tamanho mínimo da SECRET_KEY. 32 caracteres aleatórios já passam de 128 bits
# de entropia com folga; abaixo disso a assinatura do cookie de sessão (Fase 2)
# fica ao alcance de força bruta.
TAMANHO_MINIMO_CHAVE = 32


def variaveis(caminho_env: Path | None = None) -> dict[str, str]:
    """Todas as variáveis GSF_*: primeiro as do ambiente, depois as do .env
    (o arquivo vence, porque é o que o dono do sistema edita de propósito)."""
    valores = {k: v for k, v in os.environ.items() if k.startswith(PREFIXO)}
    arquivo = caminho_env or (RAIZ / ".env")
    if arquivo.exists():
        valores.update(
            {
                k: v
                for k, v in dotenv_values(arquivo).items()
                if k.startswith(PREFIXO) and v is not None
            }
        )
    return valores


def config_flask(sobrescrever: dict | None = None) -> dict:
    """Configuração do Flask. Sem GSF_SECRET_KEY de 32+ caracteres, NÃO sobe.

    `sobrescrever` é para os testes: eles passam chave e banco próprios em vez
    de depender do .env da máquina."""
    v = variaveis()
    cfg = {
        "SECRET_KEY": v.get("GSF_SECRET_KEY", ""),
        "CAMINHO_BANCO": v.get("GSF_BANCO") or str(RAIZ / "data" / "app.db"),
        "PASTA_LOGS": v.get("GSF_LOGS") or str(RAIZ / "logs"),
        # Pasta dos backups automáticos feitos antes de cada migração.
        "PASTA_BACKUPS": v.get("GSF_BACKUPS") or str(RAIZ / "backups"),
        # Quem aparece como autor na auditoria enquanto não existe login (a
        # Fase 2 troca pelo usuário da sessão).
        "USUARIO_PADRAO": v.get("GSF_USUARIO_PADRAO") or "local",
        # Cookie com nome próprio: no PythonAnywhere há outros apps no mesmo
        # domínio, e o nome padrão "session" faria um derrubar o outro.
        "SESSION_COOKIE_NAME": "gsf_sessao",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": v.get("GSF_COOKIE_SEGURO", "1") != "0",
    }
    cfg.update(sobrescrever or {})
    if len(cfg["SECRET_KEY"] or "") < TAMANHO_MINIMO_CHAVE:
        raise RuntimeError(
            "GSF_SECRET_KEY ausente ou curta no .env (mínimo "
            f"{TAMANHO_MINIMO_CHAVE} caracteres). Veja o .env.example."
        )
    return cfg
