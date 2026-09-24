"""Endpoints JSON consumidos pelo JavaScript das telas."""

from flask import Blueprint, jsonify, request

from app import paineis

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/valores-filtro")
def valores_filtro():
    """Lista do funil de coluna, carregada só quando o funil abre."""
    corpo, status = paineis.valores_filtro(request.args)
    return jsonify(corpo), status
