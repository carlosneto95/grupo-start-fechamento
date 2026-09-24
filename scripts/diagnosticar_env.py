"""
Diagnóstico do .env — não imprime nenhum valor sensível, só confirma
se o arquivo foi encontrado e quais variáveis estão preenchidas.

Uso:
    python scripts/diagnosticar_env.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import find_dotenv, load_dotenv

caminho_encontrado = find_dotenv(usecwd=True)
print(f"Diretório atual (cwd): {os.getcwd()}")
print(f".env esperado em:      {RAIZ / '.env'}")
print(f".env existe nesse caminho? {(RAIZ / '.env').exists()}")
print(f".env encontrado pelo find_dotenv: {caminho_encontrado or '(não encontrado)'}")
print()

load_dotenv(RAIZ / ".env")

campos = [
    "EMPRESA1_NOME", "EMPRESA1_TINY_API_TOKEN", "EMPRESA1_TINY_USER", "EMPRESA1_TINY_PASS",
    "EMPRESA2_NOME", "EMPRESA2_TINY_API_TOKEN", "EMPRESA2_TINY_USER", "EMPRESA2_TINY_PASS",
    "EMPRESA3_NOME", "EMPRESA3_TINY_API_TOKEN", "EMPRESA3_TINY_USER", "EMPRESA3_TINY_PASS",
]
print("Variáveis preenchidas (True/False, sem mostrar o valor):")
for campo in campos:
    valor = os.getenv(campo)
    print(f"  {campo}: {'preenchido' if valor else 'vazio/ausente'}")
