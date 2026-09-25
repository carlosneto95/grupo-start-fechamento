"""Congela o golden master: copia o banco e grava a fotografia esperada.

Uso (na raiz do projeto):

    .venv\\Scripts\\python -m tests.golden.gerar                 # usa data/app.db
    .venv\\Scripts\\python -m tests.golden.gerar --db backups\\x.db --ate 08/2026

Grava em tests/golden/esperado/ (FORA do git — são números reais):
  base.db          cópia congelada do banco. O teste roda SEMPRE sobre ela, e
                   não sobre data/app.db: a próxima sincronização muda o banco
                   vivo, e aí o golden acusaria diferença de DADO, não de CÓDIGO.
  fotografia.json  os números que o código atual produz sobre base.db.
  meta.json        de onde e quando veio, e o SHA-256 da base.

Regerar só quando a mudança de número foi explicada e aceita. Regerar para
"fazer o teste passar" anula o juiz.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ESPERADO = Path(__file__).resolve().parent / "esperado"


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def main() -> int:
    sys.path.insert(0, str(RAIZ))
    # Importa o conftest ANTES de tudo: ele desvia o DB_PATH do banco real.
    import tests.conftest  # noqa: F401
    from financeiro.db import abrir_somente_leitura
    from tests.golden import fotografia

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=str(RAIZ / "data" / "app.db"))
    p.add_argument("--ate", help="última competência fechada (MM/AAAA); padrão: última com nota")
    p.add_argument("--forcar", action="store_true", help="sobrescreve um golden já existente")
    args = p.parse_args()

    origem = Path(args.db)
    if (ESPERADO / "fotografia.json").exists() and not args.forcar:
        print(
            "Já existe um golden em tests/golden/esperado/. Regerar apaga o juiz atual;"
            " use --forcar só depois de explicar a diferença."
        )
        return 1

    ESPERADO.mkdir(parents=True, exist_ok=True)
    base = ESPERADO / "base.db"

    # Cópia pela API de backup: consistente mesmo com o banco em WAL e aberto.
    fonte = abrir_somente_leitura(origem)
    alvo = sqlite3.connect(base)
    try:
        fonte.backup(alvo)
        # A cópia herda o modo WAL da origem, e abrir um banco WAL, mesmo só
        # para ler, cria -wal e -shm ao lado. Em modo DELETE a base congelada
        # fica num arquivo só, e o SHA-256 dela não depende de checkpoint.
        alvo.execute("PRAGMA journal_mode=DELETE")
        integridade = alvo.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        alvo.close()
        fonte.close()
    if integridade != "ok":
        print(f"Cópia com integridade {integridade!r}: abortado.")
        return 1

    foto = fotografia.tirar(base, ate=args.ate)
    (ESPERADO / "fotografia.json").write_text(
        json.dumps(foto, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    meta = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "origem": str(origem),
        "sha256_base": sha256(base),
        "competencias": foto["competencias"],
        "cenarios": len(foto["cenarios"]),
    }
    (ESPERADO / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(
        f"Golden gravado: {meta['cenarios']} cenários, "
        f"{meta['competencias'][0]} a {meta['competencias'][-1]}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
