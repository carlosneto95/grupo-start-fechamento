"""Log do sistema: arquivo com rotação e máscara de dado sensível.

Detalhe de erro vai para o log, NUNCA para a tela (a tela mostra mensagem
genérica — ver financeiro/__init__.py). Por isso o log precisa ser seguro por si:
um traceback pode carregar a URL da API do Tiny com o token, ou uma linha de
nota com o CPF do cliente. A máscara age em TODA mensagem, antes de gravar,
em vez de confiar que cada chamada lembre de esconder.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Rotação: 5 arquivos de 1 MB. Dá semanas de histórico num sistema deste
# porte e não enche a cota de disco do PythonAnywhere.
TAMANHO_ARQUIVO = 1_000_000
ARQUIVOS_GUARDADOS = 5

# Token do Tiny e qualquer segredo parecido: sequência longa sem espaço.
# 32+ caracteres alfanuméricos não aparecem em mensagem legítima do sistema.
_SEGREDO = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9])")
# Parâmetro nomeado de segredo em URL ou dicionário, mesmo curto: token=abc.
_PARAMETRO = re.compile(
    r"(?i)(token|senha|password|secret|chave)(['\"]?\s*[=:]\s*['\"]?)([^\s&'\",}]+)"
)
# CNPJ antes do CPF: o padrão do CPF casaria com um pedaço do CNPJ.
_CNPJ = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})\b")
_CPF = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")


def mascarar(texto: str) -> str:
    """Esconde segredo e documento. CPF/CNPJ ficam com os dígitos do meio,
    o suficiente para quem lê o log achar a nota sem expor o documento."""
    texto = _PARAMETRO.sub(lambda m: f"{m.group(1)}{m.group(2)}***", texto)
    texto = _SEGREDO.sub("***", texto)
    texto = _CNPJ.sub(lambda m: f"**.{m.group(2)}.***/****-**", texto)
    texto = _CPF.sub(lambda m: f"***.{m.group(2)}.***-**", texto)
    return texto


class FiltroSigilo(logging.Filter):
    """Aplica `mascarar` à mensagem já formatada e ao traceback."""

    def filter(self, registro: logging.LogRecord) -> bool:
        registro.msg = mascarar(registro.getMessage())
        registro.args = ()
        if registro.exc_info:
            # Formata o traceback agora, mascara, e descarta o objeto original
            # para o handler não reformatar a versão sem máscara.
            texto = logging.Formatter().formatException(registro.exc_info)
            registro.exc_text = mascarar(texto)
            registro.exc_info = None
        return True


def configurar(pasta_logs: str | Path, nivel: int = logging.INFO) -> logging.Logger:
    """Liga o log do pacote `app` em logs/app.log. Idempotente: chamar duas
    vezes (testes criam vários apps) não duplica linhas."""
    log = logging.getLogger("financeiro")
    log.setLevel(nivel)
    pasta = Path(pasta_logs)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = str(pasta / "app.log")
    if not any(
        getattr(h, "baseFilename", None) == str(Path(destino).resolve()) for h in log.handlers
    ):
        handler = RotatingFileHandler(
            destino, maxBytes=TAMANHO_ARQUIVO, backupCount=ARQUIVOS_GUARDADOS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(FiltroSigilo())
        log.addHandler(handler)
    return log
