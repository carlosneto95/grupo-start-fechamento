"""
Script simples para testar a conexão com o Tiny da EMPRESA 1 antes de
implementar o relatório em si.

Uso:
    1. Copie .env.example para .env e preencha os dados da EMPRESA1
       (token da API, OU usuário/senha para o fallback HTTP).
    2. pip install -r requirements.txt
    3. python scripts_testar_conexao.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.companies import load_companies
from app.tiny_client.api_client import TinyAPIClient

def main():
    empresas = load_companies()
    if not empresas:
        print("Nenhuma empresa configurada no .env ainda. Preencha EMPRESA1_* e tente de novo.")
        return

    empresa = empresas[0]
    print(f"Testando empresa: {empresa.nome} ({empresa.key})")

    if empresa.has_api_token:
        cliente = TinyAPIClient(token=empresa.tiny_api_token, empresa_nome=empresa.nome)
        ok = cliente.testar_conexao()
        print("Conexão via API:", "OK" if ok else "FALHOU")
    elif empresa.has_http_credentials:
        print("Login/senha configurados, mas o fallback HTTP ainda não foi implementado.")
        print("Precisamos inspecionar o site do Tiny primeiro para descobrir a URL/campos do login.")
    else:
        print("Empresa sem token nem usuário/senha configurados.")


if __name__ == "__main__":
    main()
