# Regista duas tarefas agendadas do Windows para o bot do Agentock ficar sempre ligado:
#
#   "Agentock bot"       arranca o supervisor (tools\run_bot.cmd) quando inicias sessão; o supervisor volta a
#                        arrancar o bot sempre que ele parar, e a tarefa volta a arrancar o supervisor se ele morrer.
#   "Agentock watchdog"  de 5 em 5 minutos confirma o sinal de vida do bot (tools\bot_watchdog.py); se estiver preso,
#                        termina-o (o supervisor arranca outro) e avisa-te no Telegram.
#
#   Instalar:   powershell -ExecutionPolicy Bypass -File tools\install_bot_task.ps1
#   Remover:    powershell -ExecutionPolicy Bypass -File tools\install_bot_task.ps1 -Remove
#   Ver estado: Get-ScheduledTask -TaskName "Agentock*" | Get-ScheduledTaskInfo
#
# Só afeta o teu utilizador e não precisa de administrador. Corre com a tua sessão iniciada (é ela que tem o login
# do Claude Code). Para arrancar também sem sessão iniciada, ver docs/PLANO.md §Alojamento (exige administrador e um
# token de longa duração em vez do login interativo).
param([switch]$Remove)

$names = "Agentock bot", "Agentock watchdog"
if ($Remove) {
    foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Output "Tarefas removidas. O bot que estiver a correr continua até fechares a janela ou reiniciares."
    return
}

$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$common = @{ AllowStartIfOnBatteries = $true; DontStopIfGoingOnBatteries = $true; StartWhenAvailable = $true
             MultipleInstances = "IgnoreNew" }

# 1) supervisor: sem limite de tempo, reinicia de minuto a minuto se o próprio supervisor morrer
$botAction = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c tools\run_bot.cmd" -WorkingDirectory $root
$botSettings = New-ScheduledTaskSettingsSet @common -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
Register-ScheduledTask -TaskName $names[0] -Action $botAction -Trigger $trigger -Settings $botSettings `
    -Description "Bot Telegram do Agentock (supervisor com reinício automático)" -Force | Out-Null

# 2) vigia: de 5 em 5 minutos, enquanto houver sessão
$wdAction = New-ScheduledTaskAction -Execute $python -Argument "tools\bot_watchdog.py" -WorkingDirectory $root
$wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
$wdSettings = New-ScheduledTaskSettingsSet @common -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -Hidden
Register-ScheduledTask -TaskName $names[1] -Action $wdAction -Trigger $wdTrigger, $trigger -Settings $wdSettings `
    -Description "Vigia o sinal de vida do bot do Agentock" -Force | Out-Null

Start-ScheduledTask -TaskName $names[0]
Write-Output "Tarefas '$($names[0])' e '$($names[1])' instaladas. O bot arranca agora e sempre que iniciares sessão."
Write-Output "Registo: data\logs\bot.log · estado no Telegram: /estado"
