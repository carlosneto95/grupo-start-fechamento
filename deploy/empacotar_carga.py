"""Gera o pacote da CARGA INICIAL do banco (roda no computador, UMA vez).

    .venv\\Scripts\\python deploy\\empacotar_carga.py   ->  dist\\financeiro_carga_AAAAMMDD_HHMM.zip

Conteúdo:
  - data/app.db: cópia CONSISTENTE do banco local (API de backup do SQLite,
    não cópia de arquivo), com os ajustes manuais das notas, os overrides das
    despesas, usuários, fechamentos e auditoria;
  - manifesto.json: contagens e somas por tabela e empresa + o hash do banco.
    O servidor confere a carga contra ele (deploy/conferir_carga.py);
  - tests/golden/esperado/ (base.db, fotografia.json, meta.json): para o golden rodar no
    servidor e provar que as bibliotecas do virtualenv compartilhado dão os
    mesmos números que as daqui.

Este zip tem DADO REAL. Ele vai direto para a sua conta do PythonAnywhere e
depois é apagado dos dois lados — nunca para o git nem para e-mail.

Depois do corte, o servidor é a fonte da verdade: ajuste feito no banco local
depois de gerar este pacote NÃO sobe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def manifesto(banco: Path) -> dict:
    """Números que o servidor tem de reproduzir depois da carga. Mesma função
    usada lá (conferir_carga.py importa daqui), então a comparação é exata."""
    conn = sqlite3.connect(f"file:{banco.as_posix()}?mode=ro", uri=True)
    try:
        tabelas = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        saida = {
            "tabelas": {
                t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tabelas
            }
        }
        # Dinheiro e ajustes manuais por empresa: são o que não pode se perder.
        for tabela in ("contas_pagar", "notas"):
            saida[tabela] = {
                empresa: {"linhas": n, "valor_centavos": v, "considerar_manual": m}
                for empresa, n, v, m in conn.execute(
                    f"SELECT empresa, count(*), coalesce(sum(valor_centavos), 0), "
                    f"count(considerar_manual) FROM {tabela} GROUP BY empresa ORDER BY empresa"
                )
            }
        saida["notas_ajustadas"] = conn.execute(
            "SELECT count(*) FROM notas WHERE competencia_manual IS NOT NULL OR categoria_manual IS NOT NULL"
        ).fetchone()[0]
        saida["versao_esquema"] = conn.execute(
            "SELECT coalesce(max(versao), 0) FROM schema_versao"
        ).fetchone()[0]
        saida["integridade"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return saida
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--banco", default=str(RAIZ / "data" / "app.db"))
    ap.add_argument("--destino", default=str(RAIZ / "dist"))
    args = ap.parse_args()
    origem = Path(args.banco)
    if not origem.exists():
        sys.exit(f"Banco não encontrado: {origem}")

    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "app.db"
        # Backup pela API do SQLite: consistente mesmo com o app aberto.
        fonte, alvo = sqlite3.connect(origem), sqlite3.connect(copia)
        fonte.backup(alvo)
        alvo.close()
        fonte.close()
        dados = manifesto(copia)
        if dados["integridade"] != "ok":
            sys.exit(f"Banco local com problema de integridade: {dados['integridade']}")
        dados["sha256"] = sha256(copia)
        dados["gerado_em"] = datetime.now().isoformat(timespec="seconds")

        destino = Path(args.destino)
        destino.mkdir(parents=True, exist_ok=True)
        pacote = destino / f"financeiro_carga_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copia, "data/app.db")
            z.writestr("manifesto.json", json.dumps(dados, ensure_ascii=False, indent=2))
            esperado = RAIZ / "tests" / "golden" / "esperado"
            for nome in ("base.db", "fotografia.json", "meta.json"):
                if (esperado / nome).exists():
                    z.write(esperado / nome, f"tests/golden/esperado/{nome}")
    print(pacote)
    print(
        f"  contas: {dados['tabelas'].get('contas_pagar')}  notas: {dados['tabelas'].get('notas')}  "
        f"notas ajustadas à mão: {dados['notas_ajustadas']}  esquema v{dados['versao_esquema']}"
    )
    print("  A partir de agora o SERVIDOR é a fonte da verdade: não ajuste nada no banco local.")


if __name__ == "__main__":
    main()
