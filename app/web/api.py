"""Endpoints JSON consumidos pelo JavaScript das telas."""

from flask import Blueprint, g, jsonify, request

from app import paineis

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/valores-filtro")
def valores_filtro():
    """Lista do funil de coluna, carregada só quando o funil abre. Em cascata e
    dentro do escopo: quem só vê a MSV não recebe fornecedor da GTF."""
    corpo, status = paineis.valores_filtro(g.escopo, request.args)
    return jsonify(corpo), status
