// CSRF nos fetch POST (Fase 2).
//
// O Flask-WTF exige o token em todo POST. Formulário comum leva o campo
// escondido; o fetch JSON leva o cabeçalho X-CSRFToken, com o token que o
// servidor pôs no <meta name="csrf-token"> de _base.html.
//
// `postarJson` é o caminho único de POST das telas: centraliza o token, o
// Content-Type e o tratamento da sessão expirada (401 -> volta ao login).

function tokenCsrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
}

async function postarJson(url, corpo) {
    const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": tokenCsrf() },
        body: JSON.stringify(corpo),
    });
    if (resp.status === 401) {
        // Sessão expirou (60 min parada): recarregar leva ao login e volta aqui.
        window.location.reload();
    }
    return resp;
}
