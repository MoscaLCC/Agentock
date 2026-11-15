@echo off
rem Supervisor do bot do Agentock: arranca-o e volta a arrancá-lo sempre que parar (erro, atualização, queda).
rem Usado pela tarefa agendada (tools\install_bot_task.ps1); também serve à mão (duplo clique).
rem O bot grava o seu próprio registo rotativo em data\logs\bot.log; aqui só fica o que o Python escrever antes
rem de o registo existir (erros de arranque), em data\logs\bot-supervisor.log.
rem Uma segunda instância sai sozinha (data\bot.lock), por isso correr isto duas vezes não faz mal.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
set PYTHONUTF8=1

:loop
python -u tools\telegram_bot.py >> data\logs\bot-supervisor.log 2>&1
echo [%date% %time%] o bot terminou (codigo %errorlevel%); novo arranque dentro de 15 s >> data\logs\bot-supervisor.log
timeout /t 15 /nobreak > nul
goto loop
