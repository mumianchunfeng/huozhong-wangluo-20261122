#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验器 v2：把整块闸拆成 关系表 + 域表 + 跨表算式
=====================================================
v1 的闸是一整块：五项挨个查，查完说「填错」。
v2 拆三层：
    关系表   给谁 / 谁受损         —— 按关系存，跨域可带走
    域表     规则 / 依据 / 补偿     —— 按域存，换域重学
    跨表算式 补偿额 = 面积×单价      —— 两张表各取一边，算出一个数

用法：
    python3 checker_v2.py test      # 四候选×五格：旧闸 vs 新拆，逐格比
    python3 checker_v2.py audit     # 85 条历史明细：按栏目 / 按语义，各归哪层
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import netmodel as v1  # 旧闸与旧账本

REL_CHECKS = os.path.join(BASE, "checks", "校验器-v2-关系表.json")
DOM_CHECKS = os.path.join(BASE, "checks", "校验器-v2-域表.json")
JOIN_CHECKS = os.path.join(BASE, "checks", "校验器-v2-跨表.json")
PARAM_CHECKS = os.path.join(BASE, "checks", "校验器-v3-参数化.json")
TABLES = {"区片综合地价": os.path.join(BASE, "tables", "区片综合地价.json")}
OLD_CHECKS = os.path.join(BASE, "checks", "真事-校验器.json")
REAL_CASE = os.path.join(BASE, "cases", "真事-张征补2025-6号.json")
CROSS_CASE = os.path.join(BASE, "cases", "真事-跨域.json")

FIVE = ["who", "rule", "basis", "harm", "comp"]
REL_FIELDS = ["who", "harm"]
DOM_FIELDS = ["rule", "basis", "comp"]
FIVE_ZH = {"who": "给谁", "rule": "按什么规则", "basis": "依据哪份数据",
           "harm": "谁受损", "comp": "如何补偿"}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def spec_pass(v, spec):
    bad = []
    for group in spec.get("must_all", []):
        if not any(t in v for t in group):
            bad.append("缺要素：" + "／".join(group))
    for t in spec.get("must_none", []):
        if t in v:
            bad.append("含谬误：" + t)
    return bad


def join_value(join, p):
    vals = {}
    for name, spec in join["inputs"].items():
        m = re.search(spec["regex"], p.get(spec["field"]) or "")
        if not m:
            d = (join.get("defaults") or {}).get(name)
            if d is None:
                return None, f"取不到 {name}"
            if isinstance(d, dict) and d.get("from"):
                vals[name] = vals.get(d["from"], 0.0)
            else:
                vals[name] = float(d)
            continue
        vals[name] = float(m.group(1))
    return eval(join["expr"], {"__builtins__": {}}, vals), None


def norm_facts(f):
    """两套 facts 写法归一：真事-张征补（中文键）与 真事-批量（规范键）"""
    if "village" in f:
        return f
    village = re.search(r"镇([^镇]+村)$", f.get("被征地单位") or "")
    if not village:
        village = re.search(r"([\u4e00-\u9fa5]{2,6}村)$", f.get("被征地单位") or "")
    num = lambda s: float(re.search(r"(\d+(?:\.\d+)?)", s or "").group(1))
    return {
        "village": village.group(1) if village else "",
        "area": f.get("合计面积公顷"),
        "perm_area": f.get("合计永久基本农田公顷") or 0,
        "level": (f.get("区片") or "").replace("级", ""),
        "price": num(f.get("区片综合地价")),
        "perm_price": num(f.get("永久基本农田补偿") or "0"),
        "land": "农用地",
    }


def load_table(name):
    return load(TABLES[name])


def facts_pass(v, spec, facts):
    """v3：认字段、查表。facts 缺一个就判缺，不猜。"""
    bad = []
    v = v or ""
    for w in spec.get("forbid", []):
        if w in v:
            bad.append("含谬误：" + w)
    for c in spec["checks"]:
        mode, name = c["mode"], c.get("name", "")
        if c.get("when_positive") and not facts.get(c["when_positive"]):
            continue
        if mode == "contains":
            want = facts.get(c["fact"])
            if want is None or str(want) not in v:
                bad.append(f"缺要素：{name}（应为 {want}）")
        elif mode == "any_of":
            if not any(t in v for t in c["values"]):
                bad.append("缺要素：" + name)
        elif mode in ("extract_eq", "extract_eq_if"):
            m = re.search(c["regex"], v)
            want = facts.get(c["fact"])
            if not m:
                bad.append("提不出：" + name)
            elif abs(float(m.group(1)) - float(want)) > 1e-6:
                bad.append(f"{name} {m.group(1)} ≠ 事实 {want}")
        elif mode == "extract_eq_text":
            m = re.search(c["regex"], v)
            want = str(facts.get(c["fact"]))
            if not m:
                bad.append("提不出：" + name)
            elif m.group(1) != want:
                bad.append(f"{name} {m.group(1)} ≠ 事实 {want}")
        elif mode == "table_eq":
            tb = load_table(c["table"])
            pm = re.search(c["pair_regex"], v)
            if not pm:
                bad.append("拿不到等级或单价，无法查表")
                continue
            km, vm = pm.group(1), float(pm.group(2))
            tv = tb["prices"].get(km)
            if tv is None:
                bad.append(f"表缺档：{c['table']} 未填 {km} 级")
                continue
            if abs(vm - tv) > 1e-6:
                bad.append(f"查表不符：{km} 级应为 {tv}，文案写 {vm}")
            if abs(float(facts.get(c["fact"])) - tv) > 1e-6:
                bad.append(f"事实与表冲突：{c['fact']} {facts[c['fact']]} ≠ 表 {tv}")
        elif mode == "table_perm_eq":
            tb = load_table(c["table"])
            m = re.search(c["regex"], v)
            if not m:
                bad.append("缺要素：" + name)
            else:
                got = float(m.group(1))
                if abs(got - tb["perm_price"]) > 1e-6:
                    bad.append(f"{name} {got} ≠ 表 {tb['perm_price']}")
                if abs(float(facts.get(c["fact"]) or 0) - tb["perm_price"]) > 1e-6:
                    bad.append(f"事实与表冲突：{c['fact']}")
    return bad


def check_field(f, p, rel, dom, rel_c, dom_c, joins, facts=None):
    """一层一层查一格，返回 (问题列表, 判它的层)。带 facts 时走 v3 参数化判据。"""
    bad, layer = [], None
    if f in REL_FIELDS:
        layer = "关系表"
        spec = rel_c["by_relation"][rel][f]
    else:
        layer = "域表"
        spec = dom_c["by_domain"][dom][f]
    param = load(PARAM_CHECKS)["by_field"].get(f) if facts is not None else None
    if param:
        bad += facts_pass(p.get(f) or "", param, facts)
    else:
        bad += spec_pass(p.get(f) or "", spec)
    for j in joins:
        if j["target"]["field"] != f:
            continue
        val, err = join_value(j, p)
        if err:
            bad.append("跨表：" + err)
            layer = "跨表"
            continue
        m = re.search(j["target"]["regex"], p.get(f) or "")
        if not m:
            bad.append("跨表：补偿段里找不到金额")
            layer = "跨表"
            continue
        got = float(m.group(1))
        if abs(got - val) > j["tol"]:
            bad.append(f"跨表：金额 {got:.2f} 与算式 {val:.2f} {j['unit']} 不符")
            layer = "跨表"
    return bad, layer


# ---------------------------------------------------------------- 逐格比：旧闸 vs 新拆
def cmd_test(_a):
    case = load(REAL_CASE)
    checks = load(OLD_CHECKS)["checks"]
    rel_c = load(REL_CHECKS)
    dom_c = load(DOM_CHECKS)
    joins = load(JOIN_CHECKS)["joins"]
    # 参照真值：五格都用正确说法，每轮替换一格拿去试
    truth = {slot: next(c for c in case["claims"][slot] if _old_ok(c, slot, checks))
             for slot in FIVE}
    agree = diff = 0
    print(f"{'格':<6}{'旧闸':<6}{'新拆':<6}{'层':<8}候选（前 18 字）")
    for slot in FIVE:
        for cand in case["claims"][slot]:
            p = dict(truth)
            p[slot] = cand
            p["case"] = case["facts"]["文号"]
            old_ok, _ = v1.gate_case(p, checks)
            old_field_ok = slot not in [i["slot"] for i in v1.gate_case(p, checks)[1]]
            bad, layer = check_field(slot, p, "compensation", "LW", rel_c, dom_c, joins)
            new_ok = not bad
            same = old_field_ok == new_ok
            agree += 1 if same else 0
            diff += 0 if same else 1
            print(f"{FIVE_ZH[slot]:<6}{'过' if old_field_ok else '否':<6}"
                  f"{'过' if new_ok else '否':<6}{layer:<8}{cand[:18]}")
            if not same:
                print(f"       ↳ 分歧：旧={'过' if old_field_ok else '否'} 新={'过' if new_ok else '否'}｜{bad}")
    print(f"\n逐格比对：一致 {agree} 格，分歧 {diff} 格")
    return 0 if diff == 0 else 1


def _old_ok(cand, slot, checks):
    p = {k: "占位" for k in FIVE}
    p[slot] = cand
    return not any(i["slot"] == slot for i in v1.gate_case(p, checks)[1])


# ---------------------------------------------------------------- 回灌验收：旧闸 vs v3 参数化
def cmd_test3(_a):
    """同一批 20 格：旧闸（认字）vs v3（认字段＋查表）"""
    case = load(REAL_CASE)
    facts = norm_facts(case["facts"])
    checks = load(OLD_CHECKS)["checks"]
    rel_c, dom_c, joins = load(REL_CHECKS), load(DOM_CHECKS), load(JOIN_CHECKS)["joins"]
    truth = {slot: next(c for c in case["claims"][slot] if _old_ok(c, slot, checks))
             for slot in FIVE}
    agree = diff = 0
    print(f"{'格':<6}{'旧闸':<6}{'v3':<6}{'层':<8}候选（前 18 字）")
    for slot in FIVE:
        for cand in case["claims"][slot]:
            p = dict(truth)
            p[slot] = cand
            p["case"] = case["facts"]["文号"]
            old_field_ok = slot not in [i["slot"] for i in v1.gate_case(p, checks)[1]]
            bad, layer = check_field(slot, p, "compensation", "LW", rel_c, dom_c, joins, facts=facts)
            new_ok = not bad
            same = old_field_ok == new_ok
            agree += 1 if same else 0
            diff += 0 if same else 1
            print(f"{FIVE_ZH[slot]:<6}{'过' if old_field_ok else '否':<6}"
                  f"{'过' if new_ok else '否':<6}{layer:<8}{cand[:18]}")
            if not same:
                print(f"       ↳ 分歧：旧={'过' if old_field_ok else '否'} v3={'过' if new_ok else '否'}｜{bad}")
    print(f"\n回灌验收：一致 {agree} 格，分歧 {diff} 格")
    return 0 if diff == 0 else 1


# ---------------------------------------------------------------- 85 条明细归层
REL_KW = ["院上村", "农户", "集体经济组织", "村民委员会", "村集体", "建设用地", "1.4113",
          "耕地", "无主体受损", "人民政府", "建设单位", "土地使用权人"]
DOM_KW = ["112.5", "135", "永久基本农田", "鲁政字", "鲁自然资规", "市场评估价", "协商",
          "养老", "社会保障", "社保", "货币", "公告期", "听证", "专户", "账户",
          "补偿登记", "依据", "标准"]


def semantic_layer(detail):
    if "金额不在" in detail or "金额" in detail and "区间" in detail:
        return "跨表"
    if any(k in detail for k in REL_KW):
        return "关系表"
    if any(k in detail for k in DOM_KW):
        return "域表"
    return "未归类"


def cmd_audit(_a):
    counts = {"关系表": 0, "域表": 0, "跨表": 0, "未归类": 0}
    slot_layer = {"who": "关系表", "harm": "关系表",
                  "rule": "域表", "basis": "域表", "comp": "域表"}
    mismatch = []
    total = 0
    for p in ("ledger_real_串行40/rejects.jsonl", "ledger_real_并行40/rejects.jsonl"):
        fp = os.path.join(BASE, p)
        if not os.path.exists(fp):
            continue
        for line in open(fp, encoding="utf-8"):
            r = json.loads(line)
            for i in r["reasons"]:
                for d in i.get("detail", []):
                    total += 1
                    lay = semantic_layer(d)
                    counts[lay] += 1
                    if lay != "未归类" and lay != slot_layer[i["slot"]]:
                        mismatch.append((i["slot"], lay, d))
    print(f"历史明细 {total} 条")
    print("  按语义归层：" + "，".join(f"{k} {v}" for k, v in counts.items()))
    print(f"  栏目所在层 ≠ 语义所在层：{len(mismatch)} 条")
    for slot, lay, d in mismatch[:8]:
        print(f"    [{FIVE_ZH[slot]}栏 → {lay}] {d}")
    if len(mismatch) > 8:
        print(f"    …另 {len(mismatch) - 8} 条")
    return 0


def main():
    ap = argparse.ArgumentParser(description="校验器 v2 / v3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    sub.add_parser("test3")
    sub.add_parser("audit")
    a = ap.parse_args()
    if a.cmd == "test":
        return cmd_test(a)
    if a.cmd == "test3":
        return cmd_test3(a)
    return cmd_audit(a)


if __name__ == "__main__":
    raise SystemExit(main())
