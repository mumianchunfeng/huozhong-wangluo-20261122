#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S14 第二层聚合 + S16 裁决规则（一起做：先定谁赢，再合并）
==========================================================
S14：格 → 关系层（给谁 ∧ 谁受损）→ 域层（规则 ∧ 依据 ∧ 补偿）→ 跨表层（算得通）→ 件级一条结论。
S16：两层一起上，冲突就出现了。本件先写死四条裁决规则，再让聚合只按规则合并：

    K1 层间：关系层否、域层过 → 关系层胜（事实先于口径）
    K2 批评者：票重 ≥3 否决、2 需回应、<2 不受理；平票且无受影响者 → 冻结
    K3 件间：同一格多件结论不一 → 标「摇摆·件依赖」，不抹平成过或否
    K4 依赖：格与格互相取数成环 → 冻结（fail-closed，冻结不放行）

冻结不是失误，是设计：宁可不出结论，也不出一个靠猜的结论。
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import checker_v2 as ck

FIVE = ck.FIVE
BATCH = os.path.join(BASE, "cases", "真事-批量.json")
CRIT = os.path.join(BASE, "cases", "批评者.json")


def judge(p, facts):
    rel_c, dom_c, joins = ck.load(ck.REL_CHECKS), ck.load(ck.DOM_CHECKS), ck.load(ck.JOIN_CHECKS)["joins"]
    bad = {}
    for f in FIVE:
        issues, layer = ck.check_field(f, p, "compensation", "LW", rel_c, dom_c, joins, facts=facts)
        if issues:
            bad[f] = (layer, issues)
    return bad


def layers(bad):
    rel_ok = not any(f in bad for f in ("who", "harm"))
    dom_ok = all(f not in bad or bad[f][0] == "跨表" for f in ("rule", "basis", "comp"))
    join_ok = ("comp" not in bad) or bad["comp"][0] != "跨表"
    return {"关系层": rel_ok, "域层": dom_ok, "跨表层": join_ok}


def has_cycle(deps):
    """K4：格与格互相取数成环"""
    seen, stack = set(), []

    def dfs(n):
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n)
        stack.append(n)
        for m in deps.get(n, []):
            if dfs(m):
                return True
        stack.pop()
        return False

    return any(dfs(n) for n in deps)


def arbitrate(name, p, facts, veto=(), support=(), crit_weights=None, deps=None):
    """把一件的多层结论按 K1–K4 合成一条。"""
    bad = judge(p, facts)
    L = layers(bad)
    reasons, codes = [], []
    weights = crit_weights or {"C1": 2, "C2": 2, "C3": 1}
    no_score = sum(weights.get(c, 0) for c in veto)
    yes_score = sum(weights.get(c, 0) for c in support)
    net = no_score - yes_score
    affected_side = None
    for c in list(veto) + list(support):
        if c == "C1":
            affected_side = "否" if c in veto else "放"
    cycle = has_cycle(deps or {})
    tie = no_score > 0 and no_score == yes_score
    code = "—"

    # K1 层间优先
    if not L["关系层"] and L["域层"]:
        codes.append("K1")

    if cycle:
        verdict, code = "冻结", "K4"
        reasons.append("格与格互相取数成环，无法定序")
    elif not all(L.values()):
        verdict = "不成立"
        if codes:
            reasons.append("关系层否、域层过 → 关系层胜（事实先于口径）")
        for k, ok in L.items():
            if not ok:
                det = [f"{f}:{bad[f][1][0]}" for f in bad if f in ("who", "harm") and k == "关系层"
                       or f in ("rule", "basis") and k == "域层"
                       or bad[f][0] == "跨表" and k == "跨表层"]
                if det:
                    reasons.append(f"{k}未过：" + "；".join(det))
    elif tie and affected_side == "否":
        verdict, code = "不成立", "K2"
        reasons.append(f"票重相抵（否 {no_score}／放 {yes_score}），受影响者在否方 → 从否")
    elif tie and affected_side == "放":
        verdict, code = "成立", "K2"
        reasons.append(f"票重相抵（否 {no_score}／放 {yes_score}），受影响者在放方 → 从放")
    elif tie:
        verdict, code = "冻结", "K2"
        reasons.append(f"票重相抵（否 {no_score}／放 {yes_score}），无受影响者，无规则可依")
    elif net >= 3:
        verdict, code = "不成立", "—"
        reasons.append(f"否决分 {net}≥3")
    elif net >= 2:
        verdict, code = "暂缓", "—"
        reasons.append(f"否决分 {net}=2，需提案人书面回应")
    elif net >= 1:
        verdict, code = "成立", "—"
        reasons.append(f"否决分 {net}<2，单方异议不足以拦，记不受理")
    else:
        verdict, code = "成立", "—"
        reasons.append("三层全过，无有效否决")

    if code != "—" and code not in codes:
        codes.append(code)
    return {"件": name, "关系层": L["关系层"], "域层": L["域层"], "跨表层": L["跨表层"],
            "票重": net, "裁决": verdict, "规则": "+".join(codes) or "—", "理由": "；".join(reasons)}


def cross_case():
    """K3：同一格多件结论不一 → 摇摆保留，不抹平"""
    batch = json.load(open(BATCH, encoding="utf-8"))
    cells = FIVE + ["comp_amount"]
    res = {c: [] for c in cells}
    for c in batch["cases"]:
        p = {
            "who": f"{c['village']}集体土地所有权人、使用权人（{c['village']}村民委员会及被征地农户）",
            "rule": f"按{c['level']}级区片综合地价{c['price']}万元/公顷执行" + (
                f"，其中永久基本农田{c['perm_price']}万元/公顷" if c["perm_area"] else ""),
            "basis": "鲁政字〔2023〕144号（山东省征地区片综合地价批复）",
            "harm": f"{c['village']}失去{c['land']}{c['area']}公顷（{c['land_detail']}）",
            "comp": f"货币安置（土地补偿费与安置补助费约{c['amount']}万元，拨付{c['village']}村民委员会账户）＋被征地农民养老保险（鲁人社规〔2023〕3号）",
        }
        bad = judge(p, c)
        for f in FIVE:
            res[f].append(f not in bad)
        res["comp_amount"].append(("comp" not in bad) or bad["comp"][0] != "跨表")
    print("\n二、跨件聚合（K3：不抹平）")
    print(f"{'格':<13}{'通过':<8}聚合结论")
    for c in cells:
        n = sum(res[c])
        kind = "稳定" if n == 5 else ("崩" if n == 0 else "摇摆·件依赖")
        print(f"{c:<13}{n}/5{'':<4}{kind}")
    return res


def main():
    batch = json.load(open(BATCH, encoding="utf-8"))
    base = next(c for c in batch["cases"] if c["id"] == "ZD06")
    P = lambda: {
        "who": "院上村集体土地所有权人、使用权人（院上村村民委员会及被征地农户）",
        "rule": "按Ⅳ级区片综合地价112.5万元/公顷执行，其中永久基本农田135万元/公顷",
        "basis": "鲁政字〔2023〕144号（山东省征地区片综合地价批复）",
        "harm": "院上村失去农用地1.4113公顷（耕地0.2432公顷（含永久基本农田0.1936公顷））",
        "comp": "货币安置（土地补偿费与安置补助费约163.13万元，拨付院上村村民委员会账户）＋被征地农民养老保险（鲁人社规〔2023〕3号）",
    }
    scenes = []
    p = P(); scenes.append(("A1 正确件", p, set(), set(), None))
    p = P(); p["comp"] = p["comp"].replace("163.13", "158.77"); scenes.append(("A2 金额按全112.5算", p, set(), set(), None))
    p = P(); p["comp"] = "货币安置：约163.13万元，由房镇镇人民政府代管后统筹使用；并参加被征地农民养老保险（鲁人社规〔2023〕3号）"
    scenes.append(("A3 镇代管（关系人否）", p, {"C1"}, set(), None))
    p = P(); p["comp"] = p["comp"].replace("（含永久基本农田0.1936公顷）", "") + "（永久基本农田0.1936公顷暂不落图）"
    scenes.append(("A4 永基不落图", p, {"C1", "C2"}, set(), None))
    p = P(); p["who"] = "淄博市张店区人民政府（代行补偿）"; scenes.append(("A5 受偿主体记成政府", p, set(), set(), None))
    p = P(); scenes.append(("A6 等权相抵（无受影响者）", p, {"C2"}, {"C3"}, {"C2": 2, "C3": 2}))
    p = P(); scenes.append(("A7 面积与支付互相取数", p, set(), set(), None))

    print("一、件级聚合（S14）＋ 裁决（S16）")
    print(f"{'件':<28}{'关系':<5}{'域':<4}{'跨表':<5}{'净否决':<6}{'规则':<5}裁决")
    dist = {}
    for name, pp, veto, support, w in scenes:
        deps = {"harm": ["comp"], "comp": ["harm"]} if name.startswith("A7") else None
        r = arbitrate(name, pp, base, veto=veto, support=support, crit_weights=w, deps=deps)
        print(f"{name:<28}{'过' if r['关系层'] else '否':<5}{'过' if r['域层'] else '否':<4}"
              f"{'过' if r['跨表层'] else '否':<5}{r['票重']:<5}{r['规则']:<5}{r['裁决']}")
        if r["规则"] != "—":
            print(f"      ↳ {r['理由']}")
        dist[r["裁决"]] = dist.get(r["裁决"], 0) + 1
    print("\n裁决分布：" + "，".join(f"{k} {v}" for k, v in dist.items()))

    cross_case()

    print("\n三、批评者跨件（K3 同样适用）")
    crit = json.load(open(CRIT, encoding="utf-8"))
    w = {c["id"]: c["weight"] for c in crit["critics"]}
    for t in batch["templates"]:
        hit = sum(1 for c in batch["cases"] if not (t["id"] == "T2" and not c["perm_area"]))
        kind = "域通用" if hit == 5 else "摇摆·件依赖"
        print(f"  {t['id']} {t['name']:<20}触发 {hit}/5　{kind}"
              + (f"　条件 perm_area>0" if t["id"] == "T2" else ""))
    print(f"\n合计：件级裁决 {len(scenes)} 件 → 成立 {dist.get('成立', 0)}、不成立 {dist.get('不成立', 0)}、"
          f"暂缓 {dist.get('暂缓', 0)}、冻结 {dist.get('冻结', 0)}")
    return dist


if __name__ == "__main__":
    main()
