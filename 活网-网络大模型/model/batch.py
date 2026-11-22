#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量：同一套 60 格 × 3 批评者，换五件真事跑
==========================================
五件都是张店区同一年度的征地补偿安置方案公告（6 / 9 / 17 / 19 / 35 号）。
看的不是通过率高低，是三样东西：
  1. 现行判据（写死 6 号那套）里，哪些格换件就崩 —— 件绑定；
  2. 把判据改成"跟事实字段比"之后，正例还通不通、错例还拦不拦；
  3. 批评者的议题在不同件上触发率，哪条是域通用、哪条要挂条件。

用法：
    python3 batch.py all
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import checker_v2 as ck

BATCH = os.path.join(BASE, "cases", "真事-批量.json")
CRIT = os.path.join(BASE, "cases", "批评者.json")
FIVE = ["who", "rule", "basis", "harm", "comp"]


def load_cases():
    return json.load(open(BATCH, encoding="utf-8"))["cases"]


def five_of(c):
    rule = f"按{c['level']}级区片综合地价{c['price']}万元/公顷执行"
    if c["perm_area"]:
        rule += f"，其中永久基本农田{c['perm_price']}万元/公顷"
    return {
        "who": f"{c['village']}集体土地所有权人、使用权人（{c['village']}村民委员会及被征地农户）",
        "rule": rule,
        "basis": "鲁政字〔2023〕144号（山东省征地区片综合地价批复）",
        "harm": f"{c['village']}失去{c['land']}{c['area']}公顷（{c['land_detail']}）",
        "comp": f"货币安置（土地补偿费与安置补助费约{c['amount']}万元，拨付{c['village']}村民委员会账户）＋被征地农民养老保险（鲁人社规〔2023〕3号）",
    }


def gate(p, dom="LW", rel="compensation"):
    """现行判据（写死 6 号那套）。返回 ({格: 层}, {跨表未过的格})"""
    rel_c, dom_c, joins = ck.load(ck.REL_CHECKS), ck.load(ck.DOM_CHECKS), ck.load(ck.JOIN_CHECKS)["joins"]
    bad, badj = {}, set()
    for f in FIVE:
        issues, layer = ck.check_field(f, p, rel, dom, rel_c, dom_c, joins)
        if issues:
            if layer == "跨表":
                badj.add(f)
            else:
                bad[f] = layer
    return bad, badj


def join_strict(p):
    """跨表算式：缺永久基本农田的件，S_perm 取不到值 → 算式不成立（现行写法）"""
    _, badj = gate(p)
    return "comp" not in badj


def expect_amount(c):
    return (c["area"] - c["perm_area"]) * c["price"] + c["perm_area"] * (c["perm_price"] or c["price"])


def gate3(p, c):
    """回灌后：v3 参数化判据（认字段、查表）+ 跨表缺省"""
    rel_c, dom_c, joins = ck.load(ck.REL_CHECKS), ck.load(ck.DOM_CHECKS), ck.load(ck.JOIN_CHECKS)["joins"]
    bad = {}
    for f in FIVE:
        issues, layer = ck.check_field(f, p, "compensation", "LW", rel_c, dom_c, joins, facts=c)
        if issues:
            bad[f] = (layer, issues)
    return bad


def neg_variants(p, cases, c):
    """错例：把本件的单价/面积换成另一件的（同一套文案，错一处）"""
    other = next(x for x in cases if x["id"] != c["id"] and x["price"] != c["price"])
    q = dict(p)
    q["rule"] = q["rule"].replace(str(c["price"]), str(other["price"]), 1)
    other2 = next(x for x in cases if x["id"] != c["id"] and x["area"] != c["area"])
    r = dict(p)
    r["harm"] = r["harm"].replace(str(c["area"]), str(other2["area"]), 1)
    return {"换单价→" + str(other["price"]): q, "换面积→" + str(other2["area"]): r}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=BATCH)
    a = ap.parse_args()
    batch_path = a.case
    batch = json.load(open(batch_path, encoding="utf-8"))
    cases = batch["cases"]
    N = len(cases)
    crit = json.load(open(CRIT, encoding="utf-8"))
    w = {x["id"]: x["weight"] for x in crit["critics"]}
    per_v2 = {f: 0 for f in FIVE}
    per_v3 = {f: 0 for f in FIVE}
    per_v2["comp_amount"] = per_v3["comp_amount"] = 0

    print(f"零、口径：{os.path.basename(batch_path)}｜{N} 件｜"
          f"区片 {sorted({c['level'] for c in cases})}｜村 {len({c['village'] for c in cases})} 个")
    print(f"一、回灌前（v2 认字）／回灌后（v3 认字段·查表）× {N} 件")
    print(f"{'件':<7}{'':3}{'who':<6}{'rule':<6}{'basis':<7}{'harm':<6}{'comp':<6}{'跨表':<7}整件")
    for c in cases:
        p = five_of(c)
        bad2, badj2 = gate(p)
        ok2 = (not bad2) and ("comp" not in badj2)
        bad3 = gate3(p, c)
        ok3 = not bad3
        for tag, bad, ok in (("前", bad2, ok2), ("后", bad3, ok3)):
            marks = "".join(("✓".ljust(6) if f not in bad else "✗".ljust(6)) for f in FIVE)
            js = "✓" if "comp" not in (badj2 if tag == "前" else {k for k, v in bad.items() if v[0] == "跨表"}) else "✗"
            print(f"{c['id'] if tag == '前' else '':<7}{tag:<3}{marks}{'':1}{js:<7}"
                  f"{'通' if ok else '拒'}")
            for f in FIVE:
                if f not in bad:
                    (per_v2 if tag == "前" else per_v3)[f] += 1
            if js == "✓":
                (per_v2 if tag == "前" else per_v3)["comp_amount"] += 1

    print("\n二、逐格跨件通过率：回灌前 → 回灌后")
    for f in list(FIVE) + ["comp_amount"]:
        a2, b = per_v2[f], per_v3[f]
        kind = "稳定" if b == N else ("件绑定" if b <= 1 else "摇摆")
        print(f"  {f:<12}{a2}/{N} → {b}/{N}　{kind}")

    print("\n三、跨表算式")
    dflt = sum(1 for c in cases if abs(c["amount"] - expect_amount(c)) <= 1.0)
    print(f"  加缺省（无永基则 S_perm=0、P_perm=P）：{dflt}/{len(cases)} 件算得对")

    print("\n四、错例：同一批错值，两版各拦多少")
    neg2 = neg3 = 0
    details = []
    for c in cases:
        p = five_of(c)
        for name, q in neg_variants(p, cases, c).items():
            b2, bj2 = gate(q)
            if b2 or ("comp" in bj2):
                neg2 += 1
            if gate3(q, c):
                neg3 += 1
            else:
                details.append(f"{c['id']} {name} v3 漏放")
    print(f"  v2 拦下 {neg2}/{len(cases)*2}　v3 拦下 {neg3}/{len(cases)*2}")
    for d in details:
        print("  ! " + d)

    print(f"\n五、批评者议题 × {N} 件（触发率与裁决）")
    print(f"{'模板':<5}{'格':<7}{'触发':<7}{'票重':<7}裁决")
    dist = {}
    for t in batch["templates"]:
        hit, scores = 0, set()
        for c in cases:
            if t["id"] == "T2" and not c["perm_area"]:
                continue
            hit += 1
            s = sum(w[x] for x in t["vetoed_by"])
            scores.add(s)
            dist["否决" if s >= 3 else "需回应"] = dist.get("否决" if s >= 3 else "需回应", 0) + 1
        sc = "/".join(str(s) for s in sorted(scores))
        print(f"{t['id']:<5}{t['cell']:<7}{str(hit)+'/'+str(len(cases)):<7}{sc:<7}"
              f"{'否决' if max(scores) >= 3 else '需回应'}")
    print(f"  触发率：T1 {len(cases)}/{len(cases)}，T2 {sum(1 for c in cases if c['perm_area'])}/{len(cases)}，"
          f"T3 {len(cases)}/{len(cases)}")
    print("  裁决分布：" + "，".join(f"{k} {v}" for k, v in dist.items()))
    return {"per_v2": per_v2, "per_v3": per_v3, "neg2": neg2, "neg3": neg3}


if __name__ == "__main__":
    main()
