@echo off
rem Arranca o supervisor do bot do Agentock numa janela minimizada (ver tools\run_bot.cmd).
rem Para ficar sempre ligado, mesmo depois de reiniciar o PC: tools\install_bot_task.ps1
cd /d "%~dp0.."
start "Agentock bot" /min cmd /c tools\run_bot.cmd
