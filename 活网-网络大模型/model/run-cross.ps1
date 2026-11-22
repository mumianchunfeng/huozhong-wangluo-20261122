# 活网 · 阶段三 · 跨域对照（只换学习键）
# .\run-cross.ps1            30 拍：A 段同域学满，B/C 段换两域，两把键各跑一遍
param([int]$N = 30, [int]$Seed = 20261122)

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$seedArgs = @()
if ($Seed -gt 0) { $seedArgs = @("--seed", "$Seed") }

python netmodel.py cross-both --n $N @seedArgs
Write-Output ""
Write-Output "[ledger] $PSScriptRoot\ledger_cross_domain  与  ledger_cross_relation"
