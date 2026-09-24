# HISTÓRICO — Grupo Start · Fechamento

Um registro por fase: o que foi feito, as decisões e as pendências.
Este arquivo vai para o GitHub: **nenhum valor em reais, nome de cliente ou de
fornecedor aqui**. Os números ficam em `relatorios/` e `tests/golden/esperado/`
(fora do git).

**Versão no ar:** nenhuma (sistema só local; deploy é a Fase 5).

---

## Fase 0 — Fundação · 23/09/2026 · aguardando validação

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

### Pendências
- Proteger a `main` no GitHub, ligar Secret scanning, Push protection e Dependabot alerts.
- Rodar a sincronização das 3 empresas **depois** de validado o golden (o golden usa a
  cópia congelada, então sincronizar não o invalida).
