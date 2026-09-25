"""Monta o DataFrame de Contas a Pagar a partir dos registros da API do Tiny.

Nota: a API não retorna "Forma Pagamento" nem "Centro de Custo" como campos
próprios, mas o texto de "historico" embute essas informações (ex: "CENTRO DE
CUSTO: INDÚSTRIA" e "FORMA DE PAGAMENTO\nBOLETO BANCÁRIO"), então extraímos
via regex. "Data Liquidação" vem do campo "liquidacao" (não documentado, mas
presente na resposta real da API). "Pago" é calculado como valor - saldo.
"Chave PIX/Código boleto" continua sem equivalente via API.
"""

from __future__ import annotations

import re
import unicodedata


# O histórico é texto livre. Na API vem com quebras de linha separando os blocos
# ("CENTRO DE CUSTO: X\n\nOBS: ..."), mas na planilha exportada as quebras viram
# espaços. Por isso o corte é não-guloso e para na primeira fronteira que apareça:
# quebra de linha, dois espaços seguidos, ou o início do próximo bloco conhecido.
_FRONTEIRA = r"(?=\n|\s{2,}|\s*(?:OBS|COMPET[EÊ]NCIA|FORMA DE PAGAMENTO|PEDIDO|LINK)\b|$)"
_RE_CENTRO_CUSTO = re.compile(rf"CENTRO DE CUSTO:\s*(.+?){_FRONTEIRA}")
_RE_FORMA_PAGAMENTO = re.compile(rf"FORMA DE PAGAMENTO[:\s]*\n?\s*(.+?){_FRONTEIRA}")


def _extrair_centro_custo(historico: str | None) -> str | None:
    if not historico:
        return None
    m = _RE_CENTRO_CUSTO.search(historico)
    return m.group(1).strip() if m else None


def _extrair_forma_pagamento(historico: str | None) -> str | None:
    if not historico:
        return None
    m = _RE_FORMA_PAGAMENTO.search(historico)
    return m.group(1).strip() if m else None


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def normalizar_forma_pagamento(texto: str | None) -> str | None:
    """Reduz o texto livre do histórico ao vocabulário que o ERP usa.

    Confirmado em 434 contas que existem nas duas fontes: acerta 96,8% das vezes.
    Quando a conta vem de planilha, o campo oficial do ERP tem precedência sobre
    esta inferência."""
    if not texto:
        return None
    t = _sem_acento(texto).upper()
    if "BOLETO" in t:
        return "boleto"
    if "PIX" in t:
        return "pix"
    if "CREDITO" in t or "CARTAO" in t:
        return "credito"
    if "DEBITO" in t:
        return "debito"
    if "DINHEIRO" in t or "ESPECIE" in t:
        return "dinheiro"
    if "DEPOSITO" in t:
        return "deposito"
    if "TRANSFER" in t or "TED" in t or "DOC" in t:
        return "transferencia_bancaria_carteira_digital"
    return "outra"


def _separar_categoria(categoria) -> tuple[str | None, str | None]:
    """ "CATEGORIA-Subcategoria" -> ("CATEGORIA", "Subcategoria"). Separa só no primeiro hífen."""
    if not isinstance(categoria, str) or not categoria:
        return None, None
    if "-" not in categoria:
        return categoria.strip(), None
    primaria, subcategoria = categoria.split("-", 1)
    return primaria.strip(), subcategoria.strip()


def _para_float(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _registro_para_linha(registro: dict, empresa: str) -> dict:
    historico = registro.get("historico")
    valor = _para_float(registro.get("valor"))
    saldo = _para_float(registro.get("saldo"))
    pago = (valor - saldo) if valor is not None and saldo is not None else None
    categoria_primaria, subcategoria = _separar_categoria(registro.get("categoria"))

    return {
        "empresa": empresa,
        "id": registro.get("id"),
        "fornecedor": (registro.get("cliente") or {}).get("nome"),
        "data_emissao": registro.get("data"),
        "data_vencimento": registro.get("vencimento"),
        "data_liquidacao": registro.get("liquidacao"),
        "valor": valor,
        "saldo": saldo,
        "pago": pago,
        "situacao": registro.get("situacao"),
        "numero_documento": registro.get("nro_documento"),
        "categoria": registro.get("categoria"),
        "categoria_primaria": categoria_primaria,
        "subcategoria": subcategoria,
        "centro_custo": _extrair_centro_custo(historico),
        "forma_pagamento": normalizar_forma_pagamento(_extrair_forma_pagamento(historico)),
        "forma_pagamento_texto": _extrair_forma_pagamento(historico),
        "historico": historico,
        "competencia": registro.get("competencia"),
    }
