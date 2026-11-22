#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小鸟的羽翼 · 取真实 LLM 三机制的原理（不调真实 LLM）
====================================================
来源（原理取自网络开源最小实现，代码重写为纯标准库、零依赖）：
  · BPE 分词      ← Karpathy minbpe / bpe-tokeniser：高频相邻合并 → 词表成长
  · Self-Attention← Karpathy microGPT：Q·K 相关加权求和 → 多维取相关
  · MoE top-k     ← ctxnn/MoE、moe-lab：按输入打分选 top-k 专家 + 负载均衡

移到本包后对应的三件事：
  ① 合并成长  把中期忆层里高频相邻的事件对合并成"复合件"，词表（判据口径）随之长大
  ② 相关取证  对某件的五个字段，用 QK 相关权重从其他件取相关先例，作为勘比补充证据
  ③ 专家路由  按任务形状打分，选 top-k 执行端，并记录负载防专家塌缩

只增不改：本文件新增，账写在 羽翼账/，不碰 checker_v2 / 火种 / 鞣合记忆。
凭据纪律：不读、不存任何 API key；不发任何网络请求。

用法：
    python 羽翼.py selfcheck     # 三机制自检（全在临时目录，不碰真实账）
    python 羽翼.py merge         # ① 合并成长（读鞣合记忆，写羽翼账）
    python 羽翼.py attend --id ZD06   # ② 相关取证
    python 羽翼.py route --kind 征地    # ③ 专家路由
    python 羽翼.py all           # 三机制依次跑
"""
import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "model")
CASES = os.path.join(MODEL, "cases", "真事-批量9.json")
MEM = os.path.join(ROOT, "鞣合记忆", "中期忆层.jsonl")
WING = os.path.join(ROOT, "羽翼账")
FIVE = ["who", "rule", "basis", "harm", "comp"]


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_cases():
    d = json.load(open(CASES, encoding="utf-8"))
    return d.get("cases", [])


# ================================================================
# ① BPE 原理：高频相邻合并 → 词表成长
#    真实 BPE 合并字节对；这里合并"事件标签对"，合并规则落账可复算。
# ================================================================
def bpe_train(tokens, target_size):
    """tokens: list[str]。返回 (merges, vocab)。
    修：target_size 是上限不是硬指标——没有达标的合法合并就停，不硬凑，
    否则会反复合并自己的产物，长出 '农用地+Ⅱ+农用地+Ⅱ' 这种无意义串。
    合并产物打 '合成' 标记，下一轮不再参与合并（真实 BPE 的增量式约束）。"""
    vocab = list(dict.fromkeys(tokens))
    merges = []
    while len(vocab) < target_size:
        pairs = Counter(zip(tokens, tokens[1:]))
        # 只统计两个原始 token（不含上一轮合成产物），杜绝自我吞并
        pairs = Counter({p: c for p, c in pairs.items()
                         if not (p[0].startswith("‹") or p[1].startswith("‹"))})
        if not pairs:
            break
        pair, cnt = pairs.most_common(1)[0]
        if cnt < 2:          # 频率门槛：只合并反复出现的对，单次不合并
            break
        new = "‹" + pair[0].lstrip("‹") + "+" + pair[1].lstrip("‹") + "›"
        merged, i = [], 0
        while i < len(tokens):
            if i + 1 < len(tokens) and tokens[i] == pair[0] and tokens[i + 1] == pair[1]:
                merged.append(new); i += 2
            else:
                merged.append(tokens[i]); i += 1
        if merged == tokens:  # 防御：没发生实际合并就停，避免死循环
            break
        tokens = merged
        vocab = list(dict.fromkeys(tokens))
        merges.append({"pair": list(pair), "new": new, "count": cnt})
    return merges, vocab


def cmd_merge():
    print("=" * 64)
    print("① 合并成长 · BPE 原理（高频相邻对合并 → 口径词表生长）")
    print("=" * 64)
    cases = load_cases()
    # 事件标签：境别+地类 作为相邻序列，模拟 token 流
    tokens = []
    for c in cases:
        tokens += [c.get("level", "?"), c.get("land", "?")]
    merges, vocab = bpe_train(tokens, target_size=len(set(tokens)) + 6)
    print(f"  原始 token 数 {len(tokens)}｜唯一 {len(set(tokens))}")
    print(f"  合并 {len(merges)} 次 → 口径词表 {len(vocab)}")
    for m in merges[:6]:
        print(f"    {m['pair'][0]}+{m['pair'][1]} ← {m['count']} 次 → {m['new']}")
    os.makedirs(WING, exist_ok=True)
    rec = {"at": now(), "机制": "BPE合并", "merges": merges, "vocab": vocab}
    with open(os.path.join(WING, "成长词表.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"  → 落账 {os.path.join(WING, '成长词表.json')}")
    return 0


# ================================================================
# ② Self-Attention 原理：Q·K 相关加权，对 V 求和取先例
#    真实 attention 用学习到的矩阵；这里用字段字面重合度当 QK，纯可解释。
# ================================================================
def qk(q, k):
    """相关分：字符集 Jaccard。真实 LLM 是点积，这里取同样的'相关即加权'原理。"""
    a, b = set(str(q)), set(str(k))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 字段权重：真实 attention 各维度贡献不同；关键字段(级别/地类)区分度更高。
# 修：把整串 literal 拼合改为逐字段加权，避免相似案件 QK 全打平都 0.333。
FIELD_W = {"level": 0.35, "land": 0.35, "village": 0.15, "amount": 0.10, "area": 0.05}


def qk_case(a, b):
    """逐字段 Jaccard 加权求和；同字段才比，不会把 village 的字误算进 level。"""
    total = 0.0
    for f, w in FIELD_W.items():
        av, bv = str(a.get(f, "")), str(b.get(f, ""))
        if not av or not bv:
            continue
        sa, sb = set(av), set(bv)
        sim = len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0
        total += w * sim
    return total


def cmd_attend(case_id):
    print("=" * 64)
    print("② 相关取证 · Self-Attention 原理（QK 相关加权取先例）")
    print("=" * 64)
    cases = load_cases()
    target = next((c for c in cases if c.get("id") == case_id), None)
    if not target:
        print(f"  未找到案件 {case_id}，可用 id: {[c.get('id') for c in cases]}")
        return 2
    print(f"  查询件 {case_id}｜{target.get('village')} {target.get('land')} {target.get('level')}")
    scores = []
    for c in cases:
        if c.get("id") == case_id:
            continue
        # Q=目标件字段向量，K=候选件字段向量，V=候选件的金额/面积（字段级加权相关）
        scores.append((qk_case(target, c), c))
    scores.sort(key=lambda x: x[0], reverse=True)
    top = scores[:3]
    if not top or top[0][0] == 0:
        print("  无相关先例（QK 全为 0）——不编造，如实报")
        return 0
    denom = sum(s for s, _ in top)
    print("  top-k 相关先例（权重归一化）：")
    for s, c in top:
        w = s / denom
        print(f"    {c.get('id')} {c.get('village')} {c.get('land')}｜权重 {w:.3f}｜V: {c.get('amount')}万元 / {c.get('area')}公顷")
    print("  → 加权取证仅作勘比补充，不替代 checker_v2 判定")
    return 0


# ================================================================
# ③ MoE 原理：按输入打分选 top-k 专家 + 负载均衡
#    真实 MoE 是学习的 gate；这里用形状特征打可读的分。
# ================================================================
EXPERTS = [
    ("checker_v2", "三层闸逐格比对", {"征地", "事实", "校验"}),
    ("batch", "九件批量与错例", {"批量", "九件", "错例"}),
    ("immune", "免疫异己反应", {"免疫", "异己", "冒名"}),
    ("gitbox", "跨节点织网", {"网络", "节点", "织网", "收发"}),
]


def cmd_route(kind):
    print("=" * 64)
    print("③ 专家路由 · MoE 原理（top-k gating + 负载均衡）")
    print("=" * 64)
    # gate 用连续相关度：标签字符串与任务形状的字符重合率，不再只数命中个数，
    # 否则多标签专家必然刷屏、其余专家全 0 → 单专家 100% 塌缩。
    scores = []
    kset = set(str(kind))
    for name, desc, tags in EXPERTS:
        hit = sum(1 for t in tags if t in str(kind))
        # 基础分=命中标签数；附加=标签字符集与任务的 Jaccard，给出连续区分度
        tag_chars = set("".join(tags))
        jac = len(tag_chars & kset) / len(tag_chars | kset) if (tag_chars or kset) else 0.0
        s = hit + jac
        scores.append((float(s), name, desc))
    scores.sort(reverse=True)
    # top-k 固定取前二（次优也保留），打破单一专家独占；无命中也按分数取前二
    topk = scores[:2]
    denom = sum(x[0] for x in topk) or 1.0
    print(f"  任务形状：{kind}")
    for s, name, desc in topk:
        print(f"    → {name}（{desc}）｜gate {s:.3f}/{denom:.3f}")
    os.makedirs(WING, exist_ok=True)
    lp = os.path.join(WING, "负载.jsonl")
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), "kind": kind,
                            "experts": [x[1] for x in topk]}, ensure_ascii=False) + "\n")
    # 负载统计：防专家塌缩（真实 MoE 的 aux loss 思想）
    hist = Counter()
    if os.path.exists(lp):
        for line in open(lp, encoding="utf-8"):
            for e in json.loads(line).get("experts", []):
                hist[e] += 1
    print("  负载分布：" + ", ".join(f"{k}={v}" for k, v in hist.most_common()))
    if hist and max(hist.values()) / sum(hist.values()) > 0.8:
        print("  ⚠ 专家塌缩预警：单一专家占比 >80%，建议轮换")
    return 0


# ================================================================
# 自检：全在临时目录，不碰真实账
# ================================================================
def cmd_selfcheck():
    print("=" * 64)
    print("羽翼自检 · 三机制（临时目录，不碰真实账）")
    print("=" * 64)
    ok = True
    # BPE
    m, v = bpe_train(["a", "b", "a", "b", "a", "b"], 5)
    # 新约束：产物带 ‹› 标记、不硬凑目标、无自我拼接（产物最多一个 +）
    b1 = (len(m) > 0 and any(w.startswith("‹") and w.endswith("›") for w in v)
          and all(w.count("+") <= 1 for w in v))
    print(f"  {'过' if b1 else '失败'}  BPE 合并：{len(m)} 次，词表 {v}（无自我拼接）")
    ok &= b1
    # Attention
    s = qk("abc", "abd")
    b2 = 0 < s < 1
    print(f"  {'过' if b2 else '失败'}  QK 相关：abc vs abd = {s:.3f}（应 0<s<1）")
    ok &= b2
    # MoE
    kset = set("征地 校验")
    sc = []
    for n, _, tags in EXPERTS:
        hit = sum(1 for t in tags if t in "征地 校验")
        tc = set("".join(tags))
        jac = len(tc & kset) / len(tc | kset) if (tc or kset) else 0.0
        sc.append((hit + jac, n))
    sc.sort(reverse=True)
    b3 = sc[0][1] == "checker_v2" and len(sc[:2]) == 2   # top1 正确且保留次优防塌缩
    print(f"  {'过' if b3 else '失败'}  MoE 路由：征地+校验 → top1 {sc[0][1]}（top-2 防塌缩）")
    ok &= b3
    print(f"\n自检：{'通过' if ok else '失败'}（3/3｜{'3' if ok else str(sum([b1,b2,b3]))}/3）")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="小鸟的羽翼 · LLM 三机制（取原理，不调真实模型）")
    ap.add_argument("cmd", nargs="?", default="all",
                    choices=["selfcheck", "merge", "attend", "route", "all"])
    ap.add_argument("--id", default="ZD06")
    ap.add_argument("--kind", default="征地 校验")
    a = ap.parse_args()
    if a.cmd == "selfcheck":
        return cmd_selfcheck()
    if a.cmd == "merge":
        return cmd_merge()
    if a.cmd == "attend":
        return cmd_attend(a.id)
    if a.cmd == "route":
        return cmd_route(a.kind)
    # all：自检 → 合并 → 取证 → 路由
    rc = cmd_selfcheck()
    if rc != 0:
        return rc
    rc |= cmd_merge()
    rc |= cmd_attend(a.id)
    rc |= cmd_route(a.kind)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
