#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规模审计：这摊东西现在到底"多大"
================================
不猜，只数。数四样：参数位、判据原子、外部信号条目、独立样本数。
判据：外部信号碰过的参数位 / 全部参数位 —— 低于 5% 就还只是"画好的网"。
"""
import json, os, glob

BASE = os.path.dirname(os.path.abspath(__file__))


def atoms(obj, n=0):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("must_all", "must_none", "num_range", "joins"):
                n += len(v) if isinstance(v, list) else 1
            else:
                n = atoms(v, n)
    elif isinstance(obj, list):
        for v in obj:
            n = atoms(v, n)
    return n


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases", "真事-批量.json"))
    args = ap.parse_args()
    lx = json.load(open(os.path.join(BASE, "lexicon_v2.json"), encoding="utf-8"))
    cells = lx["cells"]
    rel_cells = [c for c in cells.values() if c.get("kind") == "relation"] if isinstance(cells, dict) else []
    # 结构兜底：dict 或 list 都数得出总数
    n_cells = len(cells)
    crit = json.load(open(os.path.join(BASE, "cases", "批评者.json"), encoding="utf-8"))
    n_crit = len(crit["critics"])
    issues = crit["issues"]
    touched_cells = sorted({it["cell"] for it in issues})

    ck_files = [os.path.join(BASE, "checks", f) for f in
                ("校验器-v2-关系表.json", "校验器-v2-域表.json", "校验器-v2-跨表.json", "真事-校验器.json")]
    a = sum(atoms(json.load(open(f, encoding="utf-8"))) for f in ck_files if os.path.exists(f))

    vetoes = sum(1 for _ in open(os.path.join(BASE, "ledger_public", "vetoes.jsonl"), encoding="utf-8"))
    ext_signal = len(issues) + vetoes

    cases = [f for f in glob.glob(os.path.join(BASE, "cases", "*.json"))
             if "批评者" not in f]
    # 独立样本：批量跑的真事件数（跨域只是同一件的切片，不算新样本）
    batch = args.case
    n_samples = len(json.load(open(batch, encoding="utf-8"))["cases"]) if os.path.exists(batch) else 1

    slots = n_cells * n_crit
    touched_slots = len(touched_cells) * n_crit

    print(f"参数位：{n_cells} 格 × {n_crit} 批评者 = {slots}")
    print(f"判据原子（我写的）：{a} 条")
    print(f"外部信号（别人给的）：{ext_signal} 条＝议题 {len(issues)} + 否决 {vetoes}，只落在 {len(touched_cells)} 个格（{'/'.join(touched_cells)}）")
    print(f"→ 外部信号碰过的参数位 {touched_slots}/{slots} = {touched_slots/slots:.1%}"
          f"；其余 {(slots-touched_slots)/slots:.1%} 仍是我的判据在充数")
    print(f"独立样本：{n_samples} 件真事（cases 下 {len(cases)} 个文件，跨域是同一件的切片）"
          f"→ 每格观测数 {n_samples}，权重学不出来")
    print(f"判据 : 外部信号 = {a} : {ext_signal} ≈ {a/max(ext_signal,1):.0f} : 1")
    return {"slots": slots, "atoms": a, "ext": ext_signal, "covered": touched_slots}


if __name__ == "__main__":
    main()
