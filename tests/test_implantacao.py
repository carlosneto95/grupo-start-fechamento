"""Deploy (Fase 5): o bloco WSGI, o prefixo /financeiro e o pacote do deploy.

O bloco é executado como no PythonAnywhere — anexado a um WSGI que já tem um
`application` servindo outros sistemas — num PROCESSO SEPARADO, com uma cópia
do código e um .env de teste: no processo do pytest o .env real (que vence o
ambiente) apontaria para o banco de verdade, e o bloco trocaria os módulos
"financeiro" já importados pelos outros testes.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Roda no processo filho. argv: raiz do projeto, pasta temporária, modo.
SIMULACAO = r"""
import json, re, shutil, sys, types
from pathlib import Path

raiz, tmp, modo = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
proj = tmp / "financeiro_proj"
if modo == "ok":
    for pasta in ("financeiro", "templates", "static"):
        shutil.copytree(raiz / pasta, proj / pasta, ignore=shutil.ignore_patterns("__pycache__"))
    (proj / ".env").write_text(
        "GSF_SECRET_KEY=" + "k" * 48 + "\n"
        "GSF_PREFIXO=/financeiro\n"
        f"GSF_BANCO={proj / 'data' / 'app.db'}\n"
        f"GSF_LOGS={proj / 'logs'}\n"
        f"GSF_BACKUPS={proj / 'backups'}\n"
        "GSF_COOKIE_SEGURO=0\n",
        encoding="utf-8",
    )
else:
    proj.mkdir(parents=True)  # pasta vazia: o import de "financeiro" falha

# Outro sistema do processo já carregou um pacote "app" e o importa de novo
# durante as requisições: tem de continuar sendo o dele depois do nosso bloco.
outro = types.ModuleType("app")
outro.SOU_O_OUTRO = True
sys.modules["app"] = outro

def anterior(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"SISTEMA ANTERIOR " + environ.get("PATH_INFO", "").encode()]

codigo = (raiz / "deploy" / "bloco_wsgi_financeiro.py").read_text(encoding="utf-8")
codigo = codigo.replace("__CAMINHO_DO_PROJETO__", proj.as_posix())
wsgi = {"application": anterior}
exec(compile(codigo, "wsgi", "exec"), wsgi)

fin = sys.modules.get("financeiro")
saida = {"origem_financeiro": getattr(fin, "__file__", None),
         "app_do_outro_intacto": getattr(sys.modules.get("app"), "SOU_O_OUTRO", False),
         "anterior_mantido": wsgi["application"] is anterior}
from werkzeug.test import Client
c = Client(wsgi["application"])
saida["outro_sistema"] = c.get("/outro/painel").get_data(as_text=True)

if modo == "ok":
    from financeiro import usuarios
    from financeiro.escopo import SISTEMA
    with wsgi["_fin_app"].app_context():
        usuarios.criar(SISTEMA, "neto", "Neto", "admin", [], "Senha-de-teste-123", trocar=False)
    r = c.get("/financeiro/pendencias")
    saida["sem_login"] = r.headers.get("Location")
    pagina = c.get("/financeiro/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', pagina).group(1)
    r = c.post("/financeiro/login?proximo=/pendencias",
               data={"login": "neto", "senha": "Senha-de-teste-123", "csrf_token": token})
    saida["depois_do_login"] = r.headers.get("Location")
    saida["cookie"] = r.headers.get("Set-Cookie")
    r = c.get("/financeiro/pendencias")
    html = r.get_data(as_text=True)
    saida["pendencias"] = r.status_code
    saida["links_com_prefixo"] = 'href="/financeiro/despesas"' in html and "/financeiro/static/" in html
print(json.dumps(saida))
"""


def _simular(tmp_path, modo):
    r = subprocess.run(
        [sys.executable, "-c", SIMULACAO, str(RAIZ), str(tmp_path), modo],
        capture_output=True,
        text=True,
        timeout=120,
        # Isolamento de verdade: sem nenhuma GSF_* herdada, com a pasta
        # temporária como diretório atual e sem o diretório atual no sys.path
        # (PYTHONSAFEPATH). Sem isso, com a cópia vazia (teste de falha), o
        # Python achava o pacote REAL pela pasta do projeto e subia o sistema
        # com o .env e o banco reais.
        cwd=tmp_path,
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("GSF_")},
            "PYTHONSAFEPATH": "1",
        },
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1]), r.stderr


def test_bloco_wsgi_monta_em_financeiro_sem_tocar_nos_outros(tmp_path):
    s, _ = _simular(tmp_path, "ok")
    assert "financeiro_proj" in s["origem_financeiro"], "importou o pacote real, não a cópia"
    assert s["app_do_outro_intacto"], "o pacote 'app' do outro sistema foi trocado"
    assert s["outro_sistema"] == "SISTEMA ANTERIOR /outro/painel"
    # Sem login, a volta leva o caminho interno; depois do login, o prefixo
    # é somado (o defeito que o Impostos achou no deploy dele).
    assert s["sem_login"].startswith("/financeiro/login?proximo=/pendencias")
    assert s["depois_do_login"] == "/financeiro/pendencias"
    assert "gsf_sessao=" in s["cookie"] and "Path=/financeiro" in s["cookie"]
    assert s["pendencias"] == 200 and s["links_com_prefixo"]


def test_bloco_wsgi_com_falha_deixa_os_outros_no_ar(tmp_path):
    s, erro = _simular(tmp_path, "falha")
    assert s["origem_financeiro"] is None  # não achou pacote nenhum: nada real foi aberto
    assert s["anterior_mantido"] and s["app_do_outro_intacto"]
    assert s["outro_sistema"] == "SISTEMA ANTERIOR /outro/painel"
    assert "financeiro" in erro  # o traceback vai para o Error log


@pytest.mark.skipif(not (RAIZ / ".git").exists(), reason="o pacote é gerado no computador, com git")
def test_pacote_do_deploy_so_leva_codigo(tmp_path):
    r = subprocess.run(
        [sys.executable, str(RAIZ / "deploy" / "empacotar.py"), "--destino", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    [pacote] = tmp_path.glob("financeiro_*.zip")
    nomes = zipfile.ZipFile(pacote).namelist()
    assert "financeiro/__init__.py" in nomes and "deploy/instalar.sh" in nomes
    assert "templates/_base.html" in nomes and "static/css/style.css" in nomes
    proibidos = [n for n in nomes if n.endswith((".db", ".env", ".xlsx", ".pkl")) or "/data/" in n]
    assert proibidos == []
    assert not any(n.startswith(("data/", "backups/", "relatorios/")) for n in nomes)
    assert [n for n in nomes if n.startswith("logs/")] == ["logs/.gitkeep"]  # só a pasta
    assert not any("__pycache__" in n for n in nomes)
    assert not any(n.startswith("tests/golden/esperado/") for n in nomes)


def test_scripts_shell_tem_fim_de_linha_unix():
    # CRLF num .sh quebra o bash do PythonAnywhere com "$'\r': command not found".
    for arquivo in (RAIZ / "deploy").glob("*.sh"):
        assert b"\r\n" not in arquivo.read_bytes(), arquivo.name


@pytest.mark.parametrize(
    "nome", ["instalar.sh", "anexar-wsgi.sh", "atualizar.sh", "carregar-banco.sh"]
)
def test_scripts_existem(nome):
    assert (RAIZ / "deploy" / nome).exists()
