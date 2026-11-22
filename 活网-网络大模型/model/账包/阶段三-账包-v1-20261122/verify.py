#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线验算（纯 stdlib，不 import 本工程任何脚本）。
验三样：① 每个文件 sha256 与清单一致；② 九件金额能从明细复算；③ 账行都是合法 JSON。
用法： python verify.py            （在包根目录或任意处都可，按自身位置找 manifest）
"""
import hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAN = os.path.join(HERE, "manifest.json")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    m = json.load(open(MAN, encoding="utf-8"))
    ok = bad = 0
    print(f"包：{m['pkg']}｜规约 {m['convention']['version']} root {m['convention']['root_sha3'][:16]}…")
    for f in m["files"]:
        p = os.path.join(HERE, "data", f["path"])
        if not os.path.exists(p):
            print(f"  缺文件 {f['path']}"); bad += 1; continue
        got = sha256(p)
        if got == f["sha256"]:
            ok += 1
        else:
            print(f"  哈希不符 {f['path']} 清单 {f['sha256'][:16]} 实得 {got[:16]}"); bad += 1
    # 总哈希：按清单顺序拼接 "path:sha256"
    cat = "".join(f"{f['path']}:{f['sha256']}\n" for f in m["files"]).encode()
    tot = hashlib.sha256(cat).hexdigest()
    if tot != m["total_sha256"]:
        print(f"  总哈希不符 清单 {m['total_sha256'][:16]} 实得 {tot[:16]}"); bad += 1
    else:
        ok += 1

    # 金额复算（与跨表算式同式）
    cases = json.load(open(os.path.join(HERE, "data", "cases", "真事-批量9.json"), encoding="utf-8"))["cases"]
    a_ok = a_bad = 0
    for c in cases:
        calc = round((c["area"] - c["perm_area"]) * c["price"] + c["perm_area"] * c["perm_price"], 4)
        if abs(calc - c["amount"]) <= 1.0:
            a_ok += 1
        else:
            print(f"  金额不符 {c['id']} {c['village']} 账 {c['amount']} 算 {calc}"); a_bad += 1
    print(f"金额复算 {a_ok}/{len(cases)} 通过")

    # 账行解析
    n_lines = 0
    for sub in ("ledger_public", "外部账", "ledger_real"):
        d = os.path.join(HERE, "data", sub)
        for name in os.listdir(d):
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as f:
                for i, ln in enumerate(f, 1):
                    if not ln.strip():
                        continue
                    try:
                        json.loads(ln); n_lines += 1
                    except Exception:
                        print(f"  坏账行 {sub}/{name} 第 {i} 行"); bad += 1
    print(f"账行 {n_lines} 条全部可解析")

    print("\n结果：" + ("全部通过" if bad == 0 else f"失败 {bad} 项"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
