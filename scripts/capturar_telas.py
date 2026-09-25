"""Captura as telas principais em 1366×768 e conta as linhas visíveis.

    .venv\\Scripts\\python scripts\\capturar_telas.py --rotulo antes
    .venv\\Scripts\\python scripts\\capturar_telas.py --rotulo depois

Critério de aceite da Fase 3: em 1366×768, a tela de Despesas mostra PELO
MENOS o mesmo número de linhas que antes. Para "antes" e "depois" medirem a
mesma coisa, o script:

  - sobe o sistema sobre uma cópia do banco congelado do golden (mesmos
    dados nas duas medições) e entra com um usuário de teste criado na cópia;
  - usa o Chrome instalado (Playwright, channel="chrome"), sem interface;
  - mede a área útil de uma janela maximizada num monitor 1366×768 no
    Windows: 1366 × 643 px (768 menos barra de tarefas ~40 e a moldura do
    Chrome com abas e endereço ~85). O número absoluto depende dessa
    suposição; a COMPARAÇÃO antes × depois não, porque as duas usam a mesma;
  - conta como visível a linha de tabela que cabe INTEIRA na janela sem rolar.

Saída em relatorios/capturas/<rotulo>/ (fora do git: as telas têm dados reais).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

LARGURA, ALTURA = 1366, 643
SENHA = "CapturaDeTela123"

# (nome do arquivo, caminho, seletor das linhas de dados a contar ou None)
TELAS = [
    ("01_despesas", "/despesas", "#tabela-contas tbody tr"),
    ("02_dashboard", "/dashboard", ".bloco-resultado tbody tr"),
    ("03_receitas_vendas", "/receitas/vendas", "#tabela-notas tbody tr"),
    ("04_receitas_servicos", "/receitas/servicos", "#tabela-notas tbody tr"),
    ("05_analise_receitas", "/analise-receitas", "table tbody tr"),
    ("06_sincronizar", "/extracao", None),
    ("07_configuracoes", "/configuracoes/exclusoes", None),
    ("08_usuarios", "/admin/usuarios", None),
    ("09_pendencias", "/pendencias", None),
    ("10_dre", "/dre?ate=7", ".tabela-dre tbody tr"),
    (
        "11_dre_linhas",
        "/dre/linhas?periodo=07/2026&componente=despesa&bloco=servicos",
        "table tbody tr",
    ),
]

# Conta linhas INTEIRAMENTE visíveis na janela, sem rolar.
_CONTAR = """(seletor) => {
    const h = window.innerHeight;
    return [...document.querySelectorAll(seletor)].filter((tr) => {
        if (tr.hidden || tr.offsetParent === null) return false;
        const r = tr.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= h && r.height > 0;
    }).length;
}"""


def _subir_servidor(pasta: Path) -> tuple[str, object]:
    """Sobe o app numa porta livre, numa thread, sobre a cópia do banco."""
    from werkzeug.serving import make_server

    from app import criar_app
    from app.escopo import SISTEMA
    from app import usuarios

    app = criar_app(
        {
            "SECRET_KEY": "captura-de-tela-" + "x" * 32,
            "CAMINHO_BANCO": str(pasta / "captura.db"),
            "PASTA_LOGS": str(pasta / "logs"),
            "PASTA_BACKUPS": str(pasta / "backups"),
            "SESSION_COOKIE_SECURE": False,
        }
    )
    with app.app_context():
        if usuarios._por_login("captura") is None:
            usuarios.criar(SISTEMA, "captura", "Captura", "admin", [], SENHA, trocar=False)
    servidor = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{servidor.server_port}", servidor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", required=True, help="ex.: antes, depois")
    args = ap.parse_args()

    base = RAIZ / "tests" / "golden" / "esperado" / "base.db"
    if not base.exists():
        print("Sem tests/golden/esperado/base.db.")
        return 1
    saida = RAIZ / "relatorios" / "capturas" / args.rotulo
    saida.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    pasta = Path(tempfile.mkdtemp(prefix="gsf_captura_"))
    shutil.copy2(base, pasta / "captura.db")
    url, servidor = _subir_servidor(pasta)
    resultado = {"janela": f"{LARGURA}x{ALTURA}", "telas": {}}
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(channel="chrome", headless=True)
            pagina = navegador.new_page(viewport={"width": LARGURA, "height": ALTURA})
            pagina.goto(url + "/login")
            pagina.wait_for_load_state("networkidle")
            pagina.evaluate("document.fonts.ready")
            pagina.screenshot(path=str(saida / "00_login.png"))
            pagina.fill("input[name=login]", "captura")
            pagina.fill("input[name=senha]", SENHA)
            pagina.click("button[type=submit]")
            pagina.wait_for_load_state("networkidle")
            for nome, caminho, seletor in TELAS:
                pagina.goto(url + caminho)
                pagina.wait_for_load_state("networkidle")
                # Fontes do Google carregadas antes da foto (Fase 3): sem isto
                # a medida seria feita com a fonte substituta.
                pagina.evaluate("document.fonts.ready")
                pagina.screenshot(path=str(saida / f"{nome}.png"))
                visiveis = pagina.evaluate(_CONTAR, seletor) if seletor else None
                resultado["telas"][nome] = {"caminho": caminho, "linhas_visiveis": visiveis}
                print(f"{nome:24} linhas visíveis: {visiveis if visiveis is not None else '—'}")
            navegador.close()
    finally:
        servidor.shutdown()
        shutil.rmtree(pasta, ignore_errors=True)

    (saida / "linhas.json").write_text(json.dumps(resultado, indent=1), encoding="utf-8")
    print(f"Capturas em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
