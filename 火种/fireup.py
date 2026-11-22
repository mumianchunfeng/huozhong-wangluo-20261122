#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段一 · 点火校验器（Fireup Gate）
=================================
唯一入口。任何大模型、调度逻辑、记忆台账，都不得先于本脚本通过而加载。

职责（四道闸门，顺序固定）：
   闸1  LOADER SELF-CHECK  —— 校验器本体未被改动（比对创世锚登记的自身指纹）
   闸2  ANCHOR CHAIN       —— 锚链完整：prev_root 首尾相接、每版摘要自洽
   闸3  CHARTER MATCH      —— 当前规约文件与本链尾（当前有效锚）逐字节一致
   闸4  放行 / 拒绝         —— 通过则打印“点火放行”，否则给出明确拒绝原因与退出码

设计红线：
   * 只依赖 Python 标准库，不引入任何大模型或网络调用；
   * 本文件一旦被改动，闸1 必然失败——因为它的哈希已固化在创世锚里；
   * 本脚本不提供任何“跳过校验”的参数，防止运维便利性反噬。

用法：
   python3 fireup.py init     # 仅首次：生成创世锚与锚链首行
   python3 fireup.py check    # 每次点火：四道闸门全跑
   python3 fireup.py show     # 只读：打印当前有效锚摘要
"""
import argparse
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ANCHOR_DIR = os.path.join(BASE, "anchor")
GENESIS_PATH = os.path.join(ANCHOR_DIR, "genesis.json")
CHAIN_PATH = os.path.join(ANCHOR_DIR, "anchor_chain.jsonl")
REKEY_LOG_PATH = os.path.join(ANCHOR_DIR, "rekey_log.jsonl")
CHARTER_REL = os.path.join("convention", "本源规约.md")

EXIT_OK = 0          # 放行
EXIT_STALE = 1       # 规约内容与当前有效锚不一致（被改动/未登记的版本）
EXIT_CHAIN = 2       # 锚链损坏（断链、被删行、摘要自相矛盾）
EXIT_LOADER = 3      # 校验器本体被改动
EXIT_ANCHOR = 4      # 创世锚 / 锚链文件缺失或不可读
EXIT_EMPTY = 5       # 规约文件缺失
EXIT_GENE = 6        # 基因锁缺失 / 被弱化（宗旨在，则拒点火）

GUARDED_LOADER = ["fireup.py", "amend.py"]   # 需登记指纹的本层代码


# ---------------------------------------------------------------- 摘要原语
def digest_bytes(raw: bytes) -> dict:
    return {
        "sha3_256": hashlib.sha3_256(raw).hexdigest(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "lines": raw.count(b"\n"),          # 口径：换行符计数，等同 wc -l
    }


def digest_file(path: str) -> dict:
    with open(path, "rb") as f:
        return digest_bytes(f.read())


def digest_text(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 基因锁
# 三款必须逐字存在于规约中；删一个字、改一个标点，都算被弱化。
GENE_PREFIXES = ["6. 不可转让", "7. 不可被代表", "8. 不可改根", "9. 不可信任缔造者"]


def line_sha3(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


def extract_gene(charter_path: str):
    """按款首标记取整行，逐字哈希。返回 (clauses, 错误)。"""
    if not os.path.exists(charter_path):
        return None, "规约文件缺失"
    lines = open(charter_path, encoding="utf-8").read().splitlines()
    out = []
    for i, pf in enumerate(GENE_PREFIXES, 1):
        hit = [l for l in lines if l.startswith(pf)]
        if not hit:
            return None, f"基因锁 G{i}「{pf}」缺失"
        if len(hit) > 1:
            return None, f"基因锁 G{i}「{pf}」重复出现 {len(hit)} 次"
        out.append({"id": f"G{i}", "prefix": pf, "sha3_256": line_sha3(hit[0])})
    return out, None


def gate_rekey_log(genesis):
    """闸1.5 重登记留声：改自己可以，抹掉痕迹不行。
    若创世锚已登记留声基线，则追加日志条数必须等于「重登记历史条数 − 基线」。
    日志被删、被截断、未写入，均判为失败。
    """
    hist = genesis.get("loader_history") or []
    base = genesis.get("rekey_log_baseline")
    if base is None:
        return True, ["· 尚未启用重登记留声（首次 rekey 时建立基线；此前历史不追溯）"]
    n = 0
    if os.path.exists(REKEY_LOG_PATH):
        with open(REKEY_LOG_PATH, encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
    want = len(hist) - int(base)
    if want < 0:
        return False, [f"✗ 重登记历史少于基线（{len(hist)} < {base}），创世锚被回滚"]
    if n == want:
        return True, [f"✓ 重登记留声 {n} 条，与创世锚所载一致"]
    return False, [f"✗ 重登记留声 {n} 条，应为 {want} 条（记录被删、被截断或未写入）"]


def gate_gene_lock(genesis, charter_path):
    """登记过基因锁之后，缺一即拒。未登记（早期版本）则跳过。"""
    reg = (genesis.get("gene_lock") or {}).get("clauses")
    cur, err = extract_gene(charter_path)
    if not reg:
        # 允许“规约里本来就没有基因锁”的早期状态；
        # 但若规约已含三款而登记为空，只可能是有人把登记清掉了 → 必须拒。
        if err is None and cur:
            return False, ["✗ 规约含基因锁三款，但创世锚登记为空（登记被清空），拒绝点火"]
        return True, ["· 未登记基因锁（早期版本状态，本闸跳过）"]
    if err:
        return False, [f"✗ {err}"]
    ok, detail = True, []
    for r in reg:
        c = [x for x in cur if x["id"] == r["id"]]
        if not c:
            ok = False
            detail.append(f"✗ {r['id']}「{r['prefix']}」已不存在")
            continue
        if c[0]["sha3_256"] != r["sha3_256"]:
            ok = False
            detail.append(f"✗ {r['id']}「{r['prefix']}」被改动（逐字哈希不符）")
        else:
            detail.append(f"✓ {r['id']}「{r['prefix']}」逐字一致")
    return ok, detail


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 锚链读写
def read_chain(path=CHAIN_PATH):
    """返回 (链行列表, 错误信息)。任何结构缺陷都视为损坏，不做“容错修复”。"""
    if not os.path.exists(path):
        return None, "锚链文件不存在"
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                return None, f"锚链第 {i} 行无法解析：{e}"
    if not rows:
        return None, "锚链为空"
    return rows, None


def verify_chain(rows) -> list:
    """校验链完整性，返回问题清单（空清单=通过）。"""
    problems = []
    for idx, row in enumerate(rows):
        n = row.get("version")
        # 自洽：root 必须与同一行登记的文件摘要相同
        if row.get("root_sha3") != row.get("file_sha3"):
            problems.append(f"v{n} 行内 root_sha3 与 file_sha3 不一致（摘要自相矛盾）")
        for key in ("version", "root_sha3", "file_sha3", "cache_sha256", "bytes", "lines", "at"):
            if key not in row:
                problems.append(f"v{n} 缺失字段 {key}")
        # 首行必须是创世链
        if idx == 0:
            if row.get("prev_root") is not None:
                problems.append(f"v{n} 首行 prev_root 应为 null，实际 {row.get('prev_root')!r}")
            if row.get("version") != "v1":
                problems.append(f"首行版本应为 v1，实际 {row.get('version')!r}")
        else:
            if row.get("prev_root") != rows[idx - 1].get("root_sha3"):
                problems.append(f"v{n} 的 prev_root 与上一版 root 断开（断链或被插队）")
            if not str(row.get("version", "")).startswith("v") or int(str(row["version"])[1:]) != int(str(rows[idx - 1]["version"])[1:]) + 1:
                problems.append(f"v{n} 版本号未连续递增")
    return problems


def tail_anchor(rows) -> dict:
    return rows[-1]


# ---------------------------------------------------------------- 闸1
def gate_loader(genesis) -> tuple:
    """校验器自身指纹比对。返回 (ok, 明细列表)。"""
    detail = []
    ok = True
    registered = genesis.get("loader", {})
    for name in GUARDED_LOADER:
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            detail.append(f"✗ {name} 缺失")
            ok = False
            continue
        if name not in registered:
            detail.append(f"· {name} 未登记（未纳入自校验范围）")
            continue
        actual = digest_file(path)
        expect = registered[name]["sha3_256"]
        if actual["sha3_256"] == expect:
            detail.append(f"✓ {name} 指纹一致 {expect[:16]}…")
        else:
            detail.append(f"✗ {name} 指纹不一致  期望 {expect[:16]}…  实际 {actual['sha3_256'][:16]}…")
            ok = False
    return ok, detail


# ---------------------------------------------------------------- check
def cmd_check(as_json=False) -> int:
    out = {"gates": [], "verdict": None, "exit": None}

    # 闸1 依赖创世锚，先读锚
    if not os.path.exists(GENESIS_PATH):
        return _fail(EXIT_ANCHOR, "创世锚 anchor/genesis.json 缺失，拒绝点火", out, as_json)
    with open(GENESIS_PATH, "r", encoding="utf-8") as f:
        genesis = json.load(f)

    ok1, detail1 = gate_loader(genesis)
    out["gates"].append({"gate": "1 LOADER SELF-CHECK", "ok": ok1, "detail": detail1})
    if not ok1:
        return _fail(EXIT_LOADER, "校验器本体被改动，拒绝点火（闸1）", out, as_json)

    # 闸1.5 重登记留声
    ok15, d15 = gate_rekey_log(genesis)
    out["gates"].append({"gate": "1.5 REKEY LOG", "ok": ok15, "detail": d15})
    if not ok15:
        return _fail(EXIT_LOADER, "重登记痕迹不全，拒绝点火（闸1.5）", out, as_json)

    # 闸2 锚链
    rows, err = read_chain()
    if err:
        out["gates"].append({"gate": "2 ANCHOR CHAIN", "ok": False, "detail": [f"✗ {err}"]})
        return _fail(EXIT_ANCHOR, f"锚链不可用：{err}，拒绝点火（闸2）", out, as_json)
    problems = verify_chain(rows)
    out["gates"].append({"gate": "2 ANCHOR CHAIN", "ok": not problems,
                         "detail": [f"✓ 共 {len(rows)} 版锚，链完整"] if not problems else [f"✗ {p}" for p in problems]})
    if problems:
        return _fail(EXIT_CHAIN, f"锚链损坏（{len(problems)} 处缺陷），拒绝点火（闸2）", out, as_json)

    # 闸3 规约与链尾一致
    charter = os.path.join(BASE, CHARTER_REL)
    if not os.path.exists(charter):
        return _fail(EXIT_EMPTY, "规约文件缺失，拒绝点火（闸3）", out, as_json)
    cur = digest_file(charter)
    tail = tail_anchor(rows)
    same = (cur["sha3_256"] == tail["file_sha3"]
            and cur["sha256"] == tail["cache_sha256"]
            and cur["bytes"] == tail["bytes"]
            and cur["lines"] == tail["lines"])
    d3 = [f"当前有效锚：{tail['version']}  root {tail['root_sha3'][:16]}…",
          f"文件摘要：{cur['sha3_256'][:16]}… / {cur['bytes']} 字节 / {cur['lines']} 行",
          "✓ 与当前有效锚逐字节一致" if same else "✗ 与当前有效锚不一致"]
    out["gates"].append({"gate": "3 CHARTER MATCH", "ok": same, "detail": d3})
    if not same:
        return _fail(EXIT_STALE, f"规约内容偏离已登记版本（链尾 {tail['version']}），拒绝点火（闸3）", out, as_json)

    # 闸3.5 基因锁
    okg, dg = gate_gene_lock(genesis, charter)
    out["gates"].append({"gate": "3.5 GENE LOCK", "ok": okg, "detail": dg})
    if not okg:
        return _fail(EXIT_GENE, "基因锁被删除或改动，拒绝点火（闸3.5）", out, as_json)

    # 闸4 放行
    out["verdict"] = f"点火放行 · 规约 {tail['version']} · root {tail['root_sha3']}"
    out["exit"] = EXIT_OK
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 68)
        print("点火校验 · 四道闸门")
        print("=" * 68)
        for g in out["gates"]:
            print(f"\n[闸] {g['gate']}")
            for line in g["detail"]:
                print("     " + line)
        print("\n" + "-" * 68)
        print("结果：★ " + out["verdict"])
        print("=" * 68)
        print("→ 允许加载：勘比闭环 / 关系引擎 / 记忆台账 / 推理模型")
    return EXIT_OK


def _fail(code, msg, out, as_json):
    out["verdict"] = "拒绝点火：" + msg
    out["exit"] = code
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 68)
        for g in out["gates"]:
            print(f"[闸] {g['gate']}")
            for line in g["detail"]:
                print("     " + line)
            print()
        print("-" * 68)
        print("结果：✗ " + msg)
        print(f"退出码：{code}")
        print("=" * 68)
        print("→ 禁止加载：任何模型、调度、记忆逻辑一律不启动")
    return code


# ---------------------------------------------------------------- init
def cmd_rekey(reason="") -> int:
    """运维级操作：重登记校验器指纹与基因锁，不动规约、不动锚链历史。

    不是后门，是有门的门（规约 5.2）：
      原因必填；且必须向 anchor/rekey_log.jsonl 追加一条不可删记录。
    """
    reason = (reason or "").strip()
    if not reason:
        print("拒绝 rekey：原因必填（--reason）。")
        print("改自己可以，不留声不行——见规约 5.2。")
        return EXIT_LOADER
    if not os.path.exists(GENESIS_PATH):
        print("创世锚不存在，无法 rekey")
        return EXIT_ANCHOR
    with open(GENESIS_PATH, encoding="utf-8") as f:
        genesis = json.load(f)
    old_loader = dict(genesis.get("loader") or {})
    old_gene = (genesis.get("gene_lock") or {}).get("clauses")
    charter = os.path.join(BASE, CHARTER_REL)
    cur, err = extract_gene(charter)
    loader = {}
    for name in GUARDED_LOADER:
        p = os.path.join(BASE, name)
        if os.path.exists(p):
            loader[name] = digest_file(p)
    hist = genesis.get("loader_history", [])
    if genesis.get("rekey_log_baseline") is None:
        # 首次启用留声：把此前的历史作为基线，不追溯
        genesis["rekey_log_baseline"] = len(hist)
    hist.append({"at": now(), "reason": reason, "loader": old_loader})
    genesis["loader"] = loader
    genesis["gene_lock"] = {"policy": "四款须逐字存在，缺一即拒绝点火", "clauses": cur or []}
    genesis["loader_history"] = hist
    genesis["rekey_at"] = now()
    os.chmod(GENESIS_PATH, 0o644)
    with open(GENESIS_PATH, "w", encoding="utf-8") as f:
        json.dump(genesis, f, ensure_ascii=False, indent=2)
    os.chmod(GENESIS_PATH, 0o444)

    # —— 留声：追加一条不可删记录（只读靠 chmod，不改性靠外部副本比对）
    rec = {
        "at": now(),
        "reason": reason,
        "old_loader": old_loader,
        "new_loader": loader,
        "old_gene_lock": old_gene,
        "new_gene_lock": cur or [],
    }
    os.makedirs(ANCHOR_DIR, exist_ok=True)
    if os.path.exists(REKEY_LOG_PATH):
        os.chmod(REKEY_LOG_PATH, 0o644)
    with open(REKEY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.chmod(REKEY_LOG_PATH, 0o444)

    print("rekey 完成（锚链历史未动）")
    print(f"  留声：anchor/rekey_log.jsonl 已追加 1 条（原因「{reason}」、旧指纹、新指纹）")
    for n, v in loader.items():
        print(f"  {n} 新指纹 {v['sha3_256'][:16]}…")
    if err:
        print(f"  ⚠ 基因锁提取失败：{err}（本轮基因锁闸将跳过）")
    else:
        print(f"  基因锁已登记 {len(cur)} 款：{', '.join(c['id'] + ' ' + c['prefix'] for c in cur)}")
    return EXIT_OK


def cmd_init(force=False, rekey=False, reason="") -> int:
    if rekey:
        return cmd_rekey(reason)
    if os.path.exists(GENESIS_PATH) and not force:
        print("创世锚已存在，拒绝重复初始化（如确需重建，用 --force，并明白这会丢弃锚链历史）")
        return EXIT_ANCHOR
    charter = os.path.join(BASE, CHARTER_REL)
    if not os.path.exists(charter):
        print("规约文件不存在，无法生成锚")
        return EXIT_EMPTY
    if os.path.exists(CHAIN_PATH) and not force:
        print("锚链已存在，拒绝覆盖")
        return EXIT_CHAIN

    cur = digest_file(charter)
    loader = {}
    for name in GUARDED_LOADER:
        p = os.path.join(BASE, name)
        if os.path.exists(p):
            loader[name] = digest_file(p)

    genesis = {
        "convention_id": "PU-Swarm-Charter",
        "title": "《分布式普惠算力协同智能体 · 本源规约》（增补修订版）",
        "created_at": now(),
        "rules": {
            "convention_path": "convention/本源规约.md",
            "encoding": "utf-8",
            "newline": "preserve",
            "hash_primary": "sha3_256",
            "hash_secondary": "sha256",
            "lines_metric": "count of LF bytes (equals wc -l)",
        },
        "amend_threshold": 2,          # 阶段一：2 份独立审签；阶段三接入分布式节点后按节点规模提升
        "loader": loader,
        "note": "本文件不可变。任何一次规约变更只在 anchor_chain.jsonl 追加新行，本文件永不重写。",
    }
    os.makedirs(ANCHOR_DIR, exist_ok=True)
    with open(GENESIS_PATH, "w", encoding="utf-8") as f:
        json.dump(genesis, f, ensure_ascii=False, indent=2)

    row = {
        "version": "v1",
        "prev_root": None,
        "root_sha3": cur["sha3_256"],
        "file_sha3": cur["sha3_256"],
        "cache_sha256": cur["sha256"],
        "bytes": cur["bytes"],
        "lines": cur["lines"],
        "at": now(),
        "basis": {"type": "genesis", "proposal_sha3": None, "attestations": 0},
    }
    with open(CHAIN_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    os.chmod(GENESIS_PATH, 0o444)
    ctx = digest_text(json.dumps(genesis["loader"], ensure_ascii=False, sort_keys=True))
    print("创世锚已生成")
    print(f"  规约文件：{CHARTER_REL}")
    print(f"  版本：v1   根哈希 SHA3-256：{cur['sha3_256']}")
    print(f"  字节/行：{cur['bytes']} / {cur['lines']}")
    print(f"  校验器清单哈希：{ctx[:32]}…")
    print(f"  变更阈值：{genesis['amend_threshold']} 份独立审签")
    return EXIT_OK


def cmd_show(as_json=False) -> int:
    rows, err = read_chain()
    if err:
        print(f"锚链不可用：{err}")
        return EXIT_ANCHOR
    tail = tail_anchor(rows)
    if as_json:
        print(json.dumps({"tail": tail, "history_len": len(rows)}, ensure_ascii=False, indent=2))
    else:
        print(f"锚链共 {len(rows)} 版，当前有效锚：")
        print(json.dumps(tail, ensure_ascii=False, indent=2))
    return EXIT_OK


def main():
    ap = argparse.ArgumentParser(description="阶段一 · 点火校验器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="生成创世锚（仅首次）")
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument("--rekey", action="store_true", help="仅重登记校验器指纹与基因锁")
    p_init.add_argument("--reason", default="")
    p_check = sub.add_parser("check", help="执行点火校验（四道闸门）")
    p_check.add_argument("--json", action="store_true")
    p_show = sub.add_parser("show", help="打印当前有效锚")
    p_show.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.cmd == "init":
        sys.exit(cmd_init(a.force, a.rekey, a.reason))
    if a.cmd == "check":
        sys.exit(cmd_check(a.json))
    if a.cmd == "show":
        sys.exit(cmd_show(a.json))


if __name__ == "__main__":
    main()
