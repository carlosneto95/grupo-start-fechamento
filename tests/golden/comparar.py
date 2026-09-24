"""Compara o código atual com o golden e, SÓ se pedido, aceita a mudança.

    .venv\\Scripts\\python -m tests.golden.comparar --rotulo visao-competencia-vazia
    .venv\\Scripts\\python -m tests.golden.comparar --rotulo X --aceitar "motivo explicado"

Sem --aceitar: grava relatorios/golden_diff_<rotulo>.md com cada diferença
(caminho, antes, depois) e a fotografia obtida, e não mexe no golden.

Com --aceitar: a fotografia atual vira a esperada. A anterior é guardada como
fotografia_ate_<rotulo>.json e meta.json ganha uma entrada no histórico com o
motivo — o golden nunca muda sem rastro. Aceitar só depois de explicar cada
diferença (regra do projeto: nenhum número muda sem explicação).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.path.insert(0, str(RAIZ))
    import tests.conftest  # noqa: F401  (desvia o banco antes de tudo)
    from tests.golden import fotografia
    from tests.golden.gerar import ESPERADO

    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", required=True)
    ap.add_argument("--aceitar", metavar="MOTIVO")
    args = ap.parse_args()

    esperado = json.loads((ESPERADO / "fotografia.json").read_text(encoding="utf-8"))
    obtido = json.loads(
        json.dumps(fotografia.tirar(ESPERADO / "base.db", progresso=lambda *_: None))
    )
    difs = fotografia.comparar(esperado, obtido)

    saida = RAIZ / "relatorios"
    saida.mkdir(exist_ok=True)
    (saida / f"golden_obtido_{args.rotulo}.json").write_text(
        json.dumps(obtido, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    por_tela = Counter(d.split(".", 2)[1].split("|")[0] for d in difs if d.startswith("cenarios."))
    linhas = [f"# Golden — {args.rotulo}", "", f"Diferenças: **{len(difs)}**", ""]
    linhas += [f"- {tela}: {n}" for tela, n in por_tela.most_common()]
    linhas += ["", "## Linha a linha", ""] + [f"- `{d}`" for d in difs]
    (saida / f"golden_diff_{args.rotulo}.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"{len(difs)} diferença(s): {dict(por_tela)} -> relatorios/golden_diff_{args.rotulo}.md")

    if args.aceitar:
        anterior = ESPERADO / f"fotografia_ate_{args.rotulo}.json"
        shutil.copy2(ESPERADO / "fotografia.json", anterior)
        (ESPERADO / "fotografia.json").write_text(
            json.dumps(obtido, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        shutil.copy2(saida / f"golden_diff_{args.rotulo}.md", ESPERADO / f"diff_{args.rotulo}.md")
        meta = json.loads((ESPERADO / "meta.json").read_text(encoding="utf-8"))
        meta.setdefault("historico", []).append(
            {
                "em": datetime.now().isoformat(timespec="seconds"),
                "etapa": args.rotulo,
                "motivo": args.aceitar,
                "diferencas": len(difs),
                "anterior": anterior.name,
                "aprovado_pelo_neto": False,
            }
        )
        (ESPERADO / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"Aceito. Anterior guardada em {anterior.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
