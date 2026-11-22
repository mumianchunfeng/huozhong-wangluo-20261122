#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火种 × 网络大模型 · 鞣合层（tanhe.py）
=====================================
把火种的机制接进本包数据流，不是把两包摆在一起。
只增不改：本文件是新增层，原有 run.py / model/* / 火种/* 一个字节不动。

四段流程（对齐「火种与大模型鞣合数据流简图」）：
  ① 边界锁   读体内火种规约，锁定事实源/规则源/排除项/输出落点（只读）
  ② 分流     按任务形状选执行端：脚本(校验器) / 本地小模型 / 网络大模型集群
  ③ 勘比校验 执行端产出统一回传，由火种口径下的 checker_v2 逐格核；不合格打回
  ④ 分层归档 恒久层只读(火种锚) / 中期忆层(核验通过才沉淀) / 原材料层(留指针)

权限红线：
  · 模型无权写恒久层——本层只读火种锚链，不提供任何写入接口；
  · 勘比不合格一律不流出、不归档；
  · 经验回灌只进中期忆层，不动基准。

用法：
    python 鞣合.py                     # 全链路：闸门→边界→分流→勘比→归档
    python 鞣合.py --task simple       # 只跑脚本端（校验器），不调模型
    python 鞣合.py --task full         # 全部执行端（默认）
    python 鞣合.py --no-archive        # 只校验，不写中期忆层
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "model")
SEED = os.path.join(ROOT, "火种")
MEM = os.path.join(ROOT, "鞣合记忆")          # 新增：中期忆层，不碰任何原有账
MEM_LOG = os.path.join(MEM, "中期忆层.jsonl")

env = dict(os.environ, PYTHONIOENCODING="utf-8")


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run(argv, cwd):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def banner(t):
    print("\n" + "=" * 66)
    print(t)
    print("=" * 66)


# ---------- ① 边界锁 ----------
def boundary_lock():
    """只读火种规约与锚，锁定本次运行的边界；任何一个缺失即拒绝。"""
    banner("① 边界锁 · 锁定事实源/规则源/排除项/输出落点")
    charter = os.path.join(SEED, "convention", "本源规约.md")
    genesis = os.path.join(SEED, "anchor", "genesis.json")
    chain = os.path.join(SEED, "anchor", "anchor_chain.jsonl")
    for p in (charter, genesis, chain):
        if not os.path.isfile(p):
            print(f"✗ 缺 {p}，边界无法锁定")
            return None
    g = json.load(open(genesis, encoding="utf-8"))
    rows = [json.loads(x) for x in open(chain, encoding="utf-8") if x.strip()]
    tail = rows[-1]
    lock = {
        "事实源": "案件材料 / 法条库 / 用户指令（外部输入源，锁定）",
        "规则源": "火种本源规约 " + tail["version"] + " · root " + tail["root_sha3"][:16],
        "排除项": [c.get("prefix", "") for c in (g.get("gene_lock") or {}).get("clauses", []) if c.get("prefix")],
        "排除项依据": (g.get("gene_lock") or {}).get("policy", ""),
        "输出落点": os.path.join(MEM, "中期忆层.jsonl"),
        "规约sha256": sha_file(charter),
        "锚链版数": len(rows),
    }
    for k in ("事实源", "规则源", "排除项", "输出落点"):
        print(f"  {k}: {lock[k]}")
    print("  → 模型只读基准，无权改写恒久层")
    return lock


# ---------- ② 分流 ----------
def dispatch(task):
    """按活的形状分流：脚本端必跑（硬校验），模型端按任务开关。"""
    banner("② 任务分流 · 脚本 / 本地小模型 / 网络大模型集群")
    ends = [("脚本端 checker_v2", os.path.join(MODEL, "checker_v2.py"), ["test"])]
    if task == "full":
        ends += [("批量端 batch", os.path.join(MODEL, "batch.py"), ["--case", os.path.join("cases", "真事-批量9.json")]),
                 ("免疫端 immune", os.path.join(MODEL, "immune.py"), ["selfcheck"])]
    for name, path, argv in ends:
        print(f"  指派 → {name}｜{' '.join(argv)}")
    return ends


# ---------- ③ 勘比校验 ----------
def check_all(ends, lock):
    """所有执行端产出回到火种口径下核验；任一不合格即打回，不流出。"""
    banner("③ 勘比校验 · 唯一放行关口（不合格打回）")
    results = []
    for name, path, argv in ends:
        r = run([sys.executable, os.path.basename(path)] + argv, MODEL)
        tail = "\n".join((r.stdout or r.stderr).strip().splitlines()[-3:])
        ok = r.returncode == 0
        print(f"  {'过' if ok else '打回'}  {name}（退出 {r.returncode}）")
        for line in tail.splitlines():
            print("      " + line)
        results.append((name, ok, r.returncode))
    passed = all(x[1] for x in results)
    if not passed:
        bad = [x[0] for x in results if not x[1]]
        print(f"\n✗ 不合格：{', '.join(bad)} —— 打回重跑，本次不流出、不归档")
    else:
        print("\n✓ 勘比通过 —— 允许进入归档")
    return passed, results


# ---------- ④ 分层归档 ----------
def archive(lock, results, enabled):
    """只写中期忆层；恒久层（火种锚）只读，原材料只留指针。"""
    banner("④ 分层归档 · 恒久只读 / 中期核验沉淀 / 原材料留指针")
    print("  恒久层：火种锚链（只读，本层无写入接口）")
    print("  原材料层：外部输入源，只留指针，不入库")
    if not enabled:
        print("  中期忆层：--no-archive，本次不写")
        return
    os.makedirs(MEM, exist_ok=True)
    body = {
        "规则源": lock["规则源"],
        "规约sha256": lock["规约sha256"],
        "勘比": [{"端": n, "通过": ok, "退出码": c} for n, ok, c in results],
        "结论": "通过归档" if all(x[1] for x in results) else "不合格未归档",
    }
    # 幂等键：内容决定，不含时间戳。同一批事实重跑 → 同一键 → 不重复沉淀。
    keys = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    idem = hashlib.sha256(keys.encode("utf-8")).hexdigest()
    seen = set()
    if os.path.exists(MEM_LOG):
        for line in open(MEM_LOG, encoding="utf-8"):
            if line.strip():
                try:
                    seen.add(json.loads(line).get("幂等键", ""))
                except Exception:
                    pass
    if idem in seen:
        print(f"  中期忆层：幂等键 {idem[:12]} 已存在，跳过（不重复堆积）")
        return
    rec = {"幂等键": idem, "at": now(), **body}
    with open(MEM_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  中期忆层：已记 1 条（幂等键 {idem[:12]}）→ {MEM_LOG}")


def main():
    ap = argparse.ArgumentParser(description="火种 × 网络大模型 鞣合层")
    ap.add_argument("--task", choices=["simple", "full"], default="full")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()

    banner("火种 × 网络大模型 · 鞣合层")
    print(f"包根 {ROOT}\n体内火种 {SEED}")

    # 闸门：火种自检必须先过（复用点火.py 的闸门语义，直接调 fireup）
    fireup = os.path.join(SEED, "fireup.py")
    if not os.path.isfile(fireup):
        print("✗ 体内火种缺失，拒绝鞣合")
        return 10
    r0 = run([sys.executable, "fireup.py", "check"], SEED)
    print("\n".join((r0.stdout or r0.stderr).strip().splitlines()[-6:]))
    if r0.returncode != 0:
        print("✗ 火种闸门拒绝，任何模型逻辑不启动")
        return 11

    lock = boundary_lock()
    if not lock:
        return 12
    ends = dispatch(args.task)
    passed, results = check_all(ends, lock)
    if passed:
        archive(lock, results, not args.no_archive)
        print("\n★ 鞣合完成：火种放行 → 边界锁定 → 勘比通过 → 归档")
    else:
        print("\n✗ 鞣合中止：产出不合格，未流出")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
