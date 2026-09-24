// Edição inline de competência e categoria das notas.
// O valor do ERP nunca é sobrescrito: o que se grava é um ajuste em coluna
// separada, então a edição sobrevive à sincronização e dá para voltar atrás
// deixando o campo em branco.

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".celula-editavel").forEach((celula) => {
        celula.addEventListener("click", () => abrirEdicao(celula));
    });
});

function abrirEdicao(celula) {
    if (celula.querySelector("input")) return; // já está editando

    const span = celula.querySelector(".valor");
    const campo = celula.dataset.campo;
    const atual = span.textContent.trim() === "—" ? "" : span.textContent.trim();

    const input = document.createElement("input");
    input.type = "text";
    input.value = atual;
    input.className = "editor-inline";
    if (campo === "competencia") {
        input.placeholder = "MM/AAAA";
        input.pattern = "\\d{2}/\\d{4}";
    } else {
        input.setAttribute("list", "categorias-sugeridas");
        input.placeholder = "escolha ou digite a categoria";
    }

    const conteudoAnterior = celula.innerHTML;
    celula.innerHTML = "";
    celula.appendChild(input);
    input.focus();
    input.select();

    let finalizado = false;

    function cancelar() {
        if (finalizado) return;
        finalizado = true;
        celula.innerHTML = conteudoAnterior;
        celula.addEventListener("click", () => abrirEdicao(celula), { once: false });
    }

    function formatoValido(valor) {
        return campo !== "competencia" || !valor || /^\d{2}\/\d{4}$/.test(valor);
    }

    // origem "enter": valor inválido avisa e mantém o foco para corrigir.
    // origem "blur" : valor inválido apenas desiste — prender o foco na célula
    //                 deixaria o usuário sem conseguir sair dali.
    async function salvar(origem) {
        if (finalizado) return;
        const novo = input.value.trim();
        if (novo === atual) return cancelar();

        if (!formatoValido(novo)) {
            if (origem === "blur") return cancelar();
            input.classList.add("entrada-invalida");
            input.title = "Use o formato MM/AAAA — por exemplo 07/2026";
            input.focus();
            return;
        }

        finalizado = true;
        const linha = celula.closest("tr");
        const corpo = {
            empresa: linha.dataset.empresa,
            tipo_nota: linha.dataset.tipo,
            id: linha.dataset.id,
        };
        corpo[campo] = novo; // string vazia limpa o ajuste

        try {
            // Destino vem do servidor (data-ajustar na tabela), nunca fixo.
            const destino = document.getElementById("tabela-notas").dataset.ajustar;
            const resp = await fetch(destino, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(corpo),
            });
            if (!resp.ok) throw new Error("falha ao salvar");
            // Recarrega para os totais e o filtro de competência refletirem a mudança.
            window.location.reload();
        } catch (e) {
            finalizado = false;
            celula.innerHTML = conteudoAnterior;
            celula.classList.add("erro-ao-salvar");
            celula.title = "Não consegui salvar: " + e.message;
        }
    }

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); salvar("enter"); }
        if (e.key === "Escape") { e.preventDefault(); cancelar(); }
    });
    input.addEventListener("blur", () => salvar("blur"));
}
