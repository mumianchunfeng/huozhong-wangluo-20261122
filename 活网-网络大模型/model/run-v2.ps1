# 活网 · 阶段三 · 下一版（60 格）
# .\run-v2.ps1         init → 自检 → 三版对照（30 拍、固定种子）
param([int]$N = 30, [int]$Seed = 20261122)

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$seedArgs = @()
if ($Seed -gt 0) { $seedArgs = @("--seed", "$Seed") }

python netmodel2.py init
python netmodel2.py selfcheck
python netmodel2.py compare --n $N @seedArgs
