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
    """tokens: list[str]。返回 (merges, vocab)。合并最高频相邻对，直到达标。"""
    vocab = list(dict.fromkeys(tokens))
    merges = []
    while len(vocab) < target_size:
        pairs = Counter(zip(tokens, tokens[1:]))
        if not pairs:
            break
        pair, cnt = pairs.most_common(1)[0]
        if cnt < 2:
            break
        new = pair[0] + "+" + pair[1]
        merged, i = [], 0
        while i < len(tokens):
            if i + 1 < len(tokens) and tokens[i] == pair[0] and tokens[i + 1] == pair[1]:
                merged.append(new); i += 2
            else:
                merged.append(tokens[i]); i += 1
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
        # Q=目标件五字段串，K=候选件五字段串，V=候选件的金额/面积
        q = " ".join(str(target.get(f, "")) for f in FIVE)
        k = " ".join(str(c.get(f, "")) for f in FIVE)
        scores.append((qk(q, k), c))
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
    scores = []
    for name, desc, tags in EXPERTS:
        s = sum(1 for t in tags if t in kind)
        scores.append((float(s), name, desc))
    scores.sort(reverse=True)
    topk = [x for x in scores if x[0] > 0][:2]
    if not topk:
        topk = [(0.0, scores[0][1], scores[0][2])]   # 无命中也给出一个，不空转
    denom = sum(x[0] for x in topk) or 1.0
    print(f"  任务形状：{kind}")
    for s, name, desc in topk:
        print(f"    → {name}（{desc}）｜gate {s}/{denom}")
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
    b1 = len(m) > 0 and "a+b" in v
    print(f"  {'过' if b1 else '失败'}  BPE 合并：{len(m)} 次，词表 {v}")
    ok &= b1
    # Attention
    s = qk("abc", "abd")
    b2 = 0 < s < 1
    print(f"  {'过' if b2 else '失败'}  QK 相关：abc vs abd = {s:.3f}（应 0<s<1）")
    ok &= b2
    # MoE
    sc = sorted(((float(sum(1 for t in tags if t in "征地 校验")), n)
                 for n, _, tags in EXPERTS), reverse=True)
    b3 = sc[0][1] == "checker_v2"
    print(f"  {'过' if b3 else '失败'}  MoE 路由：征地+校验 → top1 {sc[0][1]}")
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
