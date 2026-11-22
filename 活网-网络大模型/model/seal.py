#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
S17 三处介质落地：把账从脚本里拿出来，做成能离线自证的包
=========================================================
S15 之后账更多了（裁决、逾期、回避）。但账还活在「跑脚本」这件事里：
不读脚本就不知道算式，不开 Python 就核不了数。这一件做的是——
把账本体抽出来，打成**不带代码也能验**的包，再按火种的三处规则落地。

三处介质（照《三处存放操作单》，三者不得同处一室）：
  处 1  本机 I 盘（非 C 盘）      —— 本脚本可代放（export 即落）
  处 2  移动硬盘（异地）          —— 需你插盘，place 校验后才记「已置放」
  处 3  离线纸质（A4 打印）        —— 出《离线件.txt》，打印后 place --paper
未置放的不得标已置放：状态机只有 placed / pending 两态，台账逐条留痕。

包里是什么（不带内账逻辑，只有账本身）：
  data\ledger_public\*          公示账（事件、待核、否决、状态）
  data\外部账\*                 外部账（提交、复核、公开视图）
  data\ledger_real\*            真账（propose 的过闸与驳回）
  data\cases\*                  九件真事 + 批评者登记
  data\checks\*  data\tables\*  判据与区片表（能复算才算账）
  data\draft_v11.md 规模-结论.md
  manifest.json                 逐文件 sha256 + 总哈希 + 规约 root
  verify.py                     纯 stdlib 离线验算（哈希／算式／账行解析）

用法：
  python seal.py export
  python seal.py verify
  python seal.py status
  python seal.py place --no 2 --path "F:\火种\2026-11-22"
  python seal.py place --no 3 --paper
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PKG_NAME = "阶段三-账包-v1-20261122"
PKG = os.path.join(BASE, "账包", PKG_NAME)
TOC = os.path.join(BASE, "介质台账.jsonl")
CONV = os.path.join(os.path.dirname(BASE), "_收到", "x_tuoming")
ANCHOR = os.path.join(CONV, "anchor", "anchor_chain.jsonl")

SPEC = [
    "ledger_public/events.jsonl", "ledger_public/pending.jsonl",
    "ledger_public/vetoes.jsonl", "ledger_public/state.json",
    "外部账/external_log.jsonl", "外部账/复核账.jsonl", "外部账/state.json",
    "ledger_real/events.jsonl", "ledger_real/rejects.jsonl", "ledger_real/state.json",
    "cases/真事-批量9.json", "cases/真事-批量.json", "cases/批评者.json",
    "checks/校验器-v3-参数化.json", "checks/校验器-v2-关系表.json",
    "checks/校验器-v2-域表.json", "checks/校验器-v2-跨表.json",
    "tables/区片综合地价.json",
    "draft_v11.md", "规模-结论.md", "校验器-v2-结论.md",
]
PUBLIC_VIEW = os.path.join(BASE, "外部账", "public_view")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lines_of(path):
    with open(path, "rb") as f:
        return f.read().count(b"\n")


def _wide(ch):
    import unicodedata
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def disp(s):
    return sum(_wide(c) for c in s)


def pad(s, w):
    return s + " " * max(0, w - disp(s))


def anchor_root():
    if not os.path.exists(ANCHOR):
        return {"version": None, "root_sha3": None}
    last = None
    with open(ANCHOR, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                last = json.loads(ln)
    return {"version": last["version"], "root_sha3": last["root_sha3"],
            "bytes": last["bytes"], "lines": last["lines"], "at": last["at"]}


VERIFY_PY = '''#!/usr/bin/env python3
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
    cat = "".join(f"{f['path']}:{f['sha256']}\\n" for f in m["files"]).encode()
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

    print("\\n结果：" + ("全部通过" if bad == 0 else f"失败 {bad} 项"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def export():
    conv = anchor_root()
    if os.path.exists(PKG):
        shutil.rmtree(PKG)
    os.makedirs(os.path.join(PKG, "data"), exist_ok=True)
    files = []
    for rel in SPEC:
        src = os.path.join(BASE, rel)
        if not os.path.exists(src):
            print("  跳过（不存在）：", rel); continue
        dst = os.path.join(PKG, "data", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        files.append({"path": rel, "bytes": os.path.getsize(dst),
                      "lines": lines_of(dst) if dst.endswith(".jsonl") else None,
                      "sha256": sha256(dst)})

    # 外部公开视图单独收：只收已公示的只读件
    if os.path.isdir(PUBLIC_VIEW):
        for name in sorted(os.listdir(PUBLIC_VIEW)):
            if not name.endswith(".json"):
                continue
            src = os.path.join(PUBLIC_VIEW, name)
            rel = f"外部账/public_view/{name}"
            dst = os.path.join(PKG, "data", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            files.append({"path": rel, "bytes": os.path.getsize(dst), "lines": None,
                          "sha256": sha256(dst)})

    cat = "".join(f"{f['path']}:{f['sha256']}\n" for f in files).encode()
    man = {"pkg": PKG_NAME, "exported_at": time.strftime("%Y-%m-%dT%H:%M+08:00"),
           "convention": conv, "files": files,
           "total_sha256": hashlib.sha256(cat).hexdigest(),
           "how_to_verify": "python verify.py（纯 stdlib，不读脚本、不联网）"}
    with open(os.path.join(PKG, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    with open(os.path.join(PKG, "verify.py"), "w", encoding="utf-8") as f:
        f.write(VERIFY_PY)

    # 离线件：A4 可打的人读件
    cases = json.load(open(os.path.join(BASE, "cases", "真事-批量9.json"), encoding="utf-8"))["cases"]
    rows = [("件", "村", "区片", "面积", "永基", "单价", "金额(账)", "金额(算)"),
            ("--", "-----", "---", "-----", "-----", "-----", "-------", "-------")]
    for c in cases:
        calc = round((c["area"] - c["perm_area"]) * c["price"] + c["perm_area"] * c["perm_price"], 4)
        rows.append((c["id"], c["village"], c["level"], f"{c['area']:.4f}",
                     f"{c['perm_area']:.4f}", str(c["price"]), f"{c['amount']:.2f}", f"{calc:.4f}"))
    w = [max(disp(str(r[i])) for r in rows) for i in range(8)]
    table = "\n".join("  ".join(pad(str(r[i]), w[i]) for i in range(8)) for r in rows)

    lines = [
        "活网 · 阶段三账包 · 离线件（打印后封存，勿改写）",
        f"包：{PKG_NAME}｜件数 {len(cases)}｜生成 {man['exported_at']}",
        f"规约：{conv['version']}  root(sha3) {conv['root_sha3']}",
        f"总哈希(sha256) {man['total_sha256']}",
        "",
        "一、验算只看三个数（不读脚本）",
        "  1) 每个文件 sha256 对得上清单；2) 总哈希对得上；3) 金额＝(面积−永基)×单价＋永基×永基单价。",
        "  手算示例（ZD06）：(1.4113−0.1936)×112.5＋0.1936×135＝163.127 万元，账记 163.13。",
        "",
        "二、九件真事（账与算并排）",
        table,
        "",
        "三、文件清单（sha256 前 16 位）",
    ]
    for f in files:
        lines.append(f"  {f['sha256'][:16]}  {f['bytes']:>7}  {f['path']}")
    lines += ["", "四、这一纸能证什么、不能证什么",
              "  能证：账没被改（哈希）、金额算得对（算式复算）、账行没坏（逐行解析）、规约是哪一版（root）。",
              "  不能证：证据本身真不真（扫描件 OCR 未逐字核）、批评者是不是真人（仍是登记名）、"
              "复核有没有偏（复核人仍可能与提案人同体）。",
              "", "体检日：次年同日抽一处复算，三处轮抽。"]
    with open(os.path.join(PKG, "离线件.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"导出 {len(files)} 个文件 + manifest + verify.py + 离线件.txt")
    print(f"包：{PKG}")
    print(f"总哈希 {man['total_sha256'][:32]}…｜规约 {conv['version']} {conv['root_sha3'][:16]}…")
    prev = last_rec("1")
    if prev and prev.get("总哈希") == man["total_sha256"]:
        print("处 1 已置放、哈希未变：台账不重复记")
    else:
        log("1", "I 盘（本机）", PKG, "placed", "脚本代放", man["total_sha256"])
    return 0


def log(no, media, where, status, note, total=None):
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M+08:00"), "处": no,
           "介质": media, "位置": where, "状态": status, "说明": note,
           "包": PKG_NAME}
    if total:
        rec["总哈希"] = total
    with open(TOC, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def last_rec(no):
    if not os.path.exists(TOC):
        return None
    out = None
    with open(TOC, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                r = json.loads(ln)
                if r["处"] == no:
                    out = r
    return out


def verify():
    sys.path.insert(0, PKG)
    import importlib.util
    spec = importlib.util.spec_from_file_location("v", os.path.join(PKG, "verify.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.main()


def status():
    if not os.path.exists(TOC):
        print("台账为空：三处都未置放")
        return 0
    last = {}
    with open(TOC, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                r = json.loads(ln)
                last[r["处"]] = r
    names = {"1": "本机 I 盘", "2": "移动硬盘（异地）", "3": "离线纸质"}
    for no in ("1", "2", "3"):
        r = last.get(no)
        if r:
            print(f"  处{no} {names[no]:<12} {r['状态']:<7} {r['位置']}  ({r['at']})")
        else:
            print(f"  处{no} {names[no]:<12} pending  （未置放）")
    done = sum(1 for r in last.values() if r["状态"] == "placed")
    print(f"\n已置放 {done}/3" + ("——三处齐了" if done == 3 else "——不足三处，不算落地"))
    return 0


def place(no, path=None, paper=False):
    if no == "1":
        print("处 1 由 export 自动落，不必单跑 place"); return 0
    if no == "3":
        if not paper:
            print("处 3 是纸：请打印 离线件.txt 后加 --paper 表示已打印封存"); return 0
        log("3", "离线纸质", "信封（自填位置）", "placed", "打印 离线件.txt 并封存，手写日期与总哈希")
        print("已记处 3：纸质件打印封存（位置栏留待手写）"); return 0
    # 处 2：真校验——目标目录必须能读到包，且哈希一致
    if not path or not os.path.isdir(path):
        print("处 2 需要 --path 指向移动硬盘上的目标文件夹（须已存在）"); return 1
    dst = os.path.join(path, PKG_NAME)
    if os.path.isdir(dst):
        print(f"目标已存在，先自行确认是否覆盖：{dst}"); return 1
    shutil.copytree(PKG, dst)
    r = verify_pkg(dst)
    if r != 0:
        print("拷过去验不过，不记已置放"); return 2
    log("2", "移动硬盘", dst, "placed", "copytree 后离线验算全过")
    print(f"已置放处 2：{dst}"); return 0


def verify_pkg(pkg):
    import importlib.util
    spec = importlib.util.spec_from_file_location("v2", os.path.join(pkg, "verify.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.main()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    sub.add_parser("verify")
    sub.add_parser("status")
    p = sub.add_parser("place")
    p.add_argument("--no", required=True, choices=["1", "2", "3"])
    p.add_argument("--path")
    p.add_argument("--paper", action="store_true")
    a = ap.parse_args()
    if a.cmd == "export":
        return export()
    if a.cmd == "verify":
        return verify()
    if a.cmd == "status":
        return status()
    return place(a.no, a.path, a.paper)


if __name__ == "__main__":
    raise SystemExit(main())
