#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公示期与否决通道（接在 v2 三层校验之后）
==========================================
规约第 6 款：签名只是记号，不是权力；一次动作成立，只因为「可复算、可公示、期内无人否决」。

本件补上后半句。状态机：
    提案 ──闸（三层）──✗──▶ 闸拒（不入公示，不进账）
                    └──✓──▶ 公示期（N 拍）──期内被否决──▶ 否决账（不得生效，留声）
                                      └──期满无否决──▶ 生效账（带公示记录）

三条纪律：
  1. 闸过的才进公示；进过公示的，才可能生效。闸与否决是两条账，不混算。
  2. 否决必须留声：谁、何时、依据哪份数据。否决人不写在权重里，写在账里。
  3. 本地仿真只演练流程，不产生正当性——否决人是本地记录，不是独立第三方。

用法：
    python3 publicity.py demo          # 四个提案走完：闸拒 / 生效 / 否决 / 改后生效
    python3 publicity.py show          # 看三本账：pending / events / vetoes
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import checker_v2 as ck
import netmodel as v1

PUB = os.path.join(BASE, "ledger_public")
PENDING = os.path.join(PUB, "pending.jsonl")
EVENTS = os.path.join(PUB, "events.jsonl")
VETOES = os.path.join(PUB, "vetoes.jsonl")
STATE = os.path.join(PUB, "state.json")
CROSS_CASE = os.path.join(BASE, "cases", "真事-跨域.json")
WINDOW = 3  # 公示期，以「拍」计


def now_tick(clock):
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc).astimezone()
    return (t0 + timedelta(minutes=clock)).isoformat(timespec="minutes")


def jappend(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def jread(path):
    if not os.path.exists(path):
        return []
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def jwrite(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"clock": 0, "seq": 0, "proposals": {}, "counters":
            {"闸拒": 0, "公示": 0, "否决": 0, "生效": 0}}


def save_state(s):
    os.makedirs(PUB, exist_ok=True)
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def reset():
    for p in (PENDING, EVENTS, VETOES, STATE):
        if os.path.exists(p):
            os.remove(p)


# ---------------------------------------------------------------- 三段
def evaluate(p, dom, rel, facts=None):
    """三层逐格查（关系表 / 域表 / 跨表算式）。带 facts 时走 v3 参数化判据。"""
    rel_c = ck.load(ck.REL_CHECKS)
    dom_c = ck.load(ck.DOM_CHECKS)
    joins = ck.load(ck.JOIN_CHECKS)["joins"]
    issues = []
    for f in ck.FIVE:
        bad, layer = ck.check_field(f, p, rel, dom, rel_c, dom_c, joins, facts=facts)
        if bad:
            issues.append({"field": f, "layer": layer, "detail": bad})
    return (not issues), issues


def submit(s, p, dom, rel, by, note="", facts=None):
    """提一件。闸不过则闸拒；过则进公示期。"""
    s["seq"] += 1
    pid = f"P{s['seq']:02d}"
    p = dict(p, id=pid, by=by, note=note, domain=dom, relation=rel,
             submitted_at=now_tick(s["clock"]))
    ok, issues = evaluate(p, dom, rel, facts)
    p["gate"] = {"ok": ok, "issues": issues}
    if not ok:
        p["state"] = "闸拒"
        s["counters"]["闸拒"] += 1
        s["proposals"][pid] = p
        print(f"  {pid} 闸拒：" + "；".join(f"[{i['layer']}]{FIVE_ZH(i['field'])} {i['detail'][0]}"
                                            for i in issues))
        save_state(s)
        return p
    p["state"] = "公示中"
    p["deadline"] = s["clock"] + WINDOW
    p["window"] = {"from": now_tick(s["clock"]), "to": now_tick(p["deadline"]), "ticks": WINDOW}
    s["counters"]["公示"] += 1
    s["proposals"][pid] = p
    _sync_pending(s)
    print(f"  {pid} 通闸（三层 0 问）→ 进公示期 {WINDOW} 拍（{p['window']['to']} 期满）")
    save_state(s)
    return p


def FIVE_ZH(f):
    return ck.FIVE_ZH.get(f, f)


def veto(s, pid, by, reason, basis):
    p = s["proposals"].get(pid)
    if not p or p["state"] != "公示中":
        print(f"  {pid} 不在公示期，否决不予受理")
        return False
    p["state"] = "已否决"
    p["veto"] = {"by": by, "at": now_tick(s["clock"]), "reason": reason, "basis": basis}
    s["counters"]["否决"] += 1
    jappend(VETOES, {"id": pid, "by": by, "at": p["veto"]["at"], "reason": reason,
                     "basis": basis, "domain": p["domain"], "relation": p["relation"]})
    print(f"  {pid} 被 {by} 否决（依 {basis}）：{reason}　→ 记入否决账，不得生效")
    save_state(s)
    return True


def advance(s, n=1):
    """走时钟 n 拍；期满无否决的转生效，并带公示记录。"""
    s["clock"] += n
    _close(s)
    _sync_pending(s)
    save_state(s)


def _sync_pending(s):
    """pending.jsonl 只留仍在公示期的；已否决/已生效的从这里消失（另两本账留痕）。"""
    rows = [{k: p[k] for k in ("id", "domain", "relation", "by", "window", "state", "deadline")}
            for p in s["proposals"].values() if p["state"] == "公示中"]
    jwrite(PENDING, rows)


def _close(s):
    for pid, p in s["proposals"].items():
        if p["state"] != "公示中":
            continue
        if p.get("deadline", 10 ** 9) <= s["clock"]:
            p["state"] = "生效"
            s["counters"]["生效"] += 1
            jappend(EVENTS, {"id": pid, "at": now_tick(s["clock"]), "by": p["by"],
                             "domain": p["domain"], "relation": p["relation"],
                             "window": p["window"], "vetoed": False,
                             "five": {f: p[f] for f in ck.FIVE}})
            print(f"  {pid} 公示期满、期内无人否决 → 生效（入 events.jsonl）")
    save_state(s)


def cmd_show(_a):
    for name, path in (("pending", PENDING), ("events", EVENTS), ("vetoes", VETOES)):
        rows = jread(path)
        print(f"[{name}] {len(rows)} 条")
        for r in rows[-4:]:
            print("   ", json.dumps({k: r.get(k) for k in list(r)[:5]}, ensure_ascii=False))
    if os.path.exists(STATE):
        print("[counters]", json.load(open(STATE, encoding="utf-8"))["counters"])
    return 0


def cmd_demo(_a):
    reset()
    case = ck.load(CROSS_CASE)
    dom, rel = "LW", "compensation"
    base = {f: v1.correct_value(case, f, dom) for f in ck.FIVE}
    facts = ck.norm_facts(ck.load(ck.REAL_CASE)["facts"])
    s = load_state()

    print("一、通闸 → 公示 → 期满生效")
    submit(s, base, dom, rel, by="张店·本人", note="院上村征收补偿第一版", facts=facts)
    advance(s, WINDOW)

    print("\n二、通闸但被相对人否决（闸看不见的错）")
    p2 = dict(base)
    p2["comp"] = ("货币安置：土地补偿费与安置补助费约163.13万元，由房镇镇人民政府代管后统筹使用；"
                  "并参加被征地农民养老保险（鲁人社规〔2023〕3号）")
    a = submit(s, p2, dom, rel, by="张店·本人", note="改由镇代管补偿费", facts=facts)
    veto(s, a["id"], by="院上村村民委员会",
         reason="补偿费应拨付本村账户，镇代管无依据；分配须由本集体经济组织成员讨论决定",
         basis="张征补公告〔2025〕6号 四（一）")
    advance(s, WINDOW)

    print("\n三、被否决后修改重提 → 再公示 → 生效")
    submit(s, dict(base), dom, rel, by="张店·本人", note="按否决意见改回本村账户", facts=facts)
    advance(s, WINDOW)

    print("\n四、闸不过的，连公示都进不去")
    p4 = dict(base)
    p4["basis"] = "张征补公告〔2025〕6号自身即为补偿标准依据"
    submit(s, p4, dom, rel, by="张店·本人", note="循环依据", facts=facts)

    print("\n统计：")
    c = s["counters"]
    print(f"  提案件数 {s['seq']}　闸拒 {c['闸拒']}　进公示 {c['公示']}　"
          f"被否决 {c['否决']}　生效 {c['生效']}")
    print(f"  三本账：公示中 {len(jread(PENDING))} / 生效 {len(jread(EVENTS))} / 否决 {len(jread(VETOES))}")
    print(f"  读法：进过公示的 {c['公示']} 件，被否决 {c['否决']} 件、生效 {c['生效']} 件；"
          f"被否决那件没有进 events.jsonl。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="公示期与否决通道")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    sub.add_parser("show")
    a = ap.parse_args()
    return cmd_demo(a) if a.cmd == "demo" else cmd_show(a)


if __name__ == "__main__":
    raise SystemExit(main())
