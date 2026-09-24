# HISTÓRICO — Grupo Start · Fechamento

Um registro por fase: o que foi feito, as decisões e as pendências.
Este arquivo vai para o GitHub: **nenhum valor em reais, nome de cliente ou de
fornecedor aqui**. Os números ficam em `relatorios/` e `tests/golden/esperado/`
(fora do git).

**Versão no ar:** nenhuma (sistema só local; deploy é a Fase 5).

---

## Fase 2 — Segurança da informação · 24/09/2026 · aguardando validação

### O que foi feito
- **Login** (padrão do Impostos): hash scrypt, bloqueio de 15 min após 5 erros,
  mensagem única para login inexistente e senha errada (com tempo igualado), sessão
  de 60 min parada, cookie `gsf_sessao` HttpOnly/Secure/SameSite=Lax com caminho do
  prefixo, troca de senha obrigatória no primeiro acesso, sessões derrubadas ao mudar
  senha, perfil, empresas ou ativo. Proteção contra open redirect no `?proximo=`.
- **Perfis e escopo por empresa** (migração 4: `usuarios`, `usuario_empresa`):
  Admin, Financeiro e Leitura. `app/escopo.clausula()` entra em todo SQL de contas e
  notas e erra se o escopo faltar; perfil e empresas vêm do banco a cada requisição;
  escrita fora do escopo responde 404. Scripts e sincronização usam o escopo `SISTEMA`.
- **CSRF** (Flask-WTF 1.3.0, a versão do Impostos) em todo POST; `fetch` manda o token
  no cabeçalho (`static/js/csrf.js`); Sair é POST.
- **Headers**: CSP sem `unsafe-inline` (Google Fonts é a única origem externa), HSTS,
  X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, no-store.
  Os dois `style="..."` do Dashboard viraram classe.
- **Validação** (`app/validacao.py`) em toda rota de escrita; toda f-string com SQL
  revista (nome vem de constante ou lista branca; valor é sempre parâmetro).
- **LGPD**: listagem de notas deixou de ler o CPF/CNPJ do cliente;
  `mascarar_documento` pronto para quando alguma tela o mostrar.
- **Usuários**: tela Admin → Usuários (tabela ordenável e filtrável), criação com
  senha provisória mostrada uma vez, edição, redefinição de senha;
  `scripts/criar_usuario.py` pelo terminal. Admin não rebaixa nem desativa a si mesmo.
- **Auditoria**: autor passa a ser o usuário logado; login, falha, bloqueio, logout,
  acesso negado, criação e alteração de usuário registrados.
- **Achado no caminho**: salvar a tela de regras de exclusão apagava regra cujo valor
  não tinha conta na visão (latente: hoje as 5 regras têm conta), e o formulário
  aceitava categoria inventada. Corrigido e testado.
- **Revisão final**: `tests/test_seguranca.py` (adaptado do `revisao_seguranca.py` do
  Novos Convertidos) — 84 testes: sem login, outra empresa, perfil, CSRF, headers,
  login, sessão, troca de senha, usuários, escopo, SQL, LGPD, validação.
- **Testes: 255.** Golden master idêntico (o Admin vê os mesmos números de antes).
  `pip-audit`: nenhuma vulnerabilidade conhecida.
- Banco local migrado para a versão 4 (backup `backups/app_20260924_175531_antes_v4.db`);
  usuário `neto` (Admin) criado com senha provisória e troca obrigatória.
- Relatório de riscos antes e depois em `relatorios/` (fora do git: o repositório é
  público).

### Decisões
1. Usuários: só o Neto, como Admin (decisão do Neto). Os demais pela tela.
2. Financeiro não sincroniza nem mexe em regra de exclusão (valem para as três
   empresas e consomem a cota da API de todas).
3. Admin vê todas as empresas sem precisar de atribuição, inclusive uma nova.
4. Escrita fora do escopo = 404 (não confirma que o registro existe); tela de Admin
   negada = 403 (a tela existe, só não é para o perfil), com registro na auditoria.
5. `.env` local com `GSF_COOKIE_SEGURO=0` (HTTP em 127.0.0.1); produção fica com o
   padrão, ligado.
6. Exportação para Excel (item 7) não existe ainda: a neutralização de fórmula entra
   junto com ela, na Fase 4.

### Pendências
- **Neto:** entrar com a senha provisória e definir a própria.
- Fase 5: `.env` com permissão 600, `GSF_PREFIXO`, Force HTTPS.

---

## Fase 1 — Estrutura técnica · 24/09/2026 · validada pelo Neto e mesclada (PR #6)

### O que foi feito
- **Estrutura**: fábrica `criar_app()` (padrão do Impostos); rotas finas em
  `app/web/` (dashboard, despesas, receitas, análise, extração, admin, api); a regra
  que morava em `app.py` foi para `app/paineis.py` sem mudar cálculo (golden idêntico).
  `app.py` virou só ponto de entrada; `debug` do Flask desligado.
- **Configuração** só do `.env` do projeto, prefixo `GSF_`, lida com `dotenv_values`;
  sem `GSF_SECRET_KEY` de 32+ caracteres o app não sobe. O `.env` local foi renomeado
  para os nomes novos (backup em `backups/`, nenhum valor exibido) e ganhou uma chave
  gerada. Os tokens do Tiny deixaram de ir para `os.environ`.
- **Migrações versionadas** (`app/migracoes/`, `db.MIGRACOES`), aplicadas no
  `criar_app` com backup verificado antes e uma transação por migração:
  1 = esquema de antes; 2 = integridade (CHECK nas colunas que o sistema escreve,
  índices dos filtros), `auditoria` e `sincronizacoes`; 3 = dinheiro em centavos.
- **Dinheiro em centavos** (`*_centavos INTEGER`), `Decimal` no cálculo, meio centavo
  sobe (`ROUND_HALF_UP`), rateio com resíduo na maior parte (`dinheiro.ratear`). Prova
  de reconciliação linha a linha e por empresa × competência × coluna; qualquer
  diferença desfaz a migração (testado).
- **journal_mode DELETE**, o mesmo do Impostos em produção (WAL não verificado no
  PythonAnywhere; na dúvida, o que já roda lá).
- **Auditoria** append-only (triggers) em toda escrita manual: marcar, ajustar nota,
  regras de exclusão e a importação de competências. Registro inexistente → 404;
  valor recusado pelo CHECK → 400.
- **Sincronização unificada** (`app/sincronizar_tudo.py`): contas e notas das três
  empresas no mesmo job, usado pela tela (agora com "Todas"), pela linha de comando e
  por `scripts/tarefa_diaria.py` (backup 30 dias + sync + relatório). Histórico em
  `sincronizacoes`; falha numa empresa não derruba as outras.
- **Erros e log**: tela genérica; `logs/app.log` com rotação (5 × 1 MB) e máscara de
  token, senha e CPF/CNPJ em mensagem e traceback.
- **Tela Sincronizar** sem `alert()`/`confirm()` e sem `innerHTML` com dado do Tiny
  (fechava um XSS por nome de fornecedor). JS sem caminho fixo (prefixo de produção).
- **Correções de bug** achadas no caminho: `importar_competencias_notas.py` atualizava
  nota sem filtrar a empresa; scripts ignoravam `GSF_BANCO`; abertura só-leitura
  quebrava com espaço no caminho (relatório e tarefa diária falhariam); relatório de
  qualidade somaria `float` com `Decimal`.
- **Banco local migrado** (versão 3), com backup `backups/app_20260924_002608_antes_v1.db`:
  reconciliação ok (28.528 contas, 1.135 notas), integridade ok, 15 MB após VACUUM.
  A fotografia do banco real bate com o golden: 0 diferenças.
- **Testes: 169** (unitários sintéticos + golden). `ruff check` limpo.

### Golden master — o que mudou de número, e por quê
Cada etapa está em `tests/golden/esperado/diff_*.md` (fora do git) e no histórico do
`meta.json`, com a fotografia anterior guardada.
1. **Centavos/Decimal** — 413 diferenças, só nos quadros do Dashboard, máximo de 4
   centavos: imposto arredondado por linha, resíduo do rateio na maior receita e o
   10% do ADM GERAL arredondado para Vendas com o complemento exato para Serviços.
   Receita, despesa, contagens e funis idênticos. 0 violações das regras verificadas.
2. **Conta sem competência aparece** (item 2) — entram exatamente as 134 contas do
   relatório da Fase 0, só nos recortes sem filtro de competência.
3. **Dashboard sem filtro = 01/2026 até o último mês com receita** (item 3) — só os
   cenários sem filtro mudam; cada um é a soma exata dos oito meses.
4. **Adm sem receita para absorver vira linha** (item 4, opção a) — 24 recortes (os do
   relatório da Fase 0); em todos os cenários o Total carrega o bolo inteiro de Adm.
5. **Ordem do funil determinística** (item 5) — mesmas listas, só a ordem.

### Desempenho (banco congelado, mediana, máquina local)
| Rota | Antes | Depois | Meta 300 ms |
|---|---:|---:|---|
| /despesas (15,6 mil linhas) | 1.743 ms | ~190 ms | atingida (2 mil linhas na tela) |
| /dashboard | 643 ms | ~280 ms | atingida |
| /api/valores-filtro (fornecedor) | 365 ms | ~115 ms | atingida |
| /api/valores-filtro (competência) | 357 ms | ~115 ms | atingida |

Em /despesas, montar os dados custa ~170 ms; renderizar 15,6 mil linhas levava ~300 ms.
Decisão do Neto: a tela desenha até 2 mil linhas, com "Mostrar todas"; total, contagem
e funis continuam sobre todas as linhas do recorte.

### Decisões
1. Pacote continua `app/` (renomear para `sistema/` mudaria todos os imports sem ganho).
2. Colunas monetárias renomeadas (`valor` → `valor_centavos`): quem lê o banco direto
   não confunde centavos com reais.
3. Regras de exclusão **não** cacheadas: já eram lidas uma vez por listagem (< 1 ms), e
   um cache arriscaria worker do PythonAnywhere somando com regra velha.
4. Uma trava por empresa cobre contas e notas (dividem a cota da API).
5. Não parei no meio da fase quando o golden mudou por centavos: a mudança decorre do
   item 4 da fase (Decimal + resíduo), está explicada linha a linha e fica numa branch
   sem merge até a validação.

### Código removido (com aval do Neto)
`app/tiny_client/http_client.py` (login simulado, nunca usado); `app/reports/consolidar.py`;
`combinar_registros`/`salvar` em `app/reports/contas_pagar.py` (únicos usos de pandas no
app); `arvore_datas`, `arvore_competencias`, `arvore_competencias_notas`,
`categorias_primarias_das_notas`, `resumir_por_categoria`, `resumir_receitas` e o
`sincronizacao.sincronizar` público (substituído pelo job único) — nenhuma referência.

### Validação do Neto (24/09/2026)
"De acordo com tudo": as cinco mudanças de número aprovadas (registrado no `meta.json`
do golden), Despesas limitada a 2 mil linhas na tela, código morto removido.
Também: fim de linha normalizado para LF (`.gitattributes`); o repositório nasceu
misturado e cada edição aparecia como troca do arquivo inteiro.

### Pendências
- Sincronizar as 3 empresas (paradas desde 25/08/2026) — agora pela tela, com "Todas".
- 4 PRs do Dependabot abertos (actions e pandas 3.0.6): o do pandas precisa do golden
  local antes do merge.

---

## Fase 0 — Fundação · 23/09/2026 · validada e mesclada (PR #1)

### O que foi feito
- **Backup** `backups/app_20260923_221922_antes_fase0.db` pela API de backup do SQLite,
  com `PRAGMA integrity_check = ok` na origem e na cópia, e contagem/soma idênticas
  nas três tabelas (28.528 contas, 1.135 notas, 5 regras).
- **Git local** na `main`, com `.gitignore` por seções (comentário sempre em linha
  própria), hook `pre-commit` (gitleaks, ruff, bloqueio de arquivo > 1 MB, chave
  privada e das extensões `.db`/`.xls*`/`.pkl`/`.csv`/`.env` — testado com `git add -f`),
  CI (`.github/workflows/ci.yml`: ruff, pytest sintético, pip-audit, gitleaks) e
  Dependabot semanal (pip e actions). Varredura antes do primeiro commit: gitleaks e
  detect-secrets sem achados.
- **Repositório no GitHub público** (decisão do Neto, 23/09/2026). Antes do primeiro push,
  o histórico local foi refeito para tirar o que não pode ser público: `CLAUDE.md` (dado
  pessoal do diretor), `PROMPT_MELHORIAS.md` (mapa da infraestrutura e das fragilidades
  abertas) e os valores de uma NFS-e real num comentário de `app/receitas.py` (trocados por
  valores ilustrativos com a mesma aritmética). Os dois `.md` continuam no disco, fora do git.
- **`pyproject.toml`** com as versões fixadas. O `requirements.txt` antigo estava
  desatualizado (Flask 3.0.3 e pandas 2.2.2 declarados; rodava Flask 3.1.3 e pandas 3.0.5,
  e o pandas 2.2.2 nem instala no Python atual). Agora os dois batem. `pip-audit`: nenhuma
  vulnerabilidade conhecida.
- **Testes unitários (dados sintéticos): 83**, cobrindo `valor_bruto_de_servico`,
  `casa_data`, `_considerar_efetivo` (despesas e receitas), `separar`, `valores`
  (cascata do funil, pela função e pela rota) e as telas (contexto capturado pelo sinal
  `template_rendered`, sem depender do HTML que a Fase 3 vai trocar).
- **Golden master** (`tests/golden/`): 227 cenários — telas com filtros padrão;
  Dashboard, Despesas, Receitas Vendas e Receitas Serviços para cada empresa (e o
  consolidado) × cada competência de 01/2026 a 08/2026 e sem slicer; análise de receitas;
  lista de todos os funis com e sem recorte. Roda sobre uma **cópia congelada** do banco
  (a sincronização muda o banco vivo, e o golden mediria dado em vez de código), com
  SHA-256 conferido. Tolerância: meio centavo. Estável em 3 execuções seguidas; teste de
  mutação (Vendas 14% → 15%) acusou 408 diferenças, cada uma com o caminho até a linha.
- **Relatório de qualidade de dados** (`scripts/relatorio_qualidade.py`, só leitura,
  `mode=ro`), gravado em `relatorios/qualidade_fase0.md`.
- `ruff check` limpo no projeto inteiro (regras de bug); `ruff format` só nos arquivos novos.

### Achados (detalhe com valores no relatório local)
1. **Sincronização parada há 29 dias** nas 3 empresas, despesas e notas (última gravação
   25/08/2026). Não existe registro de execução: a data sai do `atualizado_em`.
2. **134 contas sem competência somem da tela** (`substr(NULL)` no filtro). 51 delas têm
   vencimento em 2026 e 42 em 2027; a maior parte é GASTOS FIXO.
3. **O Dashboard sem slicer soma parcelas até 2032** (e uma competência 07/2800). Cerca de
   **50% da despesa considerada** do Total sem slicer é de competência posterior a 09/2026,
   contra uma receita que para em 08/2026. Esse Total não é resultado de período nenhum.
4. **Adm rateado some quando o bloco não tem receita no recorte.** Com o filtro de uma
   empresa, os 90% do ADM GERAL que cabem a Serviços somem na MSV (sem receita de serviço),
   e os 10% de Vendas somem na GTF e em vários meses da START. O Resultado dessas visões
   fica maior do que a despesa permite. No consolidado mensal de 01 a 08/2026 não acontece.
5. **45 contas sem categoria na visão**, quase todas da MSV. Nenhuma nota considerada sem
   categoria hoje (as 18 de venda sem categoria estão todas desconsideradas).
6. **45 fornecedores com grafia que muda só na caixa** (ex.: `Fulano` × `FULANO`): aparecem
   duas vezes no funil e somam separados na árvore do Dashboard.
7. **Bug de código: a ordem do funil não é determinística** para esses fornecedores
   (`valores()` parte de um `set` e ordena por `casefold`, que empata). O golden achou.
8. **Risco latente:** a lista de situações sem receita tem `EXCLUIDA` sem acento — uma nota
   "Excluída" entraria como receita. Hoje não existe nenhuma no banco.
9. A regra de exclusão compara texto exato (`IMPOSTO` ≠ `Imposto`). Hoje não há grafia
   divergente de categoria, então sem efeito.
10. Comentário em `app/receitas.py` trazia os valores de uma NFS-e real — trocado por
    valores ilustrativos antes do primeiro push (repositório público).

### Decisões
1. Golden roda pelas rotas (contexto do template), não pelas funções: pega também a lógica
   que mora na rota (competência do Dashboard, tipo de nota fixo das telas de receita).
2. "Última competência fechada" = última competência com nota (08/2026). Despesa tem
   parcela até 2032 e não serve de sinal.
3. Comportamentos suspeitos (itens 4, 7, 8) ficaram **congelados como estão**, com teste que
   os documenta: corrigir agora mudaria número sem decisão registrada.
4. Ruff só com regras de bug nesta fase; estilo entra com a reescrita da Fase 1.
5. `.venv` no próprio projeto (fora do git) com as versões fixadas.
6. **Repositório público** (Neto, 23/09/2026). Consequência registrada: a partir daqui
   nenhum arquivo versionado pode ter dado pessoal, valor real, nome de cliente ou
   fornecedor, nem descrição de infraestrutura ou de fragilidade de segurança em aberto.
   O relatório de riscos da Fase 2 fica fora do git.
7. **Correções de visão aprovadas** (Neto, 23/09/2026, "o restante segue"): itens 2 (conta
   sem competência aparece como "(vazio)" em vez de sumir), 3 (Dashboard sem slicer abre no
   período 01/2026 até o último mês com receita, escrito no cabeçalho), 5 (ordem do funil
   determinística) e, no item 4, a opção recomendada: a cota de Adm sem receita para
   absorver vira linha própria, visível, em vez de sumir. Entram na Fase 1, cada uma com a
   diferença do golden master explicada linha a linha antes de regerar.

### GitHub (23/09/2026)
- Repositório **público** https://github.com/carlosneto95/grupo-start-fechamento, criado
  com o `gh` (instalado via winget). Autor dos commits: e-mail privado do GitHub
  (`...@users.noreply.github.com`), para o e-mail pessoal não ficar público.
- Ligados: Secret scanning, Push protection e Dependabot alerts.
- `main` protegida: só por PR, com os checks `testes` e `segredos` verdes e a branch
  atualizada; vale também para o administrador; sem force-push e sem apagar a branch.
  O PR exige 0 aprovações: com um único desenvolvedor, exigir 1 travaria todo merge.
- CI do PR #1 verde: 83 testes passaram e o golden foi pulado com aviso (o CI não tem o
  banco); `pip-audit` sem vulnerabilidade conhecida; gitleaks sem vazamento.

### Pendências
- Rodar a sincronização das 3 empresas **depois** de validado o golden (o golden usa a
  cópia congelada, então sincronizar não o invalida).
