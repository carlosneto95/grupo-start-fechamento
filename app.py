"""Ponto de entrada local: `python app.py` sobe o servidor em :5000.

Toda a montagem está em `financeiro.criar_app()` (financeiro/__init__.py). No
PythonAnywhere o WSGI chama a mesma fábrica.
"""

from financeiro import criar_app

app = criar_app()

if __name__ == "__main__":
    # use_reloader desligado de propósito: o projeto fica dentro do OneDrive, e a
    # sincronização dele "toca" nos arquivos, fazendo o Flask reiniciar sozinho e
    # matar a extração em andamento (já aconteceu, perdendo 15 min de chamadas).
    # debug também desligado: o depurador do Werkzeug executa código enviado
    # pelo navegador e mostra traceback com dado na tela.
    app.run(debug=False, use_reloader=False)
