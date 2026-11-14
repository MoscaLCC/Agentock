@echo off
rem Arranca o bot do Agentock sem janela, com registo em data\logs\bot.log.
rem Usado pela tarefa agendada (tools\install_bot_task.ps1) ou à mão (duplo clique).
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
start "" /b pythonw -u tools\telegram_bot.py >> data\logs\bot.log 2>&1
