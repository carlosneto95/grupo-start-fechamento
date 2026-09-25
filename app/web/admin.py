"""Administração (só Admin): regras de exclusão e usuários."""

import secrets
import sqlite3
import string

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from app import exportar, paineis, usuarios, validacao
from app.config.companies import load_companies
from app.escopo import PERFIS
from app.repositorio_contas_pagar import (
    definir_regras_exclusao,
    listar_regras_exclusao,
    listar_valores_distintos,
)
from app.seguranca import admin_necessario

bp = Blueprint("admin", __name__)


# ---- regras de exclusão ------------------------------------------------------------


@bp.route("/configuracoes/exclusoes", methods=["GET", "POST"])
@admin_necessario
def exclusoes():
    if request.method == "POST":
        # Aceita só o que existe nas contas OU já é regra: um nome inventado no
        # formulário não vira regra, e uma regra antiga cujo valor sumiu das
        # contas (ex.: a subcategoria APORTE) não é apagada em silêncio ao salvar.
        atuais = listar_regras_exclusao()
        conhecidas = {
            tipo: set(listar_valores_distintos(g.escopo, tipo)) | set(atuais.get(tipo, []))
            for tipo in ("categoria_primaria", "subcategoria")
        }
        for tipo, validos in conhecidas.items():
            marcados = [v for v in request.form.getlist(tipo) if v in validos]
            definir_regras_exclusao(g.escopo, tipo, marcados)
        return redirect(url_for("admin.exclusoes"))

    regras = listar_regras_exclusao()
    # A tela lista o que existe nas contas E as regras já gravadas: uma regra
    # cujo valor não tem conta hoje (ex.: subcategoria APORTE) precisa aparecer
    # marcada, senão salvar o formulário a apagaria sem ninguém perceber.
    return render_template(
        "configuracoes_exclusoes.html",
        categorias_primarias=sorted(
            set(listar_valores_distintos(g.escopo, "categoria_primaria"))
            | set(regras.get("categoria_primaria", []))
        ),
        subcategorias=sorted(
            set(listar_valores_distintos(g.escopo, "subcategoria"))
            | set(regras.get("subcategoria", []))
        ),
        categorias_excluidas=set(regras.get("categoria_primaria", [])),
        subcategorias_excluidas=set(regras.get("subcategoria", [])),
    )


# ---- usuários ----------------------------------------------------------------------


def _empresas_disponiveis() -> list[str]:
    """Nomes das empresas como aparecem nos dados (MSV, START, GTF)."""
    return sorted(e.nome for e in load_companies())


def _senha_provisoria() -> str:
    """16 caracteres aleatórios com letra e número (atende a política). É
    mostrada UMA vez ao Admin e o usuário é obrigado a trocá-la no primeiro
    acesso."""
    alfabeto = string.ascii_letters + string.digits
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(16))
        if any(c.isdigit() for c in senha) and any(c.isalpha() for c in senha):
            return senha


def _ler_formulario(novo: bool) -> dict:
    empresas = _empresas_disponiveis()
    dados = {
        "nome": validacao.texto(request.form.get("nome"), "Nome", maximo=80),
        "perfil": validacao.escolha(request.form.get("perfil"), "Perfil", PERFIS),
        "empresas": [
            validacao.escolha(e, "Empresa", empresas) for e in request.form.getlist("empresas")
        ],
        "ativo": request.form.get("ativo") == "1" or novo,
    }
    if novo:
        dados["login"] = validacao.login(request.form.get("login"))
    if dados["perfil"] != "admin" and not dados["empresas"]:
        raise validacao.ErroValidacao("Financeiro e Leitura precisam de ao menos uma empresa.")
    return dados


@bp.route("/admin/usuarios")
@admin_necessario
def usuarios_lista():
    contexto = paineis.usuarios(g.escopo, request.args)
    if exportar.pedido(request.args):
        return exportar.enviar(
            g.escopo,
            "usuarios",
            "Usuários",
            [],
            exportar.COLUNAS_USUARIOS,
            contexto["usuarios"],
            contexto["filtros_coluna"],
        )
    return render_template("usuarios.html", **contexto, secao="usuarios")


@bp.route("/admin/usuarios/novo", methods=["GET", "POST"])
@admin_necessario
def usuario_novo():
    erro, senha = None, None
    if request.method == "POST":
        try:
            dados = _ler_formulario(novo=True)
            senha = _senha_provisoria()
            usuarios.criar(
                g.escopo, dados["login"], dados["nome"], dados["perfil"], dados["empresas"], senha
            )
        except validacao.ErroValidacao as e:
            erro, senha = str(e), None
        except sqlite3.IntegrityError:
            erro, senha = "Já existe um usuário com esse login.", None
        else:
            return render_template(
                "senha_provisoria.html", login=dados["login"], senha=senha, secao="usuarios"
            )
    return render_template(
        "usuario_form.html",
        usuario=None,
        erro=erro,
        perfis=PERFIS,
        empresas=_empresas_disponiveis(),
        form=request.form,
        secao="usuarios",
    ), (400 if erro else 200)


@bp.route("/admin/usuarios/<int:usuario_id>", methods=["GET", "POST"])
@admin_necessario
def usuario_editar(usuario_id: int):
    usuario = usuarios.obter(g.escopo, usuario_id)
    if usuario is None:
        abort(404)
    erro = None
    if request.method == "POST":
        try:
            dados = _ler_formulario(novo=False)
            usuarios.alterar(
                g.escopo,
                usuario_id,
                dados["nome"],
                dados["perfil"],
                dados["empresas"],
                dados["ativo"],
            )
        except (validacao.ErroValidacao, ValueError) as e:
            erro = str(e)
        else:
            return redirect(url_for("admin.usuarios_lista"))
    return render_template(
        "usuario_form.html",
        usuario=usuario,
        erro=erro,
        perfis=PERFIS,
        empresas=_empresas_disponiveis(),
        form=request.form if erro else None,
        secao="usuarios",
    ), (400 if erro else 200)


@bp.route("/admin/usuarios/<int:usuario_id>/senha", methods=["POST"])
@admin_necessario
def usuario_redefinir_senha(usuario_id: int):
    """Gera senha provisória, desbloqueia e obriga a troca no próximo acesso."""
    usuario = usuarios.obter(g.escopo, usuario_id)
    if usuario is None:
        abort(404)
    senha = _senha_provisoria()
    usuarios.redefinir_senha(g.escopo, usuario_id, senha)
    return render_template(
        "senha_provisoria.html", login=usuario["login"], senha=senha, secao="usuarios"
    )
