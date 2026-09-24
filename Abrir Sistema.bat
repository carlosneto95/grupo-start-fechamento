@echo off
REM ===================================================================
REM  Grupo Start - Fechamento
REM  Sobe o servidor Flask e abre o navegador na tela de despesas.
REM  Fechar esta janela (ou Ctrl+C) derruba o servidor.
REM ===================================================================
setlocal
title Grupo Start - Fechamento (servidor)

REM %~dp0 = pasta onde este .bat esta. Sem o cd, um atalho com "iniciar em"
REM apontando para outro lugar faria o python nao achar app.py nem data\app.db.
cd /d "%~dp0"

REM Python instalado? Sem esta checagem o erro seria um "nao reconhecido como
REM comando" que some junto com a janela antes de dar tempo de ler.
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    pause
    exit /b 1
)

REM Porta 5000 ja ocupada significa que o servidor provavelmente ja esta no ar.
REM Subir um segundo so geraria WinError 10048; melhor so abrir o navegador.
netstat -ano | findstr /r /c:"TCP.*:5000 .*LISTENING" >nul
if not errorlevel 1 (
    echo Servidor ja esta rodando - abrindo o navegador.
    start http://127.0.0.1:5000
    exit /b 0
)

REM O python segura esta janela enquanto serve, entao o navegador precisa ser
REM aberto por um processo paralelo. Os 3s dao folga para o Flask subir - abrir
REM antes disso mostraria "nao foi possivel conectar".
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"

echo.
echo   Sistema em http://127.0.0.1:5000
echo   Ctrl+C ou fechar esta janela para parar.
echo.
python app.py

REM Se o python morreu no arranque (dependencia faltando, erro de import), a
REM janela fecharia sozinha e levaria o traceback junto. pause segura a tela.
if errorlevel 1 pause
