# 活网 · 阶段三  一键跑
# .\run.ps1           串行 40 拍
# .\run.ps1 40 p      并行 40 拍
# .\run.ps1 200 p     长跑
param([int]$N = 40, [string]$Mode = "s")

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Remove-Item -Recurse -Force ledger -ErrorAction SilentlyContinue
python netmodel.py init | Out-Null
if ($Mode -eq "p" -or $Mode -eq "parallel") {
    python netmodel.py tick --n $N --parallel
} else {
    python netmodel.py tick --n $N
}
python netmodel.py stats
Write-Output ""
Write-Output "[ledger] $PSScriptRoot\ledger   events.jsonl = passed, rejects.jsonl = rejected"
