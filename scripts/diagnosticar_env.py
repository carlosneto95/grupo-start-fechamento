"""
Diagnóstico do .env — NÃO imprime nenhum valor, só confirma se o arquivo foi
encontrado e quais variáveis GSF_* estão preenchidas.

Lê pelo mesmo caminho do sistema (app/configuracao.variaveis): arquivo .env
do projeto, só nomes com prefixo GSF_, sem copiar nada para os.environ.

Uso:
    python scripts/diagnosticar_env.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.configuracao import TAMANHO_MINIMO_CHAVE, variaveis  # noqa: E402

CAMPOS = ["GSF_SECRET_KEY", "GSF_BANCO", "GSF_LOGS", "GSF_BACKUPS", "GSF_AMBIENTE"] + [
    f"GSF_EMPRESA{n}_{campo}" for n in (1, 2, 3) for campo in ("NOME", "TINY_API_TOKEN")
]


def main() -> int:
    arquivo = RAIZ / ".env"
    print(f".env esperado em: {arquivo}")
    print(f".env existe? {arquivo.exists()}\n")
    v = variaveis()
    print("Variáveis (sem mostrar o valor):")
    for campo in CAMPOS:
        print(f"  {campo}: {'preenchido' if v.get(campo) else 'vazio/ausente'}")
    chave_ok = len(v.get("GSF_SECRET_KEY", "")) >= TAMANHO_MINIMO_CHAVE
    print(f"\nGSF_SECRET_KEY com {TAMANHO_MINIMO_CHAVE}+ caracteres? {chave_ok}")
    antigas = [k for k in _nomes_no_arquivo(arquivo) if k.startswith("EMPRESA")]
    if antigas:
        print(f"ATENÇÃO: nomes antigos sem prefixo GSF_ no .env, ignorados: {antigas}")
    return 0 if chave_ok else 1


def _nomes_no_arquivo(arquivo: Path) -> list[str]:
    if not arquivo.exists():
        return []
    return [
        linha.split("=", 1)[0].strip()
        for linha in arquivo.read_text(encoding="utf-8").splitlines()
        if "=" in linha and not linha.lstrip().startswith("#")
    ]


if __name__ == "__main__":
    raise SystemExit(main())
