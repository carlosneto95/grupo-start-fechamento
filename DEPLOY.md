# Deploy — PythonAnywhere

O sistema fica em `https://<conta>.pythonanywhere.com/financeiro/`, no mesmo web app
que já serve outros sistemas da conta. Mesmo roteiro do Controle de Impostos, adaptado.

Este arquivo é público (vai para o GitHub): não tem nome de conta, caminho real nem a
lista dos outros sistemas. O passo a passo concreto fica em
`relatorios/deploy_passo_a_passo.md`, fora do git.

## Regras que não são opcionais

1. **Nunca reescrever o arquivo WSGI** da conta: ele monta os outros sistemas. O
   `deploy/anexar-wsgi.sh` só **acrescenta** um bloco no fim, com backup antes, checagem de
   sintaxe, e compara como os outros sistemas respondem antes e depois — se algum mudar,
   restaura sozinho.
2. O bloco **embrulha** o `application` existente: só `/financeiro` vem para este sistema.
   Se ele falhar ao subir, o erro vai para o *Error log* e os outros seguem no ar.
3. **O pacote Python se chama `financeiro`, não `app`.** Outro sistema do mesmo processo
   tem um pacote `app` e o importa durante as requisições; num processo só existe um `app`
   em `sys.modules`. O bloco só mexe em módulos `financeiro*`. Nunca renomear de volta.
4. **Virtualenv compartilhado** com os outros sistemas: o `instalar.sh` só instala o que
   **falta** e nunca atualiza o que os outros usam; `pip check` antes e depois.
   O pytest dos testes vai para `~/financeiro/.ferramentas-teste/`, fora do venv.
5. Configuração só pelo `.env` do projeto, com nomes `GSF_*`. Cookie de sessão próprio
   (`gsf_sessao`) com caminho `/financeiro`.
6. **Force HTTPS** ligado na aba Web.
7. **Depois da carga inicial, o servidor é a fonte da verdade.** Ajuste feito no banco
   local depois do corte não sobe e se perde (a tela Sincronizar do ambiente local avisa).

## Primeira instalação

### No computador
```
.venv\Scripts\python deploy\empacotar.py          → dist\financeiro_AAAAMMDD_HHMM.zip        (código)
.venv\Scripts\python deploy\empacotar_carga.py    → dist\financeiro_carga_AAAAMMDD_HHMM.zip  (banco, UMA vez)
```
O pacote de carga tem **dado real**: vai direto para a aba Files e é apagado dos dois
lados depois. Gere-o por último, depois do último ajuste feito no banco local.

### No PythonAnywhere
1. **Files**: enviar os dois zips para a pasta pessoal (`~`).
2. **Bash console**:
   ```bash
   mkdir -p ~/financeiro && cd ~/financeiro && unzip -o ~/financeiro_AAAAMMDD_HHMM.zip
   # uma vez: ~/financeiro/.deploy.env (fora do git) com FINANCEIRO_VENV e FINANCEIRO_OUTROS
   bash deploy/instalar.sh                                      # Python, pastas, .env com chave nova, bibliotecas que faltam
   bash deploy/carregar-banco.sh ~/financeiro_carga_AAAAMMDD_HHMM.zip   # banco + conferência + testes (golden incluído)
   rm ~/financeiro_carga_AAAAMMDD_HHMM.zip
   bash deploy/anexar-wsgi.sh                                   # liga /financeiro (backup, sintaxe, antes × depois)
   ```
   O `carregar-banco.sh` confere o SHA-256 do banco e, depois das migrações, as contagens,
   as somas em centavos por empresa e os ajustes manuais contra o manifesto do computador.
   Ele recusa rodar se já existir `data/app.db`.
3. **Tokens do Tiny**: na aba **Files**, abrir `~/financeiro/.env` e preencher
   `GSF_EMPRESA1_TINY_API_TOKEN` (MSV), `..._2_...` (START) e `..._3_...` (GTF).
   Nunca colar token em chat, e-mail ou console com histórico compartilhado.
4. **Primeira sincronização, à mão, para medir o tempo** (a última completa, no
   computador, levou ~91 min — quase tudo espera pela cota da API do Tiny):
   ```bash
   cd ~/financeiro && time <venv>/bin/python scripts/tarefa_diaria.py
   ```
5. **Tasks**: tarefa diária às **07:00 UTC** (04:00 em Brasília):
   ```
   <venv>/bin/python /home/<conta>/financeiro/scripts/tarefa_diaria.py
   ```
   Backup do banco (30 dias em `backups/`), sincronização das três empresas (contas e
   notas do ano) e relatório de pendências em `relatorios/`. O horário é antes das 06:00
   de Brasília de propósito: o Controle de Impostos usa as mesmas contas do Tiny nesse
   horário, e as duas tarefas juntas disputariam a cota de chamadas por minuto.
   Se a execução passar do limite de tempo de tarefa do plano, dividir em duas tarefas
   (uma por tipo: `scripts/sincronizar.py TODAS 2026 --so contas` e `--so notas`).
6. **Web**: conferir *Force HTTPS* ligado. Abrir `/financeiro/`, entrar como `neto`
   (o usuário veio na carga, com a mesma senha).

## Atualização (nova versão, sem perder dados)
No computador: `.venv\Scripts\python deploy\empacotar.py`. No PythonAnywhere, enviar o zip e:
```bash
bash ~/financeiro/deploy/atualizar.sh ~/financeiro_AAAAMMDD_HHMM.zip
```
O script roda a suíte inteira na versão nova numa pasta temporária (falhou: **nada muda**),
faz backup do banco, copia só o código (`data/`, `backups/`, `logs/`, `relatorios/`, `.env`
e o golden nunca são tocados), aplica as migrações (com backup próprio) e recarrega o app.

## Migração do banco
- Cada evolução é um arquivo em `financeiro/migracoes/000N_*.sql`, registrado em
  `db.MIGRACOES`. `criar_app()` aplica as pendentes ao subir, com backup verificado antes
  (`backups/app_*_antes_vN.db`).
- Nunca editar uma migração já aplicada; sempre criar a próxima.

## Voltar atrás
- **Tirar o /financeiro do ar** (sem afetar os outros):
  copiar o `<arquivo WSGI>.backup-DATA` que o `anexar-wsgi.sh` criou por cima do WSGI e
  *Reload* na aba Web.
- **Versão anterior do código**: `bash deploy/atualizar.sh` com o zip anterior (o banco
  fica; se a versão nova tiver aplicado migração, voltar também o banco, abaixo).
- **Banco**: parar a tarefa agendada, copiar o backup desejado de `backups/` para
  `data/app.db`, *Reload*.

## O que NUNCA vai para o servidor pelo pacote de código
`.env` do computador, `data/`, `backups/`, `relatorios/`, `logs/`, planilhas e os valores
reais do golden. O `empacotar.py` parte do `git ls-files` (lista de inclusão) e aborta se
encontrar banco, planilha ou `.env`. O banco sobe uma única vez, pelo pacote de carga.

## Testes no servidor
```bash
bash ~/financeiro/deploy/testar.sh
```
A suíte é hermética (não lê o `.env` de produção nem toca o banco real). Com o golden
instalado pela carga, ela prova que as bibliotecas do venv compartilhado dão os mesmos
números que as do computador.
