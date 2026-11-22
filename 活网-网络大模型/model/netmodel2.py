#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段三 · 下一版（v2）：把 144 格压成 60 格
================================================
依据「跨域对照」的实测：五项里只有两项是关系级，三项是域级。

    关系表（18 关系 × 2 项）：给谁、谁受损          → 36 格
    域表  （8 域   × 3 项）：规则、依据、如何补偿    → 24 格
                                            合计 60 格

与 v1（8 域 × 18 关系 = 144 格）的三处差别：
  1. 换域只可能丢域表那 3 项，关系表不受影响（v1 是整块归零）；
  2. 换域的重学量是 3 项，不是 3 项 × 关系数（v1 按关系存时要乘）；
  3. 换关系只丢关系表那 2 项，域表照旧可用。

用法：
    python3 netmodel2.py init
    python3 netmodel2.py tick   --n 30 --seed 20261122
    python3 netmodel2.py compare --n 30 --seed 20261122
    python3 netmodel2.py selfcheck
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
LEXICON2 = os.path.join(BASE, "lexicon_v2.json")
LEDGER2 = os.path.join(BASE, "ledger_v2")
CROSS_CASE = os.path.join(BASE, "cases", "真事-跨域.json")

DOMAINS = [("AR", "建筑"), ("LW", "法律"), ("SH", "航运"), ("AV", "航空"),
           ("MD", "医疗"), ("FI", "金融"), ("EN", "能源"), ("GV", "政务")]
RELATIONS = [("supply_demand", "供需"), ("ownership", "权属"), ("compensation", "补偿"),
             ("priority", "优先级"), ("trust", "信任"), ("risk", "风险"),
             ("exclusion", "排他"), ("mutual_aid", "互助"), ("arbitrage", "套利"),
             ("mortgage", "抵押"), ("transfer", "流转"), ("constraint", "约束"),
             ("privilege", "特权"), ("harm", "损害"), ("benefit", "收益"),
             ("allocation", "分配"), ("guarantee", "担保"), ("inheritance", "继承")]

FIVE = ["who", "rule", "basis", "harm", "comp"]
REL_FIELDS = ["who", "harm"]          # 关系级
DOM_FIELDS = ["rule", "basis", "comp"]  # 域级
FIVE_ZH = {"who": "给谁", "rule": "按什么规则", "basis": "依据哪份数据",
           "harm": "谁受损", "comp": "如何补偿"}


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def jappend(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 词表：60 格
def build_lexicon():
    cells = []
    for rc, rz in RELATIONS:
        for f in REL_FIELDS:
            cells.append({"kind": "rel", "relation": rc, "relation_zh": rz,
                          "field": f, "field_zh": FIVE_ZH[f],
                          "id": f"{rc}.{f}"})
    for dc, dz in DOMAINS:
        for f in DOM_FIELDS:
            cells.append({"kind": "dom", "domain": dc, "domain_zh": dz,
                          "field": f, "field_zh": FIVE_ZH[f],
                          "id": f"{dc}.{f}"})
    lex = {
        "_meta": {
            "schema": "net-lexicon/2.0",
            "note": "v2：两表拼一张。关系表管给谁/谁受损，域表管规则/依据/补偿。"
                    "依据=跨域对照实测（跨域-结论.md）。三域实验口径为 18×2+3×3=45；按八域为 18×2+8×3=60。",
            "relations": len(RELATIONS), "domains": len(DOMAINS),
            "rel_cells": len(RELATIONS) * len(REL_FIELDS),
            "dom_cells": len(DOMAINS) * len(DOM_FIELDS),
            "cells": len(cells),
        },
        "cells": cells,
    }
    with open(LEXICON2, "w", encoding="utf-8") as f:
        json.dump(lex, f, ensure_ascii=False, indent=2)
    return lex


def cmd_init(_args):
    os.makedirs(LEDGER2, exist_ok=True)
    lex = build_lexicon()
    m = lex["_meta"]
    print(f"v2 词表：{m['cells']} 格 = 关系表 {m['rel_cells']}（{m['relations']}×2）"
          f" + 域表 {m['dom_cells']}（{m['domains']}×3）")
    print(f"对照 v1 的 144 格（{m['domains']}×{m['relations']}），压掉 {144 - m['cells']} 格")
    return 0


# ---------------------------------------------------------------- 闸：按表路由
def gate(p, case, dom):
    """给谁/谁受损 查关系级判据；规则/依据/补偿 查域级判据。"""
    issues = []
    for f in FIVE:
        v = (p.get(f) or "").strip()
        if not v:
            issues.append({"field": f, "kind": "缺项", "detail": ["空"]})
            continue
        req = case["common"][f]["must"] if f in REL_FIELDS else case["domains"][dom][f]["must"]
        miss = [t for t in req if t not in v]
        if miss:
            issues.append({"field": f, "kind": "填错", "detail": ["缺:" + "／".join(miss)]})
    return (not issues), issues


def correct_value(case, f, dom):
    return case["common"][f]["value"] if f in REL_FIELDS else case["domains"][dom][f]["value"]


def paths():
    return (os.path.join(LEDGER2, "events.jsonl"), os.path.join(LEDGER2, "rejects.jsonl"),
            os.path.join(LEDGER2, "state.json"))


# ---------------------------------------------------------------- 跑
def cmd_tick(args):
    case = load_json(args.case)
    doms = list(case["domains"].keys())
    rels = case["relations"]
    ev_p, rj_p, st_p = paths()
    for p in (ev_p, rj_p, st_p):
        if os.path.exists(p):
            os.remove(p)
    s = {"tick": 0, "rel": {}, "dom": {}, "history": [], "writes": {}}
    for _ in range(args.n):
        s["tick"] += 1
        t = s["tick"]
        blk = (t - 1) // 10
        dom = doms[blk % len(doms)]
        rel = rels[(t - 1) % len(rels)]
        switched = (t - 1) % 10 == 0 and blk > 0
        p = {"id": f"V{t:04d}", "at": now(), "domain": dom, "relation": rel}
        rel_store = s["rel"].get(rel, {})
        dom_store = s["dom"].get(dom, {})
        for f in FIVE:
            p[f] = rel_store.get(f) if f in REL_FIELDS else dom_store.get(f)
            p[f] = p[f] or case["naive"][f]
        ok, issues = gate(p, case, dom)
        writes = {"rel": 0, "dom": 0}
        if ok:
            jappend(ev_p, p)
        else:
            jappend(rj_p, {"id": p["id"], "at": p["at"], "domain": dom, "relation": rel,
                           "reasons": issues})
            for i in issues:                       # 一次补齐，只补该补的那张表
                f = i["field"]
                if f in REL_FIELDS:
                    s["rel"].setdefault(rel, {})[f] = correct_value(case, f, dom)
                    writes["rel"] += 1
                else:
                    s["dom"].setdefault(dom, {})[f] = correct_value(case, f, dom)
                    writes["dom"] += 1
        if switched:                               # 本次换域的重学量
            key = f"开关{blk}"
            s["writes"][key] = s["writes"].get(key, 0) + writes["rel"] + writes["dom"]
        s["history"].append({"tick": t, "block": blk, "domain": dom, "relation": rel,
                             "switched": switched, "result": "pass" if ok else "reject",
                             "writes": writes,
                             "pass_fields": [f for f in FIVE if not any(i["field"] == f for i in issues)]})
        with open(st_p, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    return report_v2(s, args.n, case)


def _rate(xs):
    return (sum(1 for x in xs if x["result"] == "pass") / len(xs)) if xs else 0.0


def report_v2(s, n, case):
    h = s["history"]
    sw = [x for x in h if x["switched"]]
    after = [x for x in h if x["block"] > 0]
    base = [x for x in h if x["block"] == 0]
    keep = {f: (sum(1 for x in sw if f in x["pass_fields"]) / len(sw) if sw else 0.0) for f in FIVE}
    kept = [FIVE_ZH[f] for f in FIVE if keep[f] >= 0.99]
    print(f"v2（60 格）｜换域首拍保持 {len(kept)}/5（{'、'.join(kept) or '无'}）"
          f"｜跨域段 {_rate(after):.2f}｜A段 {_rate(base):.2f}")
    print("  分项保持：" + "，".join(f"{FIVE_ZH[f]} {keep[f]:.2f}" for f in FIVE))
    if sw:
        print("  换域重学项：" + "，".join(f"{k} {v}" for k, v in s["writes"].items()))
    return {"keep": keep, "after": _rate(after), "base": _rate(base), "writes": s["writes"]}


# ---------------------------------------------------------------- 三版对照
def cmd_compare(args):
    import netmodel as v1
    rows = {}
    for key, tag in (("domain", "v1·域键"), ("relation", "v1·关系键")):
        ns = argparse.Namespace(case=args.case, n=args.n, seed=args.seed, key=key)
        r = v1.cmd_cross(ns)
        ev, rj, _ = (os.path.join(BASE, f"ledger_cross_{key}", "events.jsonl"),
                     os.path.join(BASE, f"ledger_cross_{key}", "rejects.jsonl"),
                     os.path.join(BASE, f"ledger_cross_{key}", "state.json"))
        writes = sum(len(x["reasons"]) for x in v1.jread(rj) if ((x.get("key") or "") != ""))
        rows[tag] = {"keep": r["keep"], "after": r["after"], "writes": writes}
    print("=" * 64)
    r2 = cmd_tick(argparse.Namespace(case=args.case, n=args.n))
    print("=" * 64)
    print("三版对照（同一批真事、同一套判据、同 30 拍）")
    print(f"  v1 域键　：换域首拍保持 {sum(1 for f in FIVE if rows['v1·域键']['keep'][f] >= .99)}/5"
          f"｜跨域段 {rows['v1·域键']['after']:.2f}｜全程重学项 {rows['v1·域键']['writes']}")
    print(f"  v1 关系键：换域首拍保持 {sum(1 for f in FIVE if rows['v1·关系键']['keep'][f] >= .99)}/5"
          f"｜跨域段 {rows['v1·关系键']['after']:.2f}｜全程重学项 {rows['v1·关系键']['writes']}")
    w2 = sum(r2["writes"].values())
    print(f"  v2 六十格：换域首拍保持 {sum(1 for f in FIVE if r2['keep'][f] >= .99)}/5"
          f"｜跨域段 {r2['after']:.2f}｜换域重学项 {w2}")
    print("  读法：换域首拍保持说明关系层没丢；重学项说明域层要补多少。"
          "v2 只补域表 3 项，v1 关系键要把 3 项按关系各补一遍。")
    return 0


# ---------------------------------------------------------------- 自检
def cmd_selfcheck(_args):
    case = load_json(CROSS_CASE)
    bad = 0
    for dom in case["domains"]:
        p = dict(case["naive"])
        ok, _ = gate(p, case, dom)
        if ok:
            print(f"  ✗ {dom} 域：naive 竟被判通过")
            bad += 1
        q = {f: correct_value(case, f, dom) for f in FIVE}
        ok2, issues = gate(q, case, dom)
        if not ok2:
            print(f"  ✗ {dom} 域：正确值被拒 {issues}")
            bad += 1
    print("自检：naive 全否、正确值全过" if not bad else f"自检：{bad} 处异常")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="阶段三 · v2（60 格）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    for name in ("tick", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--case", default=CROSS_CASE)
        p.add_argument("--n", type=int, default=30)
        p.add_argument("--seed", type=int, default=None)
    sub.add_parser("selfcheck")
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init(a)
    if a.cmd == "tick":
        return cmd_tick(a)
    if a.cmd == "compare":
        return cmd_compare(a)
    if a.cmd == "selfcheck":
        return cmd_selfcheck(a)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
