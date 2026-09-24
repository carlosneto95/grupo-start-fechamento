"""Acesso à tabela de usuários.

Duas famílias de função, de propósito separadas:
  - as de LOGIN (`_por_login`, `_por_id`, `_registrar_tentativa`...), usadas só
    por app/seguranca.py ANTES de existir um escopo (quem está entrando ainda
    não é ninguém);
  - as de ADMINISTRAÇÃO (`listar`, `criar`, `alterar`...), que exigem escopo
    Admin e ficam na auditoria.

Senha: só o hash scrypt do werkzeug é gravado. Nenhuma função devolve o hash
para fora do módulo de segurança.
"""

from __future__ import annotations

from werkzeug.security import generate_password_hash

from app import auditoria
from app.db import agora_brasilia, get_conn
from app.escopo import PERFIS, Escopo, exigir_admin

# Campos que a tela de Admin pode ver (nunca o hash).
_CAMPOS_PUBLICOS = (
    "id, login, nome, perfil, ativo, deve_trocar_senha, tentativas_falhas, "
    "bloqueado_ate, ultimo_login, criado_em"
)


# ---- funções do LOGIN (sem escopo) -------------------------------------------


def _por_login(login: str):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM usuarios WHERE login = ?", (login,)).fetchone()
    finally:
        conn.close()


def _por_id(usuario_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conn.close()


def _empresas(usuario_id: int) -> frozenset[str]:
    conn = get_conn()
    try:
        return frozenset(
            r[0]
            for r in conn.execute(
                "SELECT empresa FROM usuario_empresa WHERE usuario_id = ?", (usuario_id,)
            )
        )
    finally:
        conn.close()


def escopo_de(usuario) -> Escopo:
    """Monta o escopo a partir da linha do BANCO (nunca do cookie)."""
    return Escopo(
        usuario_id=usuario["id"],
        login=usuario["login"],
        perfil=usuario["perfil"],
        empresas=_empresas(usuario["id"]) if usuario["perfil"] != "admin" else frozenset(),
    )


def _atualizar_login(usuario_id: int, campos: dict, evento: str | None, login: str) -> None:
    """Grava o resultado de uma tentativa de login (contador, bloqueio, último
    acesso) e o evento de auditoria, na mesma transação. Os nomes de coluna
    vêm da lista branca abaixo, nunca de fora."""
    permitidos = {"tentativas_falhas", "bloqueado_ate", "ultimo_login"}
    if not set(campos) <= permitidos:
        raise ValueError(f"campo de login não permitido: {set(campos) - permitidos}")
    conn = get_conn()
    try:
        if campos:
            atribuicoes = ", ".join(f"{c} = ?" for c in campos)
            conn.execute(
                f"UPDATE usuarios SET {atribuicoes} WHERE id = ?", (*campos.values(), usuario_id)
            )
        if evento:
            auditoria.registrar(
                conn, evento, "usuario", str(usuario_id), None, None, None, usuario=login
            )
        conn.commit()
    finally:
        conn.close()


def registrar_evento(evento: str, login: str, usuario_id=None, detalhe=None) -> None:
    """Evento de acesso sem alteração de usuário: login inexistente, logout,
    acesso negado."""
    conn = get_conn()
    try:
        auditoria.registrar(
            conn,
            evento,
            "usuario",
            None if usuario_id is None else str(usuario_id),
            None,
            None,
            detalhe,
            usuario=login or "(anônimo)",
        )
        conn.commit()
    finally:
        conn.close()


def trocar_senha(usuario_id: int, login: str, senha_nova: str) -> None:
    """Troca feita pelo PRÓPRIO usuário (validada antes). Sobe a versão da
    sessão: as outras sessões abertas dele caem."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 0,"
            " sessao_versao = sessao_versao + 1 WHERE id = ?",
            (generate_password_hash(senha_nova), usuario_id),
        )
        auditoria.registrar(
            conn, "trocar_senha", "usuario", str(usuario_id), None, None, None, usuario=login
        )
        conn.commit()
    finally:
        conn.close()


# ---- ADMINISTRAÇÃO (escopo Admin) ------------------------------------------------


def listar(escopo) -> list[dict]:
    exigir_admin(escopo)
    conn = get_conn()
    try:
        linhas = [
            dict(r) for r in conn.execute(f"SELECT {_CAMPOS_PUBLICOS} FROM usuarios ORDER BY login")
        ]
        empresas: dict[int, list[str]] = {}
        for r in conn.execute("SELECT usuario_id, empresa FROM usuario_empresa ORDER BY empresa"):
            empresas.setdefault(r[0], []).append(r[1])
    finally:
        conn.close()
    for linha in linhas:
        linha["empresas"] = empresas.get(linha["id"], [])
    return linhas


def obter(escopo, usuario_id: int) -> dict | None:
    return next((u for u in listar(escopo) if u["id"] == usuario_id), None)


def criar(
    escopo, login: str, nome: str, perfil: str, empresas: list[str], senha: str, trocar: bool = True
) -> int:
    """Cria o usuário. Pela tela, a troca no primeiro acesso é OBRIGATÓRIA: a
    senha inicial é conhecida por quem criou. Pelo terminal
    (scripts/criar_usuario.py) o próprio usuário digita a senha, e `trocar`
    pode ser False."""
    exigir_admin(escopo)
    if perfil not in PERFIS:
        raise ValueError(f"perfil inválido: {perfil}")
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO usuarios (login, nome, senha_hash, perfil, deve_trocar_senha, criado_em)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (login, nome, generate_password_hash(senha), perfil, int(trocar), agora_brasilia()),
        )
        novo = cur.lastrowid
        _gravar_empresas(conn, novo, perfil, empresas)
        auditoria.registrar(
            conn,
            "criar_usuario",
            "usuario",
            str(novo),
            None,
            None,
            {"login": login, "nome": nome, "perfil": perfil, "empresas": sorted(empresas)},
        )
        conn.commit()
        return novo
    finally:
        conn.close()


def _gravar_empresas(conn, usuario_id: int, perfil: str, empresas: list[str]) -> None:
    conn.execute("DELETE FROM usuario_empresa WHERE usuario_id = ?", (usuario_id,))
    if perfil != "admin":  # Admin vê todas: não precisa de linha
        conn.executemany(
            "INSERT INTO usuario_empresa (usuario_id, empresa) VALUES (?, ?)",
            [(usuario_id, e) for e in sorted(set(empresas))],
        )


def alterar(
    escopo, usuario_id: int, nome: str, perfil: str, empresas: list[str], ativo: bool
) -> bool:
    """Perfil, empresas e ativo. Sobe a versão da sessão: a mudança vale na
    hora, sem esperar o usuário sair. Admin não rebaixa nem desativa a si
    mesmo (evita trancar o sistema sem Admin)."""
    exigir_admin(escopo)
    antes = obter(escopo, usuario_id)
    if antes is None:
        return False
    if usuario_id == escopo.usuario_id and (perfil != "admin" or not ativo):
        raise ValueError("Você não pode tirar o próprio perfil Admin nem se desativar.")
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE usuarios SET nome = ?, perfil = ?, ativo = ?, sessao_versao = sessao_versao + 1"
            " WHERE id = ?",
            (nome, perfil, int(ativo), usuario_id),
        )
        _gravar_empresas(conn, usuario_id, perfil, empresas)
        auditoria.registrar(
            conn,
            "alterar_usuario",
            "usuario",
            str(usuario_id),
            None,
            {k: antes[k] for k in ("nome", "perfil", "ativo", "empresas")},
            {
                "nome": nome,
                "perfil": perfil,
                "ativo": int(ativo),
                "empresas": sorted(set(empresas)),
            },
        )
        conn.commit()
        return True
    finally:
        conn.close()


def redefinir_senha(escopo, usuario_id: int, senha_provisoria: str) -> bool:
    """Admin define uma senha provisória: desbloqueia, obriga a troca e derruba
    as sessões abertas."""
    exigir_admin(escopo)
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 1, tentativas_falhas = 0,"
            " bloqueado_ate = NULL, sessao_versao = sessao_versao + 1 WHERE id = ?",
            (generate_password_hash(senha_provisoria), usuario_id),
        )
        if not cur.rowcount:
            return False
        auditoria.registrar(conn, "redefinir_senha", "usuario", str(usuario_id), None, None, None)
        conn.commit()
        return True
    finally:
        conn.close()
