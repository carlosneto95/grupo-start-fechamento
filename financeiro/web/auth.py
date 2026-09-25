"""Entrar, sair e trocar a senha."""

from flask import Blueprint, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from financeiro import seguranca, usuarios, validacao

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    # Já logado: não mostra o formulário de novo.
    if request.method == "GET" and session.get("uid"):
        return redirect(url_for("despesas.listar"))

    erro = None
    if request.method == "POST":
        usuario, erro = seguranca.autenticar(request.form.get("login"), request.form.get("senha"))
        if usuario is not None:
            seguranca.iniciar_sessao(usuario)
            # Só caminho interno: um ?proximo=https://site-falso é descartado.
            # O "proximo" é o caminho DENTRO do sistema (request.full_path, sem
            # o prefixo): em produção o sistema mora em /financeiro, e sem
            # somar o script_root o usuário cairia em /despesas na raiz do
            # domínio — que é de outro sistema. url_for já inclui o prefixo.
            proximo = seguranca.destino_seguro(request.args.get("proximo"), "")
            destino = request.script_root + proximo if proximo else url_for("despesas.listar")
            return redirect(destino)
    return render_template("login.html", erro=erro, expirou=request.args.get("expirou") == "1"), (
        401 if erro else 200
    )


@bp.route("/sair", methods=["POST"])
def sair():
    """POST com CSRF: um link <img src="/sair"> num site alheio não derruba a sessão."""
    if g.get("escopo"):
        usuarios.registrar_evento("logout", g.escopo.login, g.escopo.usuario_id)
    seguranca.encerrar_sessao()
    return redirect(url_for("auth.login"))


@bp.route("/trocar-senha", methods=["GET", "POST"])
def trocar_senha():
    erro = None
    if request.method == "POST":
        usuario = usuarios._por_id(g.escopo.usuario_id)
        atual, nova, repetida = (request.form.get(c, "") for c in ("atual", "nova", "repetida"))
        try:
            if not check_password_hash(usuario["senha_hash"], atual):
                raise validacao.ErroValidacao("Senha atual incorreta.")
            validacao.senha_nova(nova)
            if nova != repetida:
                raise validacao.ErroValidacao("As senhas novas não conferem.")
            if nova == atual:
                raise validacao.ErroValidacao("A senha nova precisa ser diferente da atual.")
        except validacao.ErroValidacao as e:
            erro = str(e)
        else:
            usuarios.trocar_senha(usuario["id"], usuario["login"], nova)
            # A troca sobe a versão da sessão (derruba as outras abertas); esta
            # continua, com a versão nova.
            seguranca.iniciar_sessao(usuarios._por_id(usuario["id"]))
            return redirect(url_for("despesas.listar"))
    obrigatoria = bool(usuarios._por_id(g.escopo.usuario_id)["deve_trocar_senha"])
    return render_template("trocar_senha.html", erro=erro, obrigatoria=obrigatoria), (
        400 if erro else 200
    )
