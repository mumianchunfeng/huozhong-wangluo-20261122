#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火种 × 活网 · 合成入口（点火.py）
=================================
把「火种的点火校验」做成网络大模型启动前的硬闸门：
    火种 fireup.py check 通过 → 才允许加载 run.py（八步自检）
    闸门非 0 → 一行模型逻辑都不启动，直接退出

设计红线（沿用火种 v9 + 活网 v1）：
  · 不改火种一个字节：fireup.py 作为子进程、独立 cwd 运行，闸门只读；
  · 不提供跳过参数：要跳火种就直接跑 run.py，绕过本入口——本文件不帮这个忙；
  · 只用标准库；火种缺失/退出码异常一律视为拒绝，不做容错放行。

用法：
    python 点火.py                     # 默认 ../火种 点火，通过后跑 run.py
    python 点火.py --seed <火种目录>    # 指定火种位置
    python 点火.py --check-only        # 只跑闸门，不启动模型
    python 点火.py --show              # 只读打印火种当前有效锚
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
# 火种嵌在本包体内（融合成一体）：默认 ./火种；体外 ../火种 仅作兼容回退。
EMBEDDED_SEED = os.path.join(ROOT, "火种")
OUTER_SEED = os.path.normpath(os.path.join(ROOT, os.pardir, "火种"))
DEFAULT_SEED = EMBEDDED_SEED if os.path.isdir(EMBEDDED_SEED) else OUTER_SEED

EXIT_NO_SEED = 10       # 火种目录 / fireup.py 缺失
EXIT_GATE_FAIL = 11     # 火种闸门拒绝或非 0


def run(cmd, cwd, env):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="火种闸门 × 活网 合成入口")
    ap.add_argument("--seed", default=DEFAULT_SEED, help="火种目录（默认 ../火种）")
    ap.add_argument("--check-only", action="store_true", help="只跑点火闸门，不启动模型")
    ap.add_argument("--show", action="store_true", help="只打印火种当前有效锚")
    args = ap.parse_args()

    seed = os.path.abspath(args.seed)
    fireup = os.path.join(seed, "fireup.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    print("=" * 68)
    print("火种 × 活网 · 合成入口")
    print("=" * 68)
    print(f"包根   {ROOT}")
    print(f"火种   {seed}")

    if not os.path.isfile(fireup):
        print(f"✗ 火种校验器不存在：{fireup}")
        print("→ 禁止加载：任何模型、调度、记忆逻辑一律不启动")
        return EXIT_NO_SEED

    if args.show:
        r = run([sys.executable, "fireup.py", "show"], seed, env)
        print((r.stdout or r.stderr).strip())
        return r.returncode

    # —— 闸门：火种 check，独立 cwd，不改火种任何字节 ——
    print("\n" + "=" * 68)
    print("【闸门】火种 fireup.py check")
    print("=" * 68)
    r = run([sys.executable, "fireup.py", "check"], seed, env)
    print((r.stdout or r.stderr).rstrip())
    if r.returncode != 0:
        print(f"\n✗ 点火闸门拒绝（退出码 {r.returncode}）")
        print("→ 禁止加载：任何模型、调度、记忆逻辑一律不启动")
        return EXIT_GATE_FAIL
    print("\n✓ 点火放行 → 允许加载活网")

    if args.check_only:
        print("--check-only：只验闸门，模型未启动")
        return 0

    # —— 闸门过后才加载活网八步自检 ——
    runpy = os.path.join(ROOT, "run.py")
    if not os.path.isfile(runpy):
        print(f"✗ 活网入口不存在：{runpy}")
        return 2
    print("\n" + "=" * 68)
    print("【活网】run.py 八步自检")
    print("=" * 68)
    r2 = run([sys.executable, "run.py"], ROOT, env)
    print((r2.stdout or r2.stderr).rstrip())
    if r2.returncode != 0:
        print(f"\n✗ 活网自检失败（退出码 {r2.returncode}）")
    else:
        print("\n★ 火种放行 + 活网自检通过 —— 合成入口完整跑通")
    return r2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
