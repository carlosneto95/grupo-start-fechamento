"""
Mostra o JSON completo e "cru" de UMA conta a pagar (todos os campos que a
API realmente devolve, não só os documentados). Útil pra descobrir campos
como data de liquidação que a documentação pode não listar.

Uso:
    python scripts/inspecionar_registro.py
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config.companies import load_companies
from app.tiny_client.api_client import TinyAPIClient


def main():
    empresas = load_companies()
    if not empresas:
        print("Nenhuma empresa configurada no .env ainda.")
        return

    empresa = empresas[0]
    cliente = TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)

    resp = cliente._post("contas.pagar.pesquisa.php", {"situacao": "pago", "pagina": 1})
    contas = resp.get("retorno", {}).get("contas", [])
    if not contas:
        print("Nenhuma conta encontrada na busca.")
        return

    primeiro = contas[0]
    id_conta = primeiro.get("conta", primeiro).get("id")
    print(f"Buscando detalhe completo da conta id={id_conta}...\n")

    detalhe = cliente.obter_conta_pagar(id_conta)
    print(json.dumps(detalhe, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
