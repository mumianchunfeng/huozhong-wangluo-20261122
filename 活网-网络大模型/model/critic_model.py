#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批评者登记与否决权重：补上被压掉的那一维
==========================================
v2 的 60 格只有一个判据来源（三层闸）。本件补另一样东西：
    同一格，在不同「受影响者」眼里，成立不成立并不一样。

于是词表真正的规模不是 60，而是 60 × 批评者数——除非实测发现不分叉。

规矩（与闸不混算）：
  1. 只收三层闸已经放过的议题；闸判得了的不进这里。
  2. 票重：受影响者 2、主管机关 2、出资方 1；合计 ≥3 否决，1–2 需回应，0 生效。
  3. 信用分：批准否的算命中（真值为「站得住」），命中率回写票重。

用法：
    python3 critic_model.py all
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import checker_v2 as ck
import netmodel as v1

CRITICS = os.path.join(BASE, "cases", "批评者.json")
CROSS_CASE = os.path.join(BASE, "cases", "真事-跨域.json")


def gate_proposal(p, dom, rel):
    rel_c = ck.load(ck.REL_CHECKS)
    dom_c = ck.load(ck.DOM_CHECKS)
    joins = ck.load(ck.JOIN_CHECKS)["joins"]
    bad = []
    for f in ck.FIVE:
        issues, layer = ck.check_field(f, p, rel, dom, rel_c, dom_c, joins)
        if issues:
            bad.append((f, layer, issues))
    return (not bad), bad


def run(verbose=True):
    data = json.load(open(CRITICS, encoding="utf-8"))
    case = json.load(open(CROSS_CASE, encoding="utf-8"))
    dom, rel = "LW", "compensation"
    base = {f: v1.correct_value(case, f, dom) for f in ck.FIVE}
    rule = data["weights_rule"]
    critics = data["critics"]
    w = {c["id"]: c["weight"] for c in critics}

    rows, diverge, gate_leak = [], 0, 0
    for it in data["issues"]:
        p = dict(base)
        p[it["cell"]] = it["text"]
        ok, bad = gate_proposal(p, dom, rel)
        if not ok:
            gate_leak += 1
            if verbose:
                print(f"  ! {it['id']} 本该闸过却没过：{[b[2][0] for b in bad]}")
        vet = it["vetoed_by"]
        score = sum(w[c] for c in vet)
        if score >= rule["sustain"]:
            verdict = "否决"
        elif score >= rule["respond"]:
            verdict = "需回应"
        elif score > 0:
            verdict = "不受理"
        else:
            verdict = "生效"
        if 0 < len(vet) < len(critics):
            diverge += 1
        rows.append((it, verdict, score, ok))

    if verbose:
        print(f"{'议题':<4}{'格':<6}{'闸':<4}" + "".join(f"{c['id']:<4}" for c in critics)
              + f"{'票重':<5}裁决")
        for it, verdict, score, ok in rows:
            cells = "".join(("否  " if c["id"] in it["vetoed_by"] else "·  ") .ljust(4) for c in critics)
            print(f"{it['id']:<4}{it['cell']:<6}{'过' if ok else '拒':<4}{cells}"
                  f"{score:<5}{verdict}")
        dist = {}
        for _, v_, _, _ in rows:
            dist[v_] = dist.get(v_, 0) + 1
        print(f"\n分叉议题 {diverge}/{len(rows)}（同格在不同批评者眼里结论不一致）"
              f"｜闸漏放 {gate_leak}")
        print("裁决分布：" + "，".join(f"{k} {v}" for k, v in dist.items()))

    # 信用分回写
    hit = {}
    for c in critics:
        mine = [it for it in data["issues"] if c["id"] in it["vetoed_by"]]
        good = sum(1 for it in mine if it["truth"] == "站得住")
        hit[c["id"]] = (good, len(mine))
        w[c["id"]] = round(min(c["weight"] * 1.5, c["weight"] * (0.5 + (good / len(mine) if mine else 0))), 2)
    if verbose:
        print("\n信用回写：" + "，".join(
            f"{c['id']} 命中 {hit[c['id']][0]}/{hit[c['id']][1]} → 票重 {c['weight']}→{w[c['id']]}"
            for c in critics))
        dist2 = {}
        for it, _, _, _ in rows:
            score = sum(w[c] for c in it["vetoed_by"])
            v2_ = "否决" if score >= rule["sustain"] else (
                "需回应" if score >= rule["respond"] else ("不受理" if score > 0 else "生效"))
            dist2[v2_] = dist2.get(v2_, 0) + 1
        print("回写后再裁：" + "，".join(f"{k} {v}" for k, v in dist2.items()))
    return {"diverge": diverge, "n": len(rows), "gate_leak": gate_leak, "weights": w}


def main():
    print(run.__doc__ or "")
    r = run(True)
    print(f"\n结论：{r['n']} 个议题里 {r['diverge']} 个分叉——"
          f"同一格换个人看结论就变，这一维不是可选的；词表实际规模 60×{3}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
