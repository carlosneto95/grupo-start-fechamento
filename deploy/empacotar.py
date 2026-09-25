"""Gera o zip do CÓDIGO para enviar ao PythonAnywhere (roda no computador).

    .venv\\Scripts\\python deploy\\empacotar.py        ->  dist\\financeiro_AAAAMMDD_HHMM.zip

A lista é de INCLUSÃO e parte do `git ls-files`: só entra arquivo versionado
dentro das pastas listadas. Um arquivo novo sensível que alguém deixe na pasta
(planilha, banco, token) não vai por engano — ele não está no git, e mesmo que
estivesse, as extensões proibidas abortam o pacote inteiro.

NUNCA entram: .env, bancos (.db), planilhas, data/, backups/, relatorios/,
logs/, e os valores reais do golden (tests/golden/esperado/). O banco sobe uma
única vez, pelo pacote de carga (deploy/empacotar_carga.py).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Pastas e arquivos que vão para o servidor. tests/ vai para rodar a suíte lá
# (o golden é pulado sem os valores reais, como no CI; com o pacote de carga
# instalado, ele roda).
INCLUIR = (
    "financeiro/",
    "templates/",
    "static/",
    "scripts/",
    "deploy/",
    "tests/",
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "HISTORICO.md",
    "DEPLOY.md",
    ".env.example",
    "logs/.gitkeep",
)
PROIBIDOS = (".env", ".db", ".sqlite", ".sqlite3", ".xls", ".xlsx", ".xlsm", ".csv", ".pkl", ".log")


def arquivos() -> list[str]:
    saida = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    escolhidos = []
    for nome in saida:
        if not nome.startswith(INCLUIR) or nome.startswith("tests/golden/esperado/"):
            continue
        if nome.endswith(PROIBIDOS) and not nome.endswith(".env.example"):
            sys.exit(f"RECUSADO: arquivo sensível no pacote: {nome}")
        if not (RAIZ / nome).exists():  # apagado localmente, ainda não commitado
            continue
        escolhidos.append(nome)
    return escolhidos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--destino", default=str(RAIZ / "dist"))
    args = ap.parse_args()
    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)
    pacote = destino / f"financeiro_{datetime.now():%Y%m%d_%H%M}.zip"
    lista = arquivos()
    for obrigatorio in ("financeiro/__init__.py", "deploy/instalar.sh", "templates/_base.html"):
        if obrigatorio not in lista:
            sys.exit(f"ERRO: {obrigatorio} fora do pacote (commitou?)")
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
        for nome in lista:
            z.write(RAIZ / nome, nome)
    print(f"{pacote}  ({len(lista)} arquivos)")


if __name__ == "__main__":
    main()
