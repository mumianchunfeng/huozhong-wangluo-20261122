#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S15 学习率与衰减：让票重"一次一次长"，并让阈值会动
==================================================
S19 暴露的问题：19 个议题里 18 个停在「需回应」，否决率反被稀释到 5.3%。
根因不是批评者不够，是三条写死的规则：
  · 信用一步顶格（命中率 100% 直接 ×1.5，C1 从 2 跳到 3）；
  · 阈值固定 3/2，批评者再多也不动；
  · 「需回应」没有期限，谁喊一句就能永久挂着。

本件换四条：
  R1 学习率：score ← score + α·(1-score)（命中）／score − α·score（失手），α=0.25。
     票重 = base × clamp(0.5+score, 0.5, 1.5)。一次命中只从 2.0 到 2.25，不再一步 3.0。
  R2 衰减：一轮不表态，score ← score − γ，γ=0.03；长期沉默者掉到下限 0.5×。
  R3 阈值会动：sustain = max(3, round(0.6·ΣW))，respond = max(2, round(0.4·ΣW))。
     ΣW 涨，门槛跟着涨——两个主体喊话不再自动等于"需回应"。
  R4 逾期（TTL）：标「需回应」的议题最多挂 2 拍，第 3 拍仍无补证 →
     异议失效、事项转为「生效（逾期）」。理由与 v11 同源：外部没有杀死权，
     也不该有无限拖延权；真受损方须在期内补证，补证才转否决。
  R5 回避：提案人不得作为本议题批评者投票（净权重剔除，分母同步剔除）。
     这是「复核权不能留在提案人手里」在裁决层的可运行版。

复算： python learn.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

ALPHA, GAMMA = 0.25, 0.03
LO, HI = 0.5, 1.5          # 票重上下限（相对 base）
SUSTAIN_F, RESPOND_F = 0.6, 0.5
THRESH_FLOOR = (3, 2)      # sustain / respond 绝对下限
TTL = 2                    # 「需回应」可挂几拍，第 TTL+1 拍转生效


def load():
    b = json.load(open(os.path.join(BASE, "cases", "真事-批量9.json"), encoding="utf-8"))
    crit = json.load(open(os.path.join(BASE, "cases", "批评者.json"), encoding="utf-8"))
    base_w = {c["id"]: float(c["weight"]) for c in crit["critics"]}
    issues = []
    for c in b["cases"]:
        for t in b["templates"]:
            if t["id"] == "T2" and not c["perm_area"]:
                continue
            issues.append({"id": f"{c['id']}-{t['id']}", "tpl": t["id"],
                           "cell": t["cell"], "vetoed_by": list(t["vetoed_by"]),
                           "truth": "站得住"})
    return base_w, issues


def weight(base, score):
    return round(base * min(HI, max(LO, 0.5 + score)), 3)


def thresholds(weights):
    s = sum(weights.values())
    return (max(THRESH_FLOOR[0], round(SUSTAIN_F * s)),
            max(THRESH_FLOOR[1], round(RESPOND_F * s)))


def verdict(score_sum, thr):
    if score_sum >= thr[0]:
        return "否决"
    if score_sum >= thr[1]:
        return "需回应"
    if score_sum > 0:
        return "不受理"
    return "生效"


def old_weights(base_w, issues):
    """S19 的旧规则：命中率直接乘，一步顶格。"""
    out = {}
    for cid, w0 in base_w.items():
        mine = [i for i in issues if cid in i["vetoed_by"]]
        good = sum(1 for i in mine if i["truth"] == "站得住")
        rate = good / len(mine) if mine else 0
        out[cid] = round(min(w0 * HI, w0 * (0.5 + rate)), 3)
    return out


def ema_traj(base_w, issues, order=None):
    """按观测次序逐次学习，返回每人轨迹与终值。"""
    score = {cid: 0.5 for cid in base_w}
    hist = {cid: [] for cid in base_w}
    seq = list(issues) if order is None else list(order)
    for it in seq:
        for cid in base_w:
            if cid not in it["vetoed_by"]:
                score[cid] = max(0.0, score[cid] - GAMMA)          # R2 沉默衰减
            elif it["truth"] == "站得住":
                score[cid] = score[cid] + ALPHA * (1 - score[cid])  # R1 命中
            else:
                score[cid] = score[cid] - ALPHA * score[cid]        # R1 失手
            hist[cid].append(round(weight(base_w[cid], score[cid]), 3))
    return hist, {cid: weight(base_w[cid], v) for cid, v in score.items()}


def run(verbose=True):
    base_w, issues = load()

    # 二、信用轨迹：逐次观测，对照旧规则一步顶格
    hist, w_ema = ema_traj(base_w, issues)
    w_old = old_weights(base_w, issues)
    if verbose:
        print("一、口径：9 件 × 三模板（T2 只 1 件适用）＝ %d 个议题；"
              "批评者 3 主体，base 票重 %s" % (len(issues), base_w))
        print("\n二、信用轨迹（同一批命中，按观测次序逐次学）")
        for cid in base_w:
            first = hist[cid][0] if hist[cid] else None
            tail = hist[cid][-1] if hist[cid] else None
            drop = sum(1 for x in hist[cid] if x < base_w[cid])
            print(f"  {cid}  base {base_w[cid]}  首次 {first}  →  终值 {tail}"
                  f"  旧规则一步 {w_old[cid]}"
                  f"（低于 base 的观测 {drop} 次＝沉默衰减）")

    thr_old = (3, 2)
    thr_new = thresholds(w_ema)
    if verbose:
        print(f"\n三、阈值会动：ΣW 旧 {sum(w_old.values()):.2f} → 新 {sum(w_ema.values()):.2f}"
              f"｜门槛 旧 {thr_old} → 新 {thr_new}")

    # 四、19 议题：四种组合裁决
    def tally(weights, thr, ttl=False):
        d = {"否决": 0, "需回应": 0, "不受理": 0, "生效": 0, "生效（逾期）": 0}
        for it in issues:
            v = verdict(sum(weights[c] for c in it["vetoed_by"]), thr)
            if v == "需回应" and ttl:
                v = "生效（逾期）"   # 无人补证，挂满 TTL 拍
            d[v] += 1
        return d

    d_base = tally(base_w, thr_old)      # S19 现状：base 票重 + 固定阈值
    d_old = tally(w_old, thr_old)        # 旧信用规则回写后
    d_ema = tally(w_ema, thr_old)
    d_thr = tally(w_ema, thr_new)
    d_ttl = tally(w_ema, thr_new, ttl=True)
    if verbose:
        print("\n四、19 议题裁决（旧→新）")
        print("  %-34s%s" % ("基线：base 票重＋固定阈值(=S19 现状)", d_base))
        print("  %-34s%s" % ("旧信用：一步顶格回写后", d_old))
        print("  %-34s%s" % ("＋R1/R2 学习率与衰减", d_ema))
        print("  %-34s%s" % ("＋R3 阈值会动", d_thr))
        print("  %-34s%s" % ("＋R4 逾期转生效（兜底）", d_ttl))

    # 五、TTL 兜底演示：造一档票重恰好落在 [respond, sustain) 的议题
    #    C1+C3 在新权重下 = 2.887+0.5 = 3.387，若阈值 (3,4] 区间即落此档
    probe = sum(w_ema[c] for c in ("C1", "C3"))
    probe_v = verdict(probe, (4, 3))
    if verbose:
        print(f"\n五、TTL 兜底（票重恰落 [respond,sustain) 的一档）")
        print(f"  C1+C3 = {probe:.3f}，阈值取 (4,3) → 首拍 {probe_v}；"
              f"挂满 {TTL} 拍无补证 → 第 {TTL+1} 拍转「生效（逾期）」")

    # 六、回避：提案人不得投票
    recused = {"C1"}          # 假设 C1（院上村村委会）本件即提案人
    w_rec = {k: v for k, v in w_ema.items() if k not in recused}
    thr_rec = thresholds(w_rec)
    d_rec = {"否决": 0, "需回应": 0, "不受理": 0, "生效": 0}
    for it in issues:
        voters = [c for c in it["vetoed_by"] if c not in recused]
        d_rec[verdict(sum(w_rec[c] for c in voters), thr_rec)] += 1
    if verbose:
        print(f"\n六、回避（提案人 C1 退出本议题投票，分母同步剔除）")
        print(f"  阈值 {thr_new} → {thr_rec}；裁决分布 {d_rec}")
        print("  说明：原由 C1 单独主张的 T1（镇代管无依据），回避后票重为 0，直接失效——")
        print("  这正是「复核权不能留在提案人手里」在裁决层的样子。")

    return {"issues": len(issues), "base": d_base, "old": d_old, "ema": d_ema,
            "thr": d_thr, "ttl": d_ttl, "recuse": d_rec,
            "w_old": w_old, "w_new": w_ema, "thr_old": thr_old, "thr_new": thr_new}


def main():
    r = run(True)
    c1_first = 2 * min(1.5, 0.5 + 0.5 * 0.25)   # 一次命中的票重（base 2）
    print("\n结论：")
    print(f"  学习率：C1 一次命中只到 {c1_first:.2f}（旧规则一步 3.0）；"
          f"终值 {r['w_new']['C1']}／{r['w_new']['C2']}，顶格要用连续命中换。")
    print(f"  旧规则最危险的地方被实测出来了：一步顶格后 C1、C2 各自 3.0，"
          f"任何一个主体单独一票就能否决——{r['old'].get('否决')}/19 全被单方否决。")
    print(f"  阈值：{r['thr_old']} → {r['thr_new']}。"
          f"暂缓：{r['base'].get('需回应', 0)} → {r['thr'].get('需回应', 0)}"
          f"（不受理 {r['thr'].get('不受理', 0)}，否决 {r['thr'].get('否决', 0)}）。")
    print("  代价写清：阈值系数 0.6/0.5 是我设的，不是从数据学出来的（每格观测仍只有 9 条）；"
          "逾期转生效是 fail-open——沉默即放行，真受损方须在 2 拍内补证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
