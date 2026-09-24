"""Validação de tudo que chega do navegador.

O navegador pode ser manipulado: validação só no HTML ou no JavaScript não
protege nada. Todo campo de escrita passa por uma função daqui ANTES de chegar
ao repositório. Cada função devolve o valor já convertido ou lança
ErroValidacao com mensagem em português, segura para a tela (sem detalhe
interno nem dado de outra empresa).

Mesmo padrão de sistema/validacao.py do Controle de Impostos.
"""

from __future__ import annotations

import re


class ErroValidacao(ValueError):
    """Valor inválido vindo do navegador."""


_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def texto(valor, campo: str, *, maximo: int = 200, obrigatorio: bool = True) -> str:
    """Texto livre: sem espaço nas pontas, com limite e sem caractere de controle."""
    if valor is not None and not isinstance(valor, str):
        raise ErroValidacao(f"{campo}: formato inválido.")
    valor = (valor or "").strip()
    if not valor:
        if obrigatorio:
            raise ErroValidacao(f"{campo}: preenchimento obrigatório.")
        return ""
    if len(valor) > maximo:
        raise ErroValidacao(f"{campo}: no máximo {maximo} caracteres.")
    if _CONTROLE.search(valor):
        raise ErroValidacao(f"{campo}: contém caracteres inválidos.")
    return valor


def escolha(valor, campo: str, opcoes) -> str:
    """Valor de lista fechada (perfil, tipo de nota, empresa)."""
    if valor not in opcoes:
        raise ErroValidacao(f"{campo}: opção inválida.")
    return valor


def id_tiny(valor) -> str:
    """Id de registro do Tiny: só dígitos, até 20. Chega como texto ou número."""
    if isinstance(valor, bool):
        raise ErroValidacao("Id inválido.")
    texto_id = str(valor).strip() if isinstance(valor, (str, int)) else ""
    if not re.fullmatch(r"\d{1,20}", texto_id):
        raise ErroValidacao("Id inválido.")
    return texto_id


def booleano_ou_nulo(valor) -> bool | None:
    """true, false ou null — nada de "sim", 1 ou "false" em texto."""
    if valor is None or isinstance(valor, bool):
        return valor
    raise ErroValidacao("Valor de marcação inválido.")


def competencia(valor, *, vazio_permitido: bool = True) -> str:
    """MM/AAAA com mês 01-12 e ano entre 2000 e 2099. Vazio limpa o ajuste."""
    valor = texto(valor, "Competência", maximo=7, obrigatorio=not vazio_permitido)
    if not valor:
        return ""
    if not re.fullmatch(r"(0[1-9]|1[0-2])/20\d\d", valor):
        raise ErroValidacao("Competência: use MM/AAAA (ex.: 07/2026).")
    return valor


def ano(valor) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ErroValidacao("Ano inválido.") from None
    if not 2000 <= numero <= 2099:
        raise ErroValidacao("Ano inválido.")
    return numero


def login(valor) -> str:
    """Letras minúsculas sem acento, números, ponto, hífen e _ (3 a 40)."""
    valor = texto(valor, "Login", maximo=40).lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", valor):
        raise ErroValidacao("Login: use de 3 a 40 letras sem acento, números, ponto, hífen ou _.")
    return valor


def senha_nova(valor) -> str:
    """Política mínima (a mesma do Impostos): 10 a 128 caracteres, letra e número."""
    valor = valor or ""
    if not isinstance(valor, str) or not 10 <= len(valor) <= 128:
        raise ErroValidacao("Senha: use de 10 a 128 caracteres.")
    if not re.search(r"[A-Za-z]", valor) or not re.search(r"\d", valor):
        raise ErroValidacao("Senha: precisa ter letras e números.")
    return valor


def mascarar_documento(documento: str | None) -> str:
    """CPF de pessoa física mascarado para listagem (LGPD): ***.456.789-**.
    CNPJ (empresa) não é dado pessoal e passa inteiro. Hoje nenhuma tela mostra
    o documento; esta função é o caminho obrigatório se uma passar a mostrar."""
    digitos = re.sub(r"\D", "", documento or "")
    if len(digitos) == 11:
        return f"***.{digitos[3:6]}.{digitos[6:9]}-**"
    return documento or ""
