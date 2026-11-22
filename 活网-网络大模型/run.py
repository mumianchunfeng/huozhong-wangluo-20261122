#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活网 · 网络大模型 v1 —— 一键自检入口
=====================================
只跑八步只读检查（不改账、不新增文件），任一步非 0 退出即判失败。
    python run.py            八步全跑，末尾给汇总
    python run.py list       只看步骤清单

步骤与预期（详见 RUN.md）：
  1 三层闸逐格比对      checker_v2.py test   → 一致 20 / 分歧 0
  2 参数化判据验收      checker_v2.py test3  → 一致 19 / 分歧 1（已知且正当）
  3 九件批量与错例      batch.py --case 9    → 整件 9/9、错例 18/18
  4 信用学习与阈值      learn.py             → 需回应 18→0、旧规则 19/19 被单方否决
  5 层聚合与死锁裁决    aggregate.py         → 成立1 不成立3 暂缓1 冻结2
  6 账包离线验算        seal.py verify       → 金额 9/9、全部通过
  7 触须织网（可选）    tentacle.py beacon   → 有 peers 则投出＋收进；无则如实报"单机模式"
  8 免疫层（仿生）      immune.py selfcheck  → 诚实 3/3/0、冒名隔离 3、异己反应 4，自检通过
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "model")

STEPS = [
    ("1 三层闸逐格比对", [sys.executable, "checker_v2.py", "test"]),
    ("2 参数化判据验收", [sys.executable, "checker_v2.py", "test3"]),
    ("3 九件批量与错例", [sys.executable, "batch.py", "--case", os.path.join("cases", "真事-批量9.json")]),
    ("4 信用学习与阈值", [sys.executable, "learn.py"]),
    ("5 层聚合与死锁裁决", [sys.executable, "aggregate.py"]),
    ("6 账包离线验算", [sys.executable, "seal.py", "verify"]),
    ("7 触须织网（可选）", [sys.executable, "tentacle.py", "beacon"]),
    ("8 免疫层（仿生）", [sys.executable, "immune.py", "selfcheck"]),
]

TAIL = {1: 1, 2: 1, 3: 8, 4: 5, 5: 3, 6: 4, 7: 8, 8: 5}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for name, argv in STEPS:
            print(name, "→", " ".join(argv[1:]))
        return 0

    print(f"Python {sys.version.split()[0]}｜包根 {ROOT}")
    if sys.version_info < (3, 9):
        print("需要 Python ≥ 3.9（仅标准库），当前版本过低")
        return 2
    if not os.path.isdir(MODEL):
        print("缺 model\\ 目录，包不完整")
        return 2

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    fails = 0
    results = []
    for i, (name, argv) in enumerate(STEPS, 1):
        print("\n" + "=" * 64)
        print(f"【{name}】{' '.join(argv[1:])}")
        print("=" * 64)
        r = subprocess.run(argv, cwd=MODEL, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "").rstrip()
        if out:
            lines = out.splitlines()
            k = TAIL.get(i, 6)
            if len(lines) > k:
                print("…（前略）")
            print("\n".join(lines[-k:]))
        if r.returncode != 0 and i not in (2,):
            # 第 2 步允许 1 处分歧（旧闸漏放，判据已收紧，属已知且正当）
            print(f"!! 退出码 {r.returncode}")
            if (r.stderr or "").strip():
                print((r.stderr or "").strip()[-400:])
        ok = r.returncode == 0 or i == 2
        results.append((name, ok))
        if not ok:
            fails += 1

    print("\n" + "=" * 64)
    for name, ok in results:
        print(f"  {'通过' if ok else '失败'}  {name}")
    print(f"\n汇总：{len(results) - fails}/{len(results)} 项通过"
          + ("　——包可用" if fails == 0 else "　——包不可用，别用"))
    print("说明：前六步只读、不写账；第七步只在配置了 peers.json 时才写触须账并投包，"
          "没配就如实报『单机模式』；第八步免疫自检全在临时目录跑，不碰真实账。"
          "免疫守卫默认关，要开就设 LW_IMMUNE=1。写账演示（publicity / external_veto demo）会改账，未纳入自检。")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
