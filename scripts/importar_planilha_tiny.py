"""
Importa uma planilha exportada manualmente do Tiny para o banco.

Serve para completar o que a API não alcança: a busca da API filtra por data de
emissão/vencimento, então conta antiga (emitida em 2021, por exemplo) com
competência recente fica de fora. Já a exportação manual do Tiny permite filtrar
direto POR COMPETÊNCIA, pegando esses casos.

Por padrão só ACRESCENTA o que falta — contas que já existem no banco são
mantidas como vieram da API (que traz mais campos). Use --sobrescrever para
mudar isso.

--campos-planilha é o meio-termo, e é o modo indicado quando o objetivo é trazer
edições feitas no Tiny (categoria renomeada, conta baixada, competência trocada)
para contas que JÁ estão no banco: atualiza a linha existente, mas só nos campos
em que a planilha é a fonte melhor. Ver CAMPOS_PRESERVADOS logo abaixo.

Uso:
    python scripts/importar_planilha_tiny.py "arquivo.xlsx"
    python scripts/importar_planilha_tiny.py "arquivo.xlsx" --sobrescrever
    python scripts/importar_planilha_tiny.py "pasta/*.xls" --campos-planilha
    python scripts/importar_planilha_tiny.py "arquivo.xlsx" --simular   # só mostra o que faria
"""
import re
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.db import init_db
from app.reports.contas_pagar import (
    _extrair_centro_custo,
    _extrair_forma_pagamento,
    _separar_categoria,
    normalizar_forma_pagamento,
)
from app.repositorio_contas_pagar import mapa_por_id, upsert_contas

# A planilha usa rótulos de tela ("Paga"); a API usa códigos ("pago"). Uniformizamos
# para o padrão da API, senão o filtro de situação da tela mostraria as duas versões.
SITUACOES = {
    "paga": "pago",
    "pago": "pago",
    "em aberto": "aberto",
    "aberto": "aberto",
    "cancelada": "cancelada",
    "cancelado": "cancelada",
    "parcial": "parcial",
    "atrasada": "aberto",
}

# Campos em que a API é a fonte melhor e que --campos-planilha NÃO sobrescreve
# numa conta que já existe no banco. Cada um tem um motivo medido, não é gosto:
#
#   historico             A planilha do Tiny troca quebra de linha por espaço. Numa
#                         comparação de 8.507 lançamentos, o texto era idêntico em
#                         100% dos casos a menos das quebras — ou seja, sobrescrever
#                         só perde formatação, não traz informação nenhuma.
#   centro_custo          Derivado do histórico por regex. Sem as quebras de linha a
#                         regex às vezes engole o bloco seguinte, virando
#                         "MANUTENÇÃO BACKSHOP VALOR: R$: 82,50".
#   forma_pagamento_texto Mesma causa: "CARTÃO DE CRÉDITO" virava
#                         "CARTÃO DE CRÉDITO FINAL 0756".
#   forma_pagamento       O campo oficial do ERP existe na planilha e seria um ganho
#                         (preencheria 1.954 vazios), mas não é usado neste sistema —
#                         decisão de 25/08/2026. Fora daqui se mudar de ideia.
#   pago                  O banco guarda `valor - saldo` (documento quitado). A coluna
#                         "Pago" do Tiny é o valor da BAIXA, que inclui juros/multa e
#                         desconto — em 116 linhas dá diferente, e num caso pagou-se
#                         R$ 227,80 num documento de R$ 50,00. São conceitos distintos;
#                         a decisão foi manter o do banco.
#   numero_documento      O Excel converte o campo para número quando ele parece um:
#                         '130,16' chegou como '130.16'.
CAMPOS_PRESERVADOS = (
    "historico",
    "centro_custo",
    "forma_pagamento_texto",
    "forma_pagamento",
    "pago",
    "numero_documento",
)

COLUNAS_ESPERADAS = [
    "ID", "Fornecedor", "Data Emissão", "Data Vencimento",
    "Data Liquidação", "Valor documento", "Saldo", "Situação",
    "Número documento", "Categoria", "Histórico", "Pago", "Competência",
    "Forma Pagamento",
]


def _data_br(valor):
    # dayfirst: a exportação bruta do Tiny vem "dd/mm/aaaa"; o consolidado em
    # xlsx vem como data. Sem isso, 03/07/2026 viraria 7 de março.
    d = pd.to_datetime(valor, errors="coerce", dayfirst=True)
    return None if pd.isna(d) else d.strftime("%d/%m/%Y")


def _competencia(valor):
    """Aceita os dois formatos que o Tiny exporta: texto "MM/AAAA" (exportação
    direta) ou data (planilha consolidada)."""
    texto = str(valor or "").strip()
    if re.fullmatch(r"\d{2}/\d{4}", texto):
        return texto
    d = pd.to_datetime(valor, errors="coerce", dayfirst=True)
    return None if pd.isna(d) else d.strftime("%m/%Y")


def _numero(valor):
    try:
        return None if pd.isna(valor) else round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def _texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    return texto or None


def linha_da_planilha(registro: dict) -> dict:
    historico = _texto(registro.get("Histórico"))
    categoria = _texto(registro.get("Categoria"))
    primaria, sub = _separar_categoria(categoria)
    situacao = _texto(registro.get("Situação")) or ""

    return {
        "empresa": _texto(registro.get("Empresa")),
        "id": str(registro.get("ID")).strip(),
        "fornecedor": _texto(registro.get("Fornecedor")),
        "data_emissao": _data_br(registro.get("Data Emissão")),
        "data_vencimento": _data_br(registro.get("Data Vencimento")),
        "data_liquidacao": _data_br(registro.get("Data Liquidação")),
        "valor": _numero(registro.get("Valor documento")),
        "saldo": _numero(registro.get("Saldo")),
        "pago": _numero(registro.get("Pago")),
        "situacao": SITUACOES.get(situacao.lower(), situacao.lower() or None),
        "numero_documento": _texto(registro.get("Número documento")),
        "categoria": categoria,
        "categoria_primaria": primaria,
        "subcategoria": sub,
        "centro_custo": _extrair_centro_custo(historico),
        # A planilha traz o campo oficial do ERP, que tem precedência sobre o que
        # a gente infere do histórico. Se vier vazio, cai para a inferência.
        "forma_pagamento": (_texto(registro.get("Forma Pagamento"))
                            or normalizar_forma_pagamento(_extrair_forma_pagamento(historico))),
        "forma_pagamento_texto": _extrair_forma_pagamento(historico),
        "historico": historico,
        "competencia": _competencia(registro.get("Competência")),
    }


def todas_empresas() -> list[str]:
    from app.config.companies import load_companies
    return [e.nome for e in load_companies()]


def _empresa_do_nome(caminho: Path, empresas: list[str]) -> str | None:
    """A exportação direta do Tiny não traz a empresa; costuma vir no nome do
    arquivo (ex: "contas_pagar_... - MSV.xls")."""
    nome = caminho.stem.upper()
    for empresa in empresas:
        if empresa.upper() in nome:
            return empresa
    return None


def _ler_planilha(caminho: Path):
    """Lê .xlsx ou .xls. O .xls do Tiny vem com o cabeçalho OLE marcado como
    corrompido, mas o conteúdo é legível — daí o ignore_workbook_corruption."""
    if caminho.suffix.lower() == ".xls":
        return pd.read_excel(caminho, engine="xlrd",
                             engine_kwargs={"ignore_workbook_corruption": True})
    return pd.read_excel(caminho)


def _mesclar(da_planilha: dict, do_banco: dict | None) -> dict:
    """A linha que vai ser gravada no modo --campos-planilha.

    Conta nova entra inteira. Conta que já existe recebe os campos da planilha,
    menos os de CAMPOS_PRESERVADOS, que continuam com o valor que a API gravou.

    `pago` é caso à parte: ele está preservado, mas numa conta NOVA não há valor
    antigo para preservar, e a coluna "Pago" da planilha tem outro significado
    (valor da baixa, com juros e desconto). Então para conta nova ele é
    recalculado como `valor - saldo`, que é a definição que o resto do banco usa
    — senão a coluna ficaria com dois conceitos misturados dentro dela."""
    if do_banco is None:
        nova = dict(da_planilha)
        valor, saldo = nova.get("valor"), nova.get("saldo")
        nova["pago"] = (valor - saldo) if valor is not None and saldo is not None else None
        return nova

    mesclada = dict(da_planilha)
    for campo in CAMPOS_PRESERVADOS:
        mesclada[campo] = do_banco.get(campo)
    return mesclada


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    sobrescrever = "--sobrescrever" in sys.argv
    campos_planilha = "--campos-planilha" in sys.argv
    simular = "--simular" in sys.argv

    if not argumentos:
        print(__doc__)
        return

    # Os dois modos decidem a mesma coisa (o que fazer com linha que já existe)
    # de formas incompatíveis. Deixar passar significaria um deles vencer em
    # silêncio, e o usuário só descobriria olhando o banco depois.
    if sobrescrever and campos_planilha:
        print("--sobrescrever e --campos-planilha se contradizem. Escolha um.")
        return

    caminhos = []
    for padrao in argumentos:
        encontrados = sorted(Path().glob(padrao)) if any(c in padrao for c in "*?") else [Path(padrao)]
        caminhos.extend(p for p in encontrados if p.exists())
    if not caminhos:
        print(f"Nenhum arquivo encontrado para: {' '.join(argumentos)}")
        return

    init_db()
    empresas_conhecidas = todas_empresas()

    todas_linhas = []
    for caminho in caminhos:
        df = _ler_planilha(caminho)
        if "Empresa" not in df.columns:
            empresa = _empresa_do_nome(caminho, empresas_conhecidas)
            if not empresa:
                print(f"  {caminho.name}: não identifiquei a empresa — inclua o nome "
                      f"no arquivo (ex: '... - MSV.xls'). Pulando.")
                continue
            df["Empresa"] = empresa

        faltando = [c for c in COLUNAS_ESPERADAS if c not in df.columns]
        if faltando:
            print(f"  {caminho.name}: faltam colunas {faltando}. Pulando.")
            continue

        linhas = [linha_da_planilha(r) for r in df.to_dict(orient="records")]
        sem_comp = [l for l in linhas if not l["competencia"]]
        if sem_comp:
            print(f"  {caminho.name}: {len(sem_comp)} linha(s) sem competência — ignoradas.")
            linhas = [l for l in linhas if l["competencia"]]
        print(f"  {caminho.name}: {len(linhas)} linha(s)")
        todas_linhas.extend(linhas)

    if not todas_linhas:
        print("\nNada a importar.")
        return

    # As exportações do Tiny vêm paginadas em 500 linhas, então o mesmo
    # lançamento pode aparecer em mais de um arquivo.
    unicas = {}
    for l in todas_linhas:
        unicas[(l["empresa"], l["id"])] = l
    repetidas = len(todas_linhas) - len(unicas)
    linhas = list(unicas.values())

    print(f"\n{len(linhas)} lançamento(s) únicos"
          + (f" ({repetidas} repetidos entre arquivos)" if repetidas else ""))
    print(f"competências: {', '.join(sorted({l['competencia'] for l in linhas}))}\n")

    total_novas = total_existentes = 0
    for empresa in sorted({l["empresa"] for l in linhas}):
        do_arquivo = [l for l in linhas if l["empresa"] == empresa]
        no_banco = mapa_por_id(empresa)
        novas = [l for l in do_arquivo if l["id"] not in no_banco]
        existentes = len(do_arquivo) - len(novas)
        total_novas += len(novas)
        total_existentes += existentes

        acao = {(True, False): "sobrescrever", (False, True): "campos da planilha"}.get(
            (sobrescrever, campos_planilha), "manter")
        print(f"{empresa}: {len(do_arquivo)} no arquivo | {existentes} já no banco ({acao}) | {len(novas)} novas")

        if not simular:
            if campos_planilha:
                gravar = [_mesclar(l, no_banco.get(l["id"])) for l in do_arquivo]
            else:
                gravar = do_arquivo if sobrescrever else novas
            if gravar:
                upsert_contas(gravar)

    print()
    if simular:
        print(f"SIMULAÇÃO — nada foi gravado. Seriam adicionados {total_novas} lançamento(s).")
    else:
        gravadas = total_novas + (total_existentes if (sobrescrever or campos_planilha) else 0)
        print(f"Gravados {gravadas} lançamento(s) ({total_novas} novos).")


if __name__ == "__main__":
    main()
