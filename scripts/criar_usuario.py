"""
Cria um usuário (ou redefine a senha) pelo terminal.

Não existe cadastro público no sistema. O primeiro Admin nasce por aqui; os
demais o Admin cria na tela Usuários.

Uso:
    python scripts/criar_usuario.py --login neto --nome "Neto" --perfil admin
    python scripts/criar_usuario.py --login fulano --nome "Fulano" --perfil financeiro --empresas MSV,GTF
    python scripts/criar_usuario.py --login neto --redefinir-senha

A senha é digitada sem aparecer na tela (getpass): nunca vai para arquivo,
argumento de linha de comando nem histórico do terminal.
"""

import argparse
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from werkzeug.security import generate_password_hash  # noqa: E402

from financeiro import db, usuarios, validacao  # noqa: E402
from financeiro.config.companies import load_companies  # noqa: E402
from financeiro.escopo import PERFIS, SISTEMA  # noqa: E402


def pedir_senha() -> str:
    """Pede duas vezes e aplica a mesma política da tela."""
    while True:
        senha = getpass.getpass("Senha (10 a 128 caracteres, letras e números): ")
        try:
            validacao.senha_nova(senha)
        except validacao.ErroValidacao as e:
            print(f"  {e}")
            continue
        if senha != getpass.getpass("Repita a senha: "):
            print("  As senhas não conferem.")
            continue
        return senha


def main() -> int:
    ap = argparse.ArgumentParser(description="Cria usuário do Fechamento.")
    ap.add_argument("--login", required=True)
    ap.add_argument("--nome")
    ap.add_argument("--perfil", choices=PERFIS)
    ap.add_argument("--empresas", default="", help="separadas por vírgula (Financeiro/Leitura)")
    ap.add_argument("--redefinir-senha", action="store_true")
    a = ap.parse_args()

    db.init_db()  # banco do .env (GSF_BANCO) + migrações pendentes, com backup
    login = validacao.login(a.login)
    existente = usuarios._por_login(login)

    if a.redefinir_senha:
        if existente is None:
            print(f"Usuário {login} não existe.")
            return 1
        senha = pedir_senha()
        # Pelo terminal o próprio dono digita: desbloqueia e NÃO obriga troca.
        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 0, tentativas_falhas = 0,"
                " bloqueado_ate = NULL, sessao_versao = sessao_versao + 1 WHERE id = ?",
                (generate_password_hash(senha), existente["id"]),
            )
            from financeiro import auditoria

            auditoria.registrar(
                conn, "redefinir_senha", "usuario", str(existente["id"]), None, None, None
            )
            conn.commit()
        finally:
            conn.close()
        print(f"Senha de {login} redefinida; bloqueio removido; sessões abertas derrubadas.")
        return 0

    if existente is not None:
        print(f"Usuário {login} já existe. Use --redefinir-senha ou a tela Usuários.")
        return 1
    if not a.nome or not a.perfil:
        print("Informe --nome e --perfil para criar.")
        return 1
    validas = {e.nome for e in load_companies()}
    empresas = [e.strip() for e in a.empresas.split(",") if e.strip()]
    if any(e not in validas for e in empresas):
        print(f"Empresa desconhecida. Válidas: {', '.join(sorted(validas))}")
        return 1
    if a.perfil != "admin" and not empresas:
        print("Financeiro e Leitura precisam de --empresas.")
        return 1

    senha = pedir_senha()
    novo = usuarios.criar(
        SISTEMA,
        login,
        validacao.texto(a.nome, "Nome", maximo=80),
        a.perfil,
        empresas,
        senha,
        trocar=False,
    )
    print(f"Usuário {login} criado (id {novo}, perfil {a.perfil}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
