#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段三 · 网络即时模型（Net-Instant Model）
==========================================
不是一个模型，是一个**给任何模型套上的外壳**：
    取（take）  → 从账本取出这次该看到的前文
    跑（run）   → 任何模型/规则做一次推理（本文件用极笨规则代替）
    写（write） → 产物切成事件，过五项闸，能自证的入账

它有三条固定性质：
  1. 模型可换：本文件的 propose() 换成任何模型，账本不动；
  2. 账不换：状态全在 ledger/，进程随时可杀；
  3. 只有过闸的才叫事件，没过的叫驳回——驳回也记账，因为「此路不通」也是经验。

词表（lexicon）：
    词位 = 域 × 关系
    域 = 建筑/法律/航运/航空/医疗/金融/能源/政务（8）
    关系 = 关系引擎 18 类
    → 144 个词位。这是它的字母表；加一个域 = 多 18 个词位。

用法：
    python3 netmodel.py init
    python3 netmodel.py take   --domain FA --limit 5
    python3 netmodel.py tick   --n 40
    python3 netmodel.py stats
"""
import argparse
import json
import os
import random

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, "ledger")
EVENTS = os.path.join(LEDGER, "events.jsonl")
REJECTS = os.path.join(LEDGER, "rejects.jsonl")
STATE = os.path.join(LEDGER, "state.json")
LEXICON = os.path.join(BASE, "lexicon.json")

DOMAINS = [
    ("AR", "建筑"), ("LW", "法律"), ("SH", "航运"), ("AV", "航空"),
    ("MD", "医疗"), ("FI", "金融"), ("EN", "能源"), ("GV", "政务"),
]
RELATIONS = [
    ("supply_demand", "供需"), ("ownership", "权属"), ("compensation", "补偿"),
    ("priority", "优先级"), ("trust", "信任"), ("risk", "风险"),
    ("exclusion", "排他"), ("mutual_aid", "互助"), ("arbitrage", "套利"),
    ("mortgage", "抵押"), ("transfer", "流转"), ("constraint", "约束"),
    ("privilege", "特权"), ("harm", "损害"), ("benefit", "收益"),
    ("allocation", "分配"), ("guarantee", "担保"), ("inheritance", "继承"),
]

# 五项自证（规约第二章第 5 款 / 第四章第 1 款）
FIVE = ["who", "rule", "basis", "harm", "comp"]
FIVE_ZH = {"who": "给谁", "rule": "按什么规则", "basis": "依据哪份数据",
           "harm": "谁受损", "comp": "如何补偿"}

# 学习到的填法：只是把空槽填上模板，不是学会判断（README 已声明）
FILLERS = {
    "rule": "按规约第四章受益序：生存与安全刚需优先，不按出价",
    "harm": "同域既有供给方短期可得减少",
    "comp": "以同域等额额度补足，挂 compensation↔harm 约束对",
}


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def jappend(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def jread(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_state():
    if not os.path.exists(STATE):
        return {"tick": 0, "domain": DOMAINS[0][0], "slots": [], "history": []}
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save_state(s):
    os.makedirs(LEDGER, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- init
def build_lexicon():
    words = []
    for dc, dz in DOMAINS:
        for rc, rz in RELATIONS:
            words.append({"id": f"{dc}.{rc}", "domain": dc, "domain_zh": dz,
                          "relation": rc, "relation_zh": rz})
    lex = {
        "_meta": {
            "schema": "net-lexicon/1.0",
            "note": "占位词表：8 域 × 18 类是笛卡尔积，未筛无效组合。裁剪须留记录（谁裁、裁了哪些、为什么），不得静默删词。",
            "domains": len(DOMAINS), "relations": len(RELATIONS),
            "words": len(words),
        },
        "words": words,
    }
    with open(LEXICON, "w", encoding="utf-8") as f:
        json.dump(lex, f, ensure_ascii=False, indent=2)
    return lex


def cmd_init():
    """初始化。词表是输入，不是产物：已存在则只读，绝不重写。"""
    os.makedirs(LEDGER, exist_ok=True)
    full = len(DOMAINS) * len(RELATIONS)
    lex_path = LEXICON
    if os.path.exists(lex_path):
        lex = load_json(lex_path)
        words = lex.get("_meta", {}).get("words", "?")
        # 被裁剪过的词表：如实报出来，不恢复、不补全、不静默
        cut = full - (words if isinstance(words, int) else full)
        if cut > 0:
            print(f"词表：只读，未改。当前 {words} 个词位，比全域 {full} 个少 {cut} 个——已裁剪，本命令不恢复。")
        else:
            print(f"词表：只读，未改。{words} 个词位（{lex['_meta']['domains']} 域 × {lex['_meta']['relations']} 类）")
    else:
        lex = build_lexicon()
        print(f"已建词表：{lex['_meta']['words']} 个词位（{lex['_meta']['domains']} 域 × {lex['_meta']['relations']} 类）")
    if not os.path.exists(STATE):
        save_state({"tick": 0, "domain": DOMAINS[0][0], "slots": [], "history": []})
    print(f"账本目录：{LEDGER}")
    print("初始状态：三个空槽（规则 / 受损 / 补偿）——它天生只会填「给谁」和「依据哪份数据」。")
    return 0


# ---------------------------------------------------------------- 三动作
def take(domain, limit=5):
    """取：这次该看到的前文——同域最近事件 + 最近驳回理由。"""
    ev = [e for e in jread(EVENTS) if e.get("domain") == domain][-limit:]
    rj = [r for r in jread(REJECTS) if r.get("domain") == domain][-limit:]
    return {"domain": domain, "events": ev, "rejects": rj}


def propose(tick, domain, slots):
    """跑：极笨规则提议器。换成任何模型，只要吐同一种结构，下游不变。"""
    words = [w for w in json.load(open(LEXICON, encoding="utf-8"))["words"]
             if w["domain"] == domain]
    w = random.choice(words)
    p = {
        "id": f"E{tick:04d}",
        "at": now(),
        "domain": domain,
        "word": w["id"],
        "word_zh": f'{w["domain_zh"]}·{w["relation_zh"]}',
        "who": f'{w["domain_zh"]}-需求池-{tick % 5}',
        "basis": f"EV-{max(tick - 1, 0):04d} 的余额与同域关系",
        "rule": "", "harm": "", "comp": "",
    }
    for k in slots:
        if k in FILLERS:
            p[k] = FILLERS[k]
    return p


def gate(p):
    """闸：五项缺一即驳回。空串、空白、占位符都算缺。"""
    missing = []
    for k in FIVE:
        v = (p.get(k) or "").strip()
        if not v or v in {"待定", "TODO", "-", "略"}:
            missing.append(k)
    return (not missing), missing


def cmd_take(args):
    ctx = take(args.domain, args.limit)
    print(json.dumps(ctx, ensure_ascii=False, indent=2)[:2000])
    return 0


def cmd_tick(args):
    s = load_state()
    n = args.n
    for _ in range(n):
        s["tick"] += 1
        t = s["tick"]
        # 每 10 拍换一个域：换了域，旧经验不通用 —— 这是迁移成本，不是故障
        if t % 10 == 1 and t > 1 and not args.no_switch:
            i = [d[0] for d in DOMAINS].index(s["domain"])
            s["domain"] = DOMAINS[(i + 1) % len(DOMAINS)][0]
            s["slots"] = []          # 换域清空，重新学
        p = propose(t, s["domain"], s["slots"])
        ok, missing = gate(p)
        if ok:
            jappend(EVENTS, p)
            s["history"].append({"tick": t, "domain": s["domain"], "result": "pass"})
        else:
            r = {"id": p["id"], "at": p["at"], "domain": s["domain"],
                 "word": p["word"], "missing": missing,
                 "missing_zh": [FIVE_ZH[m] for m in missing]}
            jappend(REJECTS, r)
            s["history"].append({"tick": t, "domain": s["domain"],
                                 "result": "reject", "missing": missing})
            # 从驳回里学
            learnable = [m for m in missing if m in FILLERS and m not in s["slots"]]
            if args.parallel:
                # 并行：一次把缺的全都补上（这是「一次改多处」，纪律上不推荐，此处只作对照）
                s["slots"].extend(learnable)
            else:
                # 串行：一次只学一项（一次只改一处）
                for m in learnable:
                    s["slots"].append(m)
                    break
        save_state(s)
    _report(s, n)
    return 0


def _report(s, n):
    h = s["history"][-n:]
    line = "".join("✓" if x["result"] == "pass" else "×" for x in h)
    passes = sum(1 for x in h if x["result"] == "pass")
    print(f"跑 {n} 拍　{take.__module__ and ''}")
    print(f"  轨迹：{line}")
    print(f"  通过 {passes}　驳回 {n - passes}　通过率 {passes / n:.2f}")
    first = h[: n // 2]
    second = h[n // 2:]
    r1 = sum(1 for x in first if x["result"] == "pass") / max(len(first), 1)
    r2 = sum(1 for x in second if x["result"] == "pass") / max(len(second), 1)
    verdict = "下降" if r2 > r1 else ("持平" if abs(r2 - r1) < 0.05 else "上升")
    print(f"  前半段通过率 {r1:.2f} → 后半段 {r2:.2f}　驳回率{verdict}")
    print(f"  当前会填的槽：{s['slots'] or '（空）'}")


def cmd_stats(args):
    ev = jread(EVENTS)
    rj = jread(REJECTS)
    total = len(ev) + len(rj)
    print("=" * 60)
    print("账本统计")
    print("=" * 60)
    print(f"事件（过闸入账）：{len(ev)}")
    print(f"驳回（记下此路不通）：{len(rj)}")
    if total:
        print(f"总通过率：{len(ev) / total:.2f}")
    miss = {}
    for r in rj:
        for m in r.get("missing", []):
            miss[m] = miss.get(m, 0) + 1
    if miss:
        print("驳回时最常缺的项：")
        for k, v in sorted(miss.items(), key=lambda x: -x[1]):
            print(f"  {FIVE_ZH.get(k, k)}：{v} 次")
    used = {e["word"] for e in ev}
    print(f"用到的词位：{len(used)} / 144")
    s = load_state()
    print(f"当前拍：{s['tick']}　当前域：{s['domain']}")
    return 0


# ---------------------------------------------------------------- 真事模式
# 与占位跑法的区别：前文的槽由「随机填模板」改成「真事 + 候选说法」。
# 提议器只拿到 facts 与 claims（不标对错），对错由外部校验器判定 —— 所以驳回
# 的理由不再是「缺项」，而是「填错」：主体记错、标准用错、依据引错、标的算错、补偿漏项。
REAL_DIR = os.path.join(BASE, "ledger_real")
CASE_FILE = os.path.join(BASE, "cases", "真事-张征补2025-6号.json")
CHECK_FILE = os.path.join(BASE, "checks", "真事-校验器.json")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def real_paths():
    return (os.path.join(REAL_DIR, "events.jsonl"),
            os.path.join(REAL_DIR, "rejects.jsonl"),
            os.path.join(REAL_DIR, "state.json"))


def propose_case(case, s, tick):
    """真事提议器：每槽从候选说法里挑一条，已被驳回的挑不到（这是它唯一的学习）。"""
    p = {"id": f"R{tick:04d}", "at": now(), "case": case["facts"]["文号"],
         "domain": "LW", "word": "LW.ownership", "word_zh": "法律·权属"}
    for slot in FIVE:
        pool = [c for c in case["claims"][slot] if c not in s["bad"].get(slot, [])]
        p[slot] = random.choice(pool) if pool else ""
    return p


def _num_ok(v, rng):
    import re
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*万元", v)]
    return any(rng["min"] <= n <= rng["max"] for n in nums)


def gate_case(p, checks):
    """真事闸：五项逐项对要素。空槽=缺项，填了但对不上=填错（附明细）。"""
    issues = []
    for slot in FIVE:
        v = (p.get(slot) or "").strip()
        ck = checks[slot]
        if not v:
            issues.append({"slot": slot, "kind": "缺项", "why": f"{FIVE_ZH[slot]}为空"})
            continue
        bad = []
        for group in ck.get("must_all", []):
            if not any(tok in v for tok in group):
                bad.append("缺要素：" + "／".join(group))
        for tok in ck.get("must_none", []):
            if tok in v:
                bad.append("含谬误：" + tok)
        nr = ck.get("num_range")
        if nr and not _num_ok(v, nr):
            bad.append(f"金额不在 {nr['min']}–{nr['max']} {nr['unit']} 区间")
        if bad:
            issues.append({"slot": slot, "kind": "填错",
                           "why": ck.get("fail_hint", ""), "detail": bad})
    return (not issues), issues


def cmd_real(args):
    if getattr(args, "seed", None) is not None:
        random.seed(args.seed)
    case = load_json(args.case)
    checks = load_json(args.checks)["checks"]
    os.makedirs(REAL_DIR, exist_ok=True)
    ev_p, rj_p, st_p = real_paths()
    if args.reset:
        for p in (ev_p, rj_p, st_p):
            if os.path.exists(p):
                os.remove(p)
    s = {"tick": 0, "bad": {}, "history": []}
    if os.path.exists(st_p):
        s = load_json(st_p)
    for _ in range(args.n):
        s["tick"] += 1
        t = s["tick"]
        p = propose_case(case, s, t)
        ok, issues = gate_case(p, checks)
        if ok:
            jappend(ev_p, p)
            s["history"].append({"tick": t, "result": "pass"})
        else:
            jappend(rj_p, {"id": p["id"], "at": p["at"], "case": p["case"],
                           "reasons": issues})
            s["history"].append({"tick": t, "result": "reject",
                                 "kinds": [i["kind"] for i in issues],
                                 "slots": [i["slot"] for i in issues]})
            # 串行学：一拍只把「一条候选」打进黑名单（一次只改一处）
            targets = issues if args.parallel else issues[:1]
            for i in targets:
                v = p[i["slot"]]
                lst = s["bad"].setdefault(i["slot"], [])
                if v and v not in lst:
                    lst.append(v)
        with open(st_p, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    report_real(s, args.n, ev_p, rj_p, case)
    return 0


def report_real(s, n, ev_p, rj_p, case):
    h = s["history"][-n:]
    line = "".join("✓" if x["result"] == "pass" else "×" for x in h)
    passes = sum(1 for x in h if x["result"] == "pass")
    ev, rj = jread(ev_p), jread(rj_p)
    kinds, slots = {}, {}
    for r in rj:
        for i in r["reasons"]:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
            slots[i["slot"]] = slots.get(i["slot"], 0) + 1
    print(f"真事：{case['_meta']['title']}")
    print(f"跑 {n} 拍　累计 {s['tick']} 拍")
    print(f"  轨迹：{line}")
    print(f"  通过 {passes}　驳回 {n - passes}　通过率 {passes / n:.2f}")
    print(f"  驳回理由：" + "，".join(f"{k} {v} 次" for k, v in sorted(kinds.items(), key=lambda x: -x[1])) if kinds else "  驳回理由：无")
    if slots:
        print("  填错最多项：" + "，".join(f"{FIVE_ZH.get(k, k)} {v}" for k, v in sorted(slots.items(), key=lambda x: -x[1])))
    # 收敛：最后一次驳回之后的连续全过
    hist = s["history"]
    last_rej = max([i for i, x in enumerate(hist) if x["result"] != "pass"], default=-1)
    print(f"  最后一次驳回在第 {last_rej + 1} 拍，其后连续全过 {len(hist) - last_rej - 1} 拍")
    remain = {k: len([c for c in case["claims"][k] if c not in s["bad"].get(k, [])]) for k in FIVE}
    print("  各槽剩余未被否的候选：" + "，".join(f"{FIVE_ZH[k]}{remain[k]}" for k in FIVE))
    if rj:
        last = rj[-1]
        print("  最近一条驳回：")
        for i in last["reasons"]:
            print(f"    [{i['kind']}] {FIVE_ZH.get(i['slot'])}：{i['why']}")
            for d in i.get("detail", []):
                print(f"        · {d}")


def cmd_stats_real(args):
    ev_p, rj_p, st_p = real_paths()
    ev, rj = jread(ev_p), jread(rj_p)
    print("=" * 60)
    print("真事账本统计")
    print("=" * 60)
    print(f"事件（过闸入账）：{len(ev)}　驳回：{len(rj)}")
    kinds, slots = {}, {}
    for r in rj:
        for i in r["reasons"]:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
            slots[i["slot"]] = slots.get(i["slot"], 0) + 1
    print("驳回理由分布：" + ("，".join(f"{k} {v}" for k, v in kinds.items()) or "无"))
    print("按项：" + ("，".join(f"{FIVE_ZH.get(k, k)} {v}" for k, v in sorted(slots.items(), key=lambda x: -x[1])) or "无"))
    if os.path.exists(st_p):
        s = load_json(st_p)
        print(f"当前拍：{s['tick']}　已否候选：" + "，".join(f"{FIVE_ZH.get(k,k)} {len(v)}" for k, v in s["bad"].items()))
    return 0


# ---------------------------------------------------------------- 跨域对照：经验挂在谁身上
# 只改一处：state 里的学习键。key=domain → 经验按域存（换域即归零）；
# key=relation → 经验按关系存（换域可带走）。同一件真事、同一套要求，只换键。
CROSS_CASE = os.path.join(BASE, "cases", "真事-跨域.json")


def gate_cross(p, case, dom):
    """同一套五项目，按当前域的口径查：公共两项查 common，域级三项查该域。"""
    issues = []
    for f in FIVE:
        v = (p.get(f) or "").strip()
        if not v:
            issues.append({"slot": f, "kind": "缺项", "detail": ["空"]})
            continue
        req = case["common"][f]["must"] if f in case["common"] else case["domains"][dom][f]["must"]
        miss = [t for t in req if t not in v]
        if miss:
            issues.append({"slot": f, "kind": "填错", "detail": ["缺:" + "／".join(miss)]})
    return (not issues), issues


def correct_value(case, f, dom):
    return case["common"][f]["value"] if f in case["common"] else case["domains"][dom][f]["value"]


def cmd_cross(args):
    """A 段在同域学满，B/C 段换域：只改学习键，看经验能不能带走。
    学习用「一次补齐」（并行），把学费压到零，只留下迁移本身这一个变量。"""
    if args.seed is not None:
        random.seed(args.seed)
    case = load_json(args.case)
    doms = list(case["domains"].keys())
    rels = case["relations"]
    d = os.path.join(BASE, f"ledger_cross_{args.key}")
    os.makedirs(d, exist_ok=True)
    ev_p, rj_p, st_p = (os.path.join(d, "events.jsonl"), os.path.join(d, "rejects.jsonl"),
                        os.path.join(d, "state.json"))
    for p in (ev_p, rj_p, st_p):
        if os.path.exists(p):
            os.remove(p)
    s = {"tick": 0, "store": {}, "history": []}
    for _ in range(args.n):
        s["tick"] += 1
        t = s["tick"]
        blk = (t - 1) // 10
        dom = doms[blk % len(doms)]
        rel = rels[(t - 1) % len(rels)]
        switched = (t - 1) % 10 == 0 and blk > 0
        k = dom if args.key == "domain" else rel   # ← 唯一变量
        learned = s["store"].get(k, {})
        p = {"id": f"X{t:04d}", "at": now(), "domain": dom, "relation": rel, "key": k}
        for f in FIVE:
            p[f] = learned.get(f) or case["naive"][f]
        ok, issues = gate_cross(p, case, dom)
        if ok:
            jappend(ev_p, p)
        else:
            jappend(rj_p, {"id": p["id"], "at": p["at"], "domain": dom, "relation": rel,
                           "key": k, "reasons": issues})
            # 一次补齐：把当前键上所有填错的项改对（排除学费，只留迁移）
            for i in issues:
                s["store"].setdefault(k, {})[i["slot"]] = correct_value(case, i["slot"], dom)
        s["history"].append({"tick": t, "block": blk, "domain": dom, "relation": rel,
                             "switched": switched, "key": k,
                             "result": "pass" if ok else "reject",
                             "pass_fields": [f for f in FIVE if not any(i["slot"] == f for i in issues)]})
        with open(st_p, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    return report_cross(s, args.n, args.key)


def _rate(xs):
    return (sum(1 for x in xs if x["result"] == "pass") / len(xs)) if xs else 0.0


def report_cross(s, n, key):
    h = s["history"][-n:]
    sw = [x for x in h if x["switched"]]
    after = [x for x in h if x["block"] > 0]        # 跨域段（B+C）
    base = [x for x in h if x["block"] == 0]        # A 段（同域学满）
    keep = {f: (sum(1 for x in sw if f in x["pass_fields"]) / len(sw) if sw else 0.0) for f in FIVE}
    tag = "域" if key == "domain" else "关系"
    kept = [FIVE_ZH[f] for f in FIVE if keep[f] >= 0.99]
    print(f"键={tag}｜换域首拍保持 {len(kept)}/5{('（' + '、'.join(kept) + '）') if kept else '（全部归零）'}"
          f"｜分项保持 " + "，".join(f"{FIVE_ZH[f]} {keep[f]:.2f}" for f in FIVE))
    print(f"  〔参考，不作证据〕A段 {_rate(base):.2f}｜跨域段 {_rate(after):.2f}"
          f"——两把键的子键数不同（域 3 个块 / 关系 4 把），重学次数不等，总数不可直接比")
    return {"key": key, "switch": _rate(sw), "after": _rate(after), "base": _rate(base), "keep": keep}


def cmd_cross_both(args):
    """同一批真事，两把键各跑一遍，出三行数并给判定。"""
    res = {}
    for k in ("domain", "relation"):
        a = argparse.Namespace(case=args.case, n=args.n, seed=args.seed, key=k)
        res[k] = cmd_cross(a)
    d, r = res["domain"], res["relation"]
    print("=" * 60)
    print("判定：")
    away = [FIVE_ZH[f] for f in FIVE if r["keep"][f] >= 0.99 and d["keep"][f] < 0.5]
    stuck = [FIVE_ZH[f] for f in FIVE if r["keep"][f] < 0.5]
    print(f"  跟着关系走的项：{'、'.join(away) or '无'}")
    print(f"  跟着域走的项：{'、'.join(stuck) or '无'}")
    if away and stuck:
        print(f"  结论：一张 144 格的表压不到 18 格。可压成 18×2 + 3×3 = 45 格——"
              f"关系管 {len(away)} 项（{'、'.join(away)}），域管 {len(stuck)} 项（{'、'.join(stuck)}）。"
              f"强行统一按关系存，后面这 {len(stuck)} 项每换一次域都要重学。")
    elif away:
        print("  结论：跟关系走，域只是前缀——144 格可压成 18 格。")
    else:
        print("  结论：跟域走，换域即归零——关系键带不走经验。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="阶段三 · 网络即时模型")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p1 = sub.add_parser("take"); p1.add_argument("--domain", default="FA"); p1.add_argument("--limit", type=int, default=5)
    p2 = sub.add_parser("tick"); p2.add_argument("--n", type=int, default=40)
    p2.add_argument("--no-switch", action="store_true", help="固定在同一域，不换域（对照组）")
    p2.add_argument("--parallel", action="store_true", help="一次补齐所有缺项（对照：串行 vs 并行）")
    sub.add_parser("stats")
    p3 = sub.add_parser("real", help="真事入 propose()：用一件真实事项跑真闸")
    p3.add_argument("--case", default=CASE_FILE)
    p3.add_argument("--checks", default=CHECK_FILE)
    p3.add_argument("--n", type=int, default=40)
    p3.add_argument("--parallel", action="store_true", help="一次否掉所有填错的候选（对照）")
    p3.add_argument("--reset", action="store_true", help="清空 ledger_real 重新跑")
    p3.add_argument("--seed", type=int, default=None, help="固定随机种子，便于复算")
    sub.add_parser("stats-real")
    p4 = sub.add_parser("cross", help="跨域对照：只改学习键（域 / 关系）")
    p4.add_argument("--key", choices=["domain", "relation"], default="domain")
    p4.add_argument("--case", default=CROSS_CASE)
    p4.add_argument("--n", type=int, default=40)
    p4.add_argument("--seed", type=int, default=None)
    p4.add_argument("--reset", action="store_true")
    p5 = sub.add_parser("cross-both", help="两把键各跑一遍，出三行数与判定")
    p5.add_argument("--case", default=CROSS_CASE)
    p5.add_argument("--n", type=int, default=40)
    p5.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init()
    if a.cmd == "take":
        return cmd_take(a)
    if a.cmd == "tick":
        return cmd_tick(a)
    if a.cmd == "stats":
        return cmd_stats(a)
    if a.cmd == "real":
        return cmd_real(a)
    if a.cmd == "stats-real":
        return cmd_stats_real(a)
    if a.cmd == "cross":
        return cmd_cross(a)
    if a.cmd == "cross-both":
        return cmd_cross_both(a)


if __name__ == "__main__":
    raise SystemExit(main())
