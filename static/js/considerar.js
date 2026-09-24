// Alternância "Considerar / Desconsiderar", usada em Despesas e em Receitas.
//
// A coluna mostra o estado por extenso e o próprio texto é o botão: um clique
// inverte e grava. Cada tela diz no <table> para onde postar (data-marcar) e o
// que identifica a linha; as notas precisam do tipo (venda/serviço), porque a
// chave delas é (empresa, tipo_nota, id).

const ROTULO = { sim: "Considerar", nao: "Desconsiderar" };

document.addEventListener("DOMContentLoaded", () => {
    const tabela = document.querySelector("[data-marcar]");
    if (!tabela) return;
    const destino = tabela.dataset.marcar;

    const totalEl = document.getElementById("total-considerado");
    let total = totalEl ? parseFloat(totalEl.dataset.total) : 0;

    function atualizarTotal() {
        if (!totalEl) return;
        totalEl.textContent = "R$ " + total.toLocaleString("pt-BR", {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
    }

    tabela.querySelectorAll(".alternar-considerar").forEach((botao) => {
        botao.addEventListener("click", async () => {
            const linha = botao.closest("tr");
            const valor = parseFloat(linha.dataset.valor);
            const considerar = botao.classList.contains("nao");  // clicar inverte

            const corpo = {
                empresa: linha.dataset.empresa,
                id: linha.dataset.id,
                considerar,
            };
            if (linha.dataset.tipo) corpo.tipo_nota = linha.dataset.tipo;

            botao.disabled = true;
            try {
                const resp = await fetch(destino, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(corpo),
                });
                if (!resp.ok) throw new Error("resposta " + resp.status);

                pintar(botao, considerar);
                linha.classList.toggle("linha-desconsiderada", !considerar);
                total += considerar ? valor : -valor;
                atualizarTotal();
            } catch (e) {
                // Nada de alert(): ele congela a aba. O aviso vai na própria linha.
                avisarFalha(linha, "não salvou: " + e.message);
            } finally {
                botao.disabled = false;
            }
        });
    });
});

function pintar(botao, considerar) {
    botao.classList.toggle("sim", considerar);
    botao.classList.toggle("nao", !considerar);
    botao.textContent = considerar ? ROTULO.sim : ROTULO.nao;
    botao.setAttribute("aria-pressed", String(considerar));
}

/** Aviso discreto e temporário na linha que falhou. */
function avisarFalha(linha, texto) {
    linha.classList.add("linha-com-erro");
    const aviso = document.createElement("span");
    aviso.className = "aviso-linha";
    aviso.textContent = texto;
    linha.querySelector("td").appendChild(aviso);
    setTimeout(() => {
        linha.classList.remove("linha-com-erro");
        aviso.remove();
    }, 4000);
}
