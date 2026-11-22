# 活网 · 阶段三 · 真事跑（一件真事入 propose()）
# .\run-real.ps1              串行 40 拍 + 并行 40 拍对照，各存一本账（默认固定种子可复算）
# .\run-real.ps1 200 0        长跑 200 拍、不设种子
param([int]$N = 40, [int]$Seed = 20261122)
$seedArgs = @()
if ($Seed -gt 0) { $seedArgs = @("--seed", "$Seed") }

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Remove-Item -Recurse -Force ledger_real -ErrorAction SilentlyContinue
python netmodel.py real --n $N --reset @seedArgs
Copy-Item -Recurse -Force ledger_real "ledger_real_串行$N"

Remove-Item -Recurse -Force ledger_real -ErrorAction SilentlyContinue
python netmodel.py real --n $N --parallel --reset @seedArgs
Copy-Item -Recurse -Force ledger_real "ledger_real_并行$N"

python netmodel.py stats-real
Write-Output ""
Write-Output "[ledger] $PSScriptRoot\ledger_real_串行$N  与  ledger_real_并行$N"

