# Regista uma tarefa agendada do Windows que arranca o bot do Agentock quando inicias sessão,
# e o reinicia se parar (até 999 vezes, de minuto a minuto).
#
#   Instalar:   powershell -ExecutionPolicy Bypass -File tools\install_bot_task.ps1
#   Remover:    Unregister-ScheduledTask -TaskName "Agentock bot" -Confirm:$false
#   Ver estado: Get-ScheduledTask -TaskName "Agentock bot" | Get-ScheduledTaskInfo
#
# Só afeta o teu utilizador (não precisa de administrador).

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command pythonw -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "-u tools\telegram_bot.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Agentock bot" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Bot Telegram do Agentock (comandos /run, /ipos, /detalhe_...)" -Force | Out-Null
Start-ScheduledTask -TaskName "Agentock bot"
Write-Output "Tarefa 'Agentock bot' instalada e arrancada (python: $python)."
