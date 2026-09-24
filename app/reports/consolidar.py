"""Junta os relatórios das 3 empresas em uma única planilha (um embaixo do outro)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def consolidar_planilhas(caminhos: list[Path], coluna_empresa: str = "empresa") -> pd.DataFrame:
    """Lê cada planilha, adiciona a coluna de origem (empresa) e empilha tudo."""
    partes = []
    for caminho in caminhos:
        df = pd.read_excel(caminho)
        df[coluna_empresa] = caminho.stem
        partes.append(df)

    if not partes:
        return pd.DataFrame()

    return pd.concat(partes, ignore_index=True)


def salvar_consolidado(df: pd.DataFrame, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(destino, index=False)
    return destino
