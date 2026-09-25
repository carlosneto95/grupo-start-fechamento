"""Migrações, integridade e auditoria (Fase 1, etapa B).

O que precisa ser verdade para o banco de produção sobreviver à subida:
  - um banco NOVO e o banco ANTIGO (sem schema_versao, em WAL) chegam ao
    mesmo esquema;
  - o antigo ganha backup verificado antes de qualquer mudança;
  - uma migração que falha não deixa nada pela metade;
  - os CHECK recusam o que a tela não pode escrever;
  - a auditoria só aceita INSERT e registra toda escrita manual.
"""

import json
import sqlite3

import pytest

from financeiro import db
from tests.conftest import _conta, _nota, gravar


def _banco_legado(caminho):
    """Um banco como o de antes da Fase 1: esquema antigo, sem schema_versao,
    em WAL, com uma linha em cada tabela."""
    conn = sqlite3.connect(caminho)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript((db.PASTA_MIGRACOES / "0001_esquema_inicial.sql").read_text("utf-8"))
    conn.commit()
    conn.close()
    gravar(
        caminho,
        [_conta("ALFA", 1, "COMERCIO-Frete", 10.5, "01/2026", considerar_manual=1)],
        [
            _nota(
                "ALFA",
                "venda",
                9,
                "COMERCIO-RECEITA",
                99.9,
                "01/2026",
                competencia_manual="02/2026",
            )
        ],
        [("categoria_primaria", "APORTE")],
    )


def test_banco_novo_chega_na_versao_final(tmp_path):
    assert db.migrar(tmp_path / "novo.db", tmp_path / "bkp") == db.MIGRACOES[-1][0]
    assert not (tmp_path / "bkp").exists()  # banco vazio não precisa de backup


def test_banco_legado_migra_com_backup_e_sem_perder_dado(tmp_path):
    caminho = tmp_path / "legado.db"
    _banco_legado(caminho)
    db.migrar(caminho, tmp_path / "bkp")

    backups = list((tmp_path / "bkp").glob("*.db"))
    assert len(backups) == 1 and "antes_v1" in backups[0].name

    conn = sqlite3.connect(caminho)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert conn.execute("SELECT considerar_manual FROM contas_pagar").fetchone()[0] == 1
    assert conn.execute("SELECT competencia_manual FROM notas").fetchone()[0] == "02/2026"
    assert conn.execute("SELECT count(*) FROM regras_exclusao").fetchone()[0] == 1
    versoes = [r[0] for r in conn.execute("SELECT versao FROM schema_versao ORDER BY 1")]
    assert versoes == [m[0] for m in db.MIGRACOES]
    conn.close()


def test_segunda_subida_nao_refaz_nada(tmp_path):
    caminho = tmp_path / "x.db"
    _banco_legado(caminho)
    db.migrar(caminho, tmp_path / "bkp")
    db.migrar(caminho, tmp_path / "bkp")
    assert len(list((tmp_path / "bkp").glob("*.db"))) == 1  # sem backup à toa


def test_migracao_que_falha_nao_deixa_nada_pela_metade(tmp_path):
    """Uma nota com tipo inválido viola o CHECK da migração 2: ela inteira
    volta atrás e o banco fica na versão 1, com a tabela antiga intacta."""
    caminho = tmp_path / "ruim.db"
    _banco_legado(caminho)
    gravar(caminho, notas=[_nota("ALFA", "xpto", 10, None, 1.0, "01/2026")])

    with pytest.raises(sqlite3.IntegrityError):
        db.migrar(caminho, tmp_path / "bkp")

    conn = sqlite3.connect(caminho)
    assert conn.execute("SELECT max(versao) FROM schema_versao").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM notas").fetchone()[0] == 2
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "notas_nova" not in tabelas and "auditoria" not in tabelas
    conn.close()


# ---- integridade --------------------------------------------------------------


@pytest.mark.parametrize("competencia", ["13/2026", "00/2026", "7/2026", "2026-07", "  "])
def test_check_recusa_competencia_manual_torta(banco_exemplo, competencia):
    conn = sqlite3.connect(banco_exemplo)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE notas SET competencia_manual=? WHERE id='201'", (competencia,))
    conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE contas_pagar SET considerar_manual=2 WHERE id='1'",
        "UPDATE notas SET considerar_manual=-1 WHERE id='201'",
        "UPDATE notas SET categoria_manual='' WHERE id='201'",
        "INSERT INTO regras_exclusao (tipo, valor) VALUES ('fornecedor', 'X')",
    ],
)
def test_check_recusa_valor_fora_do_dominio(banco_exemplo, sql):
    conn = sqlite3.connect(banco_exemplo)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)
    conn.close()


def test_competencia_suja_do_tiny_continua_aceita(banco_exemplo):
    # Espelho do Tiny: a coluna do ERP não tem CHECK. A sujeira entra e é reportada.
    gravar(banco_exemplo, [_conta("ALFA", 77, "X-Y", 1.0, "07/2800")])


# ---- auditoria -----------------------------------------------------------------


def _auditoria(caminho):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    # Só a trilha dos DADOS: os eventos de usuário (criação do usuário de
    # teste, login) têm teste próprio em test_seguranca.py.
    linhas = [
        dict(r)
        for r in conn.execute("SELECT * FROM auditoria WHERE entidade <> 'usuario' ORDER BY id")
    ]
    conn.close()
    return linhas


def test_auditoria_nao_aceita_update_nem_delete(cliente, banco_exemplo):
    cliente.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    conn = sqlite3.connect(banco_exemplo)
    with pytest.raises(sqlite3.IntegrityError, match="nao pode ser alterada"):
        conn.execute("UPDATE auditoria SET usuario='outro'")
    with pytest.raises(sqlite3.IntegrityError, match="nao pode ser apagada"):
        conn.execute("DELETE FROM auditoria")
    conn.close()


def test_marcar_conta_grava_antes_e_depois(cliente, banco_exemplo):
    cliente.post("/despesas/marcar", json={"empresa": "ALFA", "id": "1", "considerar": False})
    (linha,) = _auditoria(banco_exemplo)
    assert (linha["acao"], linha["entidade"], linha["entidade_id"], linha["empresa"]) == (
        "marcar",
        "conta",
        "1",
        "ALFA",
    )
    assert json.loads(linha["valor_anterior"]) == {"considerar_manual": None}
    assert json.loads(linha["valor_novo"]) == {"considerar_manual": 0}
    assert linha["usuario"] == "teste-admin-todas" and linha["ip"] == "127.0.0.1"


def test_ajuste_de_nota_grava_so_o_campo_mexido(cliente, banco_exemplo):
    cliente.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "03/2026"},
    )
    (linha,) = _auditoria(banco_exemplo)
    assert linha["entidade_id"] == "servico:204"
    assert json.loads(linha["valor_anterior"]) == {"competencia_manual": None}
    assert json.loads(linha["valor_novo"]) == {"competencia_manual": "03/2026"}


def test_ajuste_invalido_nao_grava_nem_audita(cliente, banco_exemplo):
    r = cliente.post(
        "/receitas/ajustar",
        json={"empresa": "BETA", "tipo_nota": "servico", "id": "204", "competencia": "13/2026"},
    )
    assert r.status_code == 400
    assert _auditoria(banco_exemplo) == []


def test_registro_inexistente_devolve_404_sem_auditar(cliente, banco_exemplo):
    r = cliente.post("/despesas/marcar", json={"empresa": "ALFA", "id": "999", "considerar": True})
    assert r.status_code == 404
    r = cliente.post(
        "/receitas/marcar",
        json={"empresa": "ALFA", "tipo_nota": "venda", "id": "999", "considerar": True},
    )
    assert r.status_code == 404
    assert _auditoria(banco_exemplo) == []


def test_regras_de_exclusao_auditam_so_quando_mudam(cliente, banco_exemplo):
    form = {"categoria_primaria": ["APORTE", "IMPOSTO"], "subcategoria": ["APORTE"]}
    cliente.post("/configuracoes/exclusoes", data=form)  # igual ao que já está
    assert _auditoria(banco_exemplo) == []
    form["categoria_primaria"].append("COMERCIO")
    cliente.post("/configuracoes/exclusoes", data=form)
    (linha,) = _auditoria(banco_exemplo)
    assert json.loads(linha["valor_anterior"]) == ["APORTE", "IMPOSTO"]
    assert json.loads(linha["valor_novo"]) == ["APORTE", "COMERCIO", "IMPOSTO"]


def test_regra_inventada_no_formulario_e_ignorada(cliente, banco_exemplo):
    """Fase 2: só vira regra o que existe nas contas ou já é regra. A regra
    antiga de subcategoria APORTE (sem conta atual) continua de pé."""
    form = {"categoria_primaria": ["APORTE", "IMPOSTO", "INVENTADA"], "subcategoria": ["APORTE"]}
    cliente.post("/configuracoes/exclusoes", data=form)
    assert _auditoria(banco_exemplo) == []
    corpo = cliente.get("/configuracoes/exclusoes").get_data(as_text=True)
    assert 'value="APORTE"' in corpo  # a regra antiga aparece para poder ser mantida


def test_somente_leitura_aceita_caminho_com_espaco_e_acento(tmp_path):
    """O projeto mora em "Grupo Start - Fechamento": um URI file: montado à mão
    quebrava com espaço (relatório e golden sobre o caminho absoluto)."""
    pasta = tmp_path / "Grupo Start - Fechamento" / "dados ç"
    pasta.mkdir(parents=True)
    caminho = pasta / "app.db"
    db.migrar(caminho, tmp_path / "bkp")
    conn = db.abrir_somente_leitura(caminho)
    assert (
        conn.execute("SELECT max(versao) FROM schema_versao").fetchone()[0] == db.MIGRACOES[-1][0]
    )
    with pytest.raises(sqlite3.OperationalError):  # e é só leitura mesmo
        conn.execute("DELETE FROM regras_exclusao")
    conn.close()
