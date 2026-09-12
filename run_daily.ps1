# run_daily.ps1 — make today's Gujarati Short from the next queued script.
# Double-click to run once, or point Windows Task Scheduler at it for daily auto-runs.
Set-Location -Path $PSScriptRoot
$log = Join-Path $PSScriptRoot "daily.log"
"[$(Get-Date)] === daily run starting ===" | Add-Content $log
python main.py --daily *>> $log
$code = $LASTEXITCODE
"[$(Get-Date)] === finished (exit $code) ===" | Add-Content $log
if ($code -eq 2) {
  "[$(Get-Date)] QUEUE EMPTY — ask Claude for more scripts and add them to stories\queue\" | Add-Content $log
}
exit $code
