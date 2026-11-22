#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
S21 免疫层（immune）：仿生取机制——用「行为一致性」认自己人
==========================================================
不签名、不持钥、不设权威。取免疫系统的识别机制，不取密码学的外壳：

  · 细胞表面自身标志（MHC） → 行为谱：判过哪些格、各判过/否、口径 → 表现型 sig
  · 初次应答（慢、弱）       → 新 node_id 首包隔离观察，事件不进联邦账
  · 二次应答（快、强）       → 同节点多次行为一致，滴度累积，达阈值升「记忆节点」，
                              隔离事件一次性并入联邦账
  · 免疫记忆                 → 行为谱存档案，append-only，每次比对有基准
  · 异己反应                 → 判定翻转超容忍，滴度下降、进警戒账、当次隔离
  · 克隆选择（阴性选择）     → 对不上行为谱的，不并入

一句话：身份不是声明出来的，是多次一致行为累积出来的。

诚实边界（不粉饰）：
  1. 行为谱不是密码学身份。蓄意镜像另一个节点全部历史行为的「拟态攻击」，
     本层分辨不了——生物界也有拟态寄生，这是同源的边界，不是 bug。
  2. 本层只判「行为像不像认识的那个」，不判事件内容真假；内容真假归三层校验器。
  3. 默认关闭。设环境变量 LW_IMMUNE=1 才在 tentacle.absorb 前启用守卫；
     不设时原路径一字不改（装了本文件也不影响旧行为）。

用法：
  python immune.py status                    免疫网况
  python immune.py guard --bundle X.json     对一个包跑免疫筛查（返回码即判定）
  python immune.py selfcheck                 自检：三只羊（诚实/冒名/突变）

账（新增，均在 触须\免疫账\ 下，不动 tentacle 原有账）：
  身份档案.jsonl   append-only，每个节点每次状态变化追加一条，取末条为当前
  隔离账.jsonl     未成熟事件（新节点首包、异己反应当次）
  警戒账.jsonl     异己反应记录
"""
import argparse
import hashlib
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("LW_HOME") or BASE
TEN = os.path.join(HOME, "触须")
IMM = os.path.join(TEN, "免疫账")
PROFILE = os.path.join(IMM, "身份档案.jsonl")
QUAR = os.path.join(IMM, "隔离账.jsonl")
ALERT = os.path.join(IMM, "警戒账.jsonl")
FED = os.path.join(TEN, "联邦账.jsonl")

MATURE_AT = 3     # 滴度阈值：首次 + 2 次一致 → 升记忆节点
FLIP_TOL = 2      # 判定翻转容忍：≤2 格算正常演化，>2 格触发异己反应
COVER_MIN = 0.8   # 覆盖门槛：新包须覆盖基准 80% 以上的格才判「同一只」


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def jlines(p):
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def japp(p, rec):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def sig_of(events):
    """表现型标记：按 key 排序的 判值串 → 哈希。行为一样，sig 就一样。"""
    items = sorted((e["key"], "T" if e["v"] == "过" else "F") for e in events)
    s = "|".join(f"{k}:{v}" for k, v in items)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def profile_of(pack):
    h = pack["header"]
    ev = pack["events"]
    layers, yes, no = {}, 0, 0
    for e in ev:
        layers[e.get("layer", "?")] = layers.get(e.get("layer", "?"), 0) + 1
        yes += 1 if e["v"] == "过" else 0
        no += 1 if e["v"] != "过" else 0
    return {"sig": sig_of(ev), "cells": len(ev), "yes": yes, "no": no,
            "layers": layers, "rules": h.get("rules"),
            "vmap": {e["key"]: (e["v"] == "过") for e in ev}}


def latest(node_id):
    for r in reversed(jlines(PROFILE)):
        if r.get("node") == node_id:
            return r
    return None


def compare(vmap_now, base_vmap, base_cells):
    """返回 (翻转数, 覆盖数)。覆盖=本次判过的格里，基准里也有的。"""
    flip = sum(1 for k, v in vmap_now.items() if k in base_vmap and base_vmap[k] != v)
    cover = sum(1 for k in vmap_now if k in base_vmap)
    return flip, cover


def flush(node_id):
    """二次应答：把该节点隔离账里的事件一次性并入联邦账。直接写 federal，
    不调 tentacle.absorb，避免与守卫递归。"""
    rows = jlines(QUAR)
    mine, rest = [], []
    for r in rows:
        (mine if r.get("node") == node_id and not r.get("matured") else rest).append(r)
    if not mine:
        return 0
    tmp = QUAR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rest:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, QUAR)
    n = 0
    for r in mine:
        h = r.get("head", {})
        for e in r["events"]:
            japp(FED, {"at": now(), "node": node_id, "键": e["key"], "判": e["v"],
                       "层": e.get("layer", "?"), "口径": h.get("rules", "?"),
                       "水位": h.get("watermark", len(r["events"])), "免疫": "二次应答成熟"})
            n += 1
        japp(ALERT, {"at": now(), "node": node_id, "动作": "成熟并入",
                     "事件": len(r["events"]), "原隔离时间": r.get("at")})
    return n


def guard(pack, _node=None):
    """免疫守卫。返回 0=放行；非 0=拦截（3 初次隔离 / 4 异己反应）。"""
    h = pack["header"]
    nid = h.get("node_id", "?")
    prof = profile_of(pack)
    rec = latest(nid)

    if rec is None:
        # 初次应答即留下初始滴度 1（生物：首触已产生初始抗体），再两次一致达阈值成熟
        japp(PROFILE, {"at": now(), "node": nid, "state": "naive", "titer": 1,
                       "sig": prof["sig"], "rules": prof["rules"],
                       "cells": prof["cells"], "vmap": prof["vmap"]})
        japp(QUAR, {"at": now(), "node": nid, "sig": prof["sig"],
                    "head": h, "events": pack["events"], "reason": "初次应答·隔离观察"})
        return 3

    flip, cover = compare(prof["vmap"], rec.get("vmap", {}), rec.get("cells", 0))
    need_cover = max(1, int(COVER_MIN * rec.get("cells", 1)))

    if flip <= FLIP_TOL and cover >= need_cover:
        titer = rec.get("titer", 0) + 1
        # 滴度未达阈值前一律维持 naive（隔离观察）；只有到阈值才升记忆并放行。
        state = "memory" if titer >= MATURE_AT else "naive"
        japp(PROFILE, {"at": now(), "node": nid, "state": state, "titer": titer,
                       "sig": prof["sig"], "rules": prof["rules"],
                       "cells": prof["cells"], "vmap": prof["vmap"],
                       "flip": flip, "cover": cover})
        if state == "memory":
            if rec.get("state") != "memory":
                flush(nid)
                print(f"[免疫] {nid[:8]} 二次应答：滴度 {titer} 达阈值，隔离事件成熟并入")
            return 0
        # 滴度未成熟：本次仍隔离，但行为与首见一致，事件已在隔离账存过，
        # 不重复追加（否则成熟并入时会重复计账）。只更新滴度。
        return 3

    titer = max(0, rec.get("titer", 0) - 1)
    japp(ALERT, {"at": now(), "node": nid, "动作": "异己反应", "翻转": flip,
                 "覆盖": cover, "本次sig": prof["sig"], "基准sig": rec.get("sig"),
                 "滴度": titer})
    japp(PROFILE, {"at": now(), "node": nid, "state": "suspicious", "titer": titer,
                   "sig": rec.get("sig"), "rules": rec.get("rules"),
                   "cells": rec.get("cells"), "vmap": rec.get("vmap"),
                   "flip": flip, "cover": cover})
    japp(QUAR, {"at": now(), "node": nid, "sig": prof["sig"],
                "head": h, "events": pack["events"], "reason": "异己反应·当次隔离"})
    print(f"[免疫] {nid[:8]} 异己反应：翻转 {flip}＞容忍 {FLIP_TOL}，隔离并降滴度至 {titer}")
    return 4


def status(_a=None):
    profs, seen = {}, []
    for r in jlines(PROFILE):
        profs[r["node"]] = r
    for nid, r in profs.items():
        seen.append((nid[:8], r.get("state"), r.get("titer"), r.get("sig")))
    print(f"免疫档案：{len(profs)} 只｜隔离事件包：{len(jlines(QUAR))}｜警戒：{len(jlines(ALERT))}")
    for nid, st, t, sig in sorted(seen):
        print(f"  {nid}  {st:10} 滴度 {t}  sig {sig}")
    return 0


def guard_cmd(a):
    pack = json.load(open(a.bundle, encoding="utf-8"))
    rc = guard(pack)
    print("放行" if rc == 0 else f"拦截（退出码 {rc}）")
    return rc


def selfcheck(_a=None):
    """用三只羊自检：诚实节点成长、冒名首见隔离、突变节点异己反应。
    全在临时目录，不碰真实账。"""
    import shutil
    import tempfile
    global HOME, TEN, IMM, PROFILE, QUAR, ALERT, FED
    old = (HOME, TEN, IMM, PROFILE, QUAR, ALERT, FED)
    tmp = tempfile.mkdtemp(prefix="immune_")
    HOME = tmp
    TEN = os.path.join(HOME, "触须")
    IMM = os.path.join(TEN, "免疫账")
    PROFILE = os.path.join(IMM, "身份档案.jsonl")
    QUAR = os.path.join(IMM, "隔离账.jsonl")
    ALERT = os.path.join(IMM, "警戒账.jsonl")
    FED = os.path.join(TEN, "联邦账.jsonl")
    try:
        ev = [{"key": f"ZD0{i}|who", "v": "过", "layer": "rel", "why": ""} for i in range(5)]
        head = {"node_id": "A" * 16, "rules": "v3", "watermark": 5}
        pack = {"header": head, "events": ev}
        r1 = guard(pack)
        r2 = guard(pack)
        r3 = guard(pack)
        print(f"诚实节点 A：首见 {r1} → 二次 {r2} → 三次 {r3}（期望 3,3,0）")
        print(f"  A 状态：{latest('A'*16)['state']}｜联邦账成熟事件：{len(jlines(FED))}（期望 5）")

        pack_b = {"header": dict(head, node_id="B" * 16), "events": ev}
        rb = guard(pack_b)
        print(f"冒名新节点 B 首见：{rb}（期望 3，事件隔离不进联邦账）")

        flip_ev = [dict(e, v="否" if e["v"] == "过" else "过") for e in ev]
        pack_mut = {"header": dict(head, node_id="A" * 16), "events": flip_ev}
        rm = guard(pack_mut)
        print(f"记忆节点 A 全翻：{rm}（期望 4，异己反应）")
        ok = (r1, r2, r3, rb, rm) == (3, 3, 0, 3, 4) and len(jlines(FED)) == 5
        print("自检：" + ("通过" if ok else "未通过"))
        return 0 if ok else 1
    finally:
        HOME, TEN, IMM, PROFILE, QUAR, ALERT, FED = old
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    pg = sub.add_parser("guard"); pg.add_argument("--bundle", required=True)
    sub.add_parser("selfcheck")
    a = ap.parse_args()
    return {"status": status, "guard": lambda: guard_cmd(a),
            "selfcheck": selfcheck}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
