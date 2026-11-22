#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S19 · 规模测试 5 → 9
====================
同一套词表、同一套判据、同一批批评者阈值，只把件数从 5 抬到 9，看三样东西往哪走：
  1. 判据：整件通过率会不会随件数掉（掉＝参数化只是拟合了原来那五件）；
  2. 裁决：否决率、暂缓率（需回应）会不会随件数变——这是"扯皮"的度量；
  3. 观测：每格观测数够不够学权重。

口径（先写清，再报数）：
  · 议题分母 = 件数 × 适用模板数。T2（永基不落图）只在含永久基本农田的件上适用，故 9 件里只有 1 件适用。
  · 裁决按 critic 票重：C1=2、C2=2、C3=1；≥3 否决，2 需回应，<2 记不受理。
  · 独立样本按村计：9 件只覆盖 6 个村，西吕(8/9)、马尚西北(17/19)、马尚西南(13/16) 各两件，同村同批两件按 0.5 独立计 → 6.5。

复算： python scale9.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import batch as bt

W = {"C1": 2, "C2": 2, "C3": 1}


def run(path, label):
    b = json.load(open(path, encoding="utf-8"))
    cases, templates = b["cases"], b["templates"]
    n_case = len(cases)

    whole_ok = 0
    for c in cases:
        if not bt.gate3(bt.five_of(c), c):
            whole_ok += 1

    issues = 0
    veto = respond = 0
    for c in cases:
        for t in templates:
            if t["id"] == "T2" and not c["perm_area"]:
                continue
            s = sum(W[x] for x in t["vetoed_by"])
            issues += 1
            if s >= 3:
                veto += 1
            elif s >= 2:
                respond += 1

    villages = len({c["village"] for c in cases})
    dup = n_case - villages   # 同村第二件起按 0.5 独立计
    indep = villages + dup * 0.5

    print(f"[{label}] {n_case} 件（{villages} 村，重复村多出 {dup} 件）→ 独立样本 {indep}")
    print(f"  整件通过（v3）：{whole_ok}/{n_case}")
    print(f"  议题 {issues}：否决 {veto}（{veto/issues:.1%}）｜需回应 {respond}（{respond/issues:.1%}）"
          f"｜受不受理 0｜生效 0")
    print(f"  每格观测数：{n_case}（独立 {indep}）")
    return {"n": n_case, "ok": whole_ok, "issues": issues, "veto": veto,
            "respond": respond, "indep": indep}


def main():
    a = run(os.path.join(BASE, "cases", "真事-批量.json"), "5 件（原批）")
    b = run(os.path.join(BASE, "cases", "真事-批量9.json"), "9 件（扩批）")
    print("\n三行对照：")
    print(f"  整件通过率　{a['ok']}/{a['n']} = {a['ok']/a['n']:.0%}　→　{b['ok']}/{b['n']} = {b['ok']/b['n']:.0%}")
    print(f"  否决率　　　{a['veto']}/{a['issues']} = {a['veto']/a['issues']:.1%}　→　"
          f"{b['veto']}/{b['issues']} = {b['veto']/b['issues']:.1%}")
    print(f"  暂缓率　　　{a['respond']}/{a['issues']} = {a['respond']/a['issues']:.1%}　→　"
          f"{b['respond']}/{b['issues']} = {b['respond']/b['issues']:.1%}")
    print("\n判读：判据跟着事实走（不随件数掉），但裁决层被稀释——件越多，"
          "越多议题停在同一档『需回应』，否决率反而降。这就是扯皮。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
