#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段一 · 规约变更闸门（Amend Channel）
====================================
规约不许“直接改”。任何修改都要走这条路，四步缺一不可：

  1) propose  提案：声明变更理由 + 指定拟议的新文本，冻结（from_root / target 摘要）
  2) attest   审签：由独立节点各自给出 approve / reject，审签件绑定提案哈希
  3) commit   提交：审签达标才生成新锚，旧版归档，新文本落盘，锚链追加一行
  4) 若任何一环不达标 → 提案作废，规约保持原样（fail-closed，不 fail-open）

闸门判据（写死在代码里，不接受命令行参数绕过）：
   * approve 数 ≥ amend_threshold（由创世锚登记，阶段一=2）
   * 审签节点唯一（同一 node 多份只算一份，且重复即告警作废）
   * 不得存在任何 reject
   * 每一份审签绑定的 proposal_sha3 必须与当前提案一致（提案被改则旧审签全部失效）
   * 拟议新文本的实测摘要必须与提案登记的 target 摘要一致
   * 提案登记的 from_root 必须等于当前链尾 root（防止基于过期锚提案）

用法：
   python3 amend.py propose --by EXAMPLE-01 --reason "补入医疗链条款" --new-file ./draft.md
   python3 amend.py attest  --proposal proposals/P-xxx.json --node NODE-A --decision approve --note "已核对"
   python3 amend.py commit  --proposal proposals/P-xxx.json
   python3 amend.py history
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ANCHOR_DIR = os.path.join(BASE, "anchor")
GENESIS_PATH = os.path.join(ANCHOR_DIR, "genesis.json")
CHAIN_PATH = os.path.join(ANCHOR_DIR, "anchor_chain.jsonl")
CHARTER = os.path.join(BASE, "convention", "本源规约.md")
ARCHIVE = os.path.join(BASE, "convention", "archive")
PROPOSALS = os.path.join(BASE, "proposals")
ATTEST_DIR = os.path.join(PROPOSALS, "attestations")

E_OK, E_BAD = 0, 2


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest_bytes(raw: bytes) -> dict:
    return {"sha3_256": hashlib.sha3_256(raw).hexdigest(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "lines": raw.count(b"\n")}


def digest_file(p: str) -> dict:
    with open(p, "rb") as f:
        return digest_bytes(f.read())


def canonical_sha3(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "proposal_sha3"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha3_256(payload.encode("utf-8")).hexdigest()


def load_chain():
    rows = []
    with open(CHAIN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def genesis():
    with open(GENESIS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------- propose
def cmd_propose(a) -> int:
    chain = load_chain()
    tail = chain[-1]
    if not os.path.exists(a.new_file):
        print(f"拟议文本不存在：{a.new_file}")
        return E_BAD
    target = digest_file(a.new_file)
    if target["sha3_256"] == tail["file_sha3"]:
        print("拟议文本与现行版本完全一致，无需变更")
        return E_BAD

    body = {
        "type": "amend_proposal",
        "convention_id": "PU-Swarm-Charter",
        "base_version": tail["version"],
        "from_root": tail["root_sha3"],
        "proposed_by": a.by,
        "reason": a.reason,
        "at": now(),
        "target": {k: target[k] for k in ("sha3_256", "sha256", "bytes", "lines")},
        "target_text_sha3": target["sha3_256"],
    }
    pid = "P-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + a.by.replace("/", "_")
    body["proposal_id"] = pid
    body["proposal_sha3"] = canonical_sha3(body)

    os.makedirs(PROPOSALS, exist_ok=True)
    path = os.path.join(PROPOSALS, pid + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
    print("提案已生成（待审签，尚未生效）")
    print(f"  提案号：{pid}   基于：{tail['version']}")
    print(f"  提案哈希：{body['proposal_sha3']}")
    print(f"  拟议文本摘要：{target['sha3_256']}  {target['bytes']}字节/{target['lines']}行")
    print(f"  需要 approve ≥ {genesis()['amend_threshold']} 份独立审签")
    return E_OK


# ------------------------------------------------------------- attest
def cmd_attest(a) -> int:
    with open(a.proposal, "r", encoding="utf-8") as f:
        prop = json.load(f)
    if canonical_sha3(prop) != prop.get("proposal_sha3"):
        print("✗ 提案文件已被改动（proposal_sha3 对不上），拒绝受理审签")
        return E_BAD
    os.makedirs(ATTEST_DIR, exist_ok=True)
    att = {
        "type": "amend_attestation",
        "proposal_id": prop["proposal_id"],
        "proposal_sha3": prop["proposal_sha3"],
        "node": a.node,
        "decision": a.decision,
        "note": a.note or "",
        "at": now(),
    }
    att["attest_sha3"] = hashlib.sha3_256(
        json.dumps({k: v for k, v in att.items() if k != "attest_sha3"},
                   ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path = os.path.join(ATTEST_DIR, f"{prop['proposal_id']}-{a.node}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(att, f, ensure_ascii=False, indent=2)
    print(f"审签已写入：{os.path.relpath(path, BASE)}  [{a.node}] {a.decision}")
    return E_OK


# ------------------------------------------------------------- commit
def collect_attestations(pid: str, proposal_sha3: str):
    """返回 (有效审签列表, 问题清单)。"""
    approves, rejects, problems = [], [], []
    seen_nodes = {}
    if not os.path.isdir(ATTEST_DIR):
        return [], [], ["审签目录不存在"]
    for fn in sorted(os.listdir(ATTEST_DIR)):
        if not fn.endswith(".json") or not fn.startswith(pid):
            continue
        with open(os.path.join(ATTEST_DIR, fn), "r", encoding="utf-8") as f:
            at = json.load(f)
        if at.get("proposal_sha3") != proposal_sha3:
            problems.append(f"{fn} 绑定的提案哈希与当前提案不一致（提案被改过 → 旧审签失效）")
            continue
        body = {k: v for k, v in at.items() if k != "attest_sha3"}
        calc = hashlib.sha3_256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        if calc != at.get("attest_sha3"):
            problems.append(f"{fn} 审签件内容与自登记哈希不符（审签件被篡改）")
            continue
        node = at.get("node")
        if node in seen_nodes:
            problems.append(f"节点 {node} 重复审签（{seen_nodes[node]} 与 {fn}），重复不作数")
            continue
        seen_nodes[node] = fn
        if at.get("decision") == "approve":
            approves.append(at)
        elif at.get("decision") == "reject":
            rejects.append(at)
        else:
            problems.append(f"{fn} 审签结论非法：{at.get('decision')!r}")
    return approves, rejects, problems


def cmd_commit(a) -> int:
    with open(a.proposal, "r", encoding="utf-8") as f:
        prop = json.load(f)
    if canonical_sha3(prop) != prop.get("proposal_sha3"):
        print("✗ 提案文件已被改动，提交作废")
        return E_BAD

    g = genesis()
    chain = load_chain()
    tail = chain[-1]

    if prop["from_root"] != tail["root_sha3"]:
        print(f"✗ 提案基于 {prop['base_version']}（root {prop['from_root'][:16]}…），"
              f"但当前链尾已是 {tail['version']}（root {tail['root_sha3'][:16]}…）→ 请重新提案")
        return E_BAD

    approves, rejects, problems = collect_attestations(prop["proposal_id"], prop["proposal_sha3"])
    threshold = int(g["amend_threshold"])

    print("提交前核验：")
    print(f"  approve：{len(approves)}/{threshold}    reject：{len(rejects)}")
    for p in problems:
        print("  ✗ " + p)

    if rejects:
        print("✗ 存在 reject 审签 → 提案被否决，规约保持原样（不可强行提交）")
        return E_BAD
    if problems:
        print("✗ 审签材料存在缺陷 → 提案作废，规约保持原样")
        return E_BAD
    if len(approves) < threshold:
        print(f"✗ 审签不足（{len(approves)} < {threshold}）→ 提案未达门槛，规约保持原样")
        return E_BAD

    # 基因锁三款必须逐字存在（修订不得删改基因锁）
    GENE_PREFIXES = ["6. 不可转让", "7. 不可被代表", "8. 不可改根", "9. 不可信任缔造者"]
    newlines = open(a.new_file, encoding="utf-8").read().splitlines()
    for pf in GENE_PREFIXES:
        hit = [l for l in newlines if l.startswith(pf)]
        if len(hit) != 1:
            print(f"✗ 基因锁条款「{pf}」{'缺失' if not hit else '重复'} → 修订不得删改基因锁，提交作废")
            return E_BAD

    # 拟议文本实测摘要必须与提案登记一致
    if not os.path.exists(a.new_file):
        print(f"✗ 拟议文本不存在：{a.new_file}")
        return E_BAD
    actual = digest_file(a.new_file)
    if any(actual[k] != prop["target"][k] for k in ("sha3_256", "sha256", "bytes", "lines")):
        print("✗ 拟议文本与提案登记摘要不一致（提案后又被改动）→ 作废")
        return E_BAD

    # ---- 达标：归档旧版 → 落新文本 → 锚链追加
    os.makedirs(ARCHIVE, exist_ok=True)
    prev_ver = tail["version"]
    arch = os.path.join(ARCHIVE, f"{prev_ver}.md")
    if os.path.exists(arch):          # 上一次失败可能留下只读残留
        os.chmod(arch, 0o644)
        os.remove(arch)
    shutil.copy2(CHARTER, arch)
    os.chmod(arch, 0o444)
    os.chmod(CHARTER, 0o644)          # 规约常驻只读，落盘前临时解锁
    shutil.copy2(a.new_file, CHARTER)
    os.chmod(CHARTER, 0o444)

    new_ver = "v" + str(int(prev_ver[1:]) + 1)
    row = {
        "version": new_ver,
        "prev_root": tail["root_sha3"],
        "root_sha3": actual["sha3_256"],
        "file_sha3": actual["sha3_256"],
        "cache_sha256": actual["sha256"],
        "bytes": actual["bytes"],
        "lines": actual["lines"],
        "at": now(),
        "basis": {
            "type": "amend",
            "proposal_id": prop["proposal_id"],
            "proposal_sha3": prop["proposal_sha3"],
            "reason": prop["reason"],
            "proposed_by": prop["proposed_by"],
            "attestations": len(approves),
            "attested_nodes": sorted(ad["node"] for ad in approves),
        },
    }
    with open(CHAIN_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"✓ 变更生效：{prev_ver} → {new_ver}")
    print(f"  旧版已归档：convention/archive/{prev_ver}.md")
    print(f"  新根哈希：{actual['sha3_256']}")
    print(f"  审签节点：{row['basis']['attested_nodes']}")
    print("  提示：请重新跑 fireup.py check 确认新锚可点火")
    return E_OK


# ------------------------------------------------------------- history
def cmd_history() -> int:
    chain = load_chain()
    print(f"锚链 {len(chain)} 版：")
    for r in chain:
        b = r.get("basis", {})
        tag = b.get("type", "?")
        extra = f" ← {b.get('proposal_id')}" if tag == "amend" else ""
        print(f"  {r['version']:>4}  root {r['root_sha3'][:20]}…  {r['bytes']}字节/{r['lines']}行  [{tag}]{extra}  {r['at']}")
    return E_OK


def main():
    ap = argparse.ArgumentParser(description="阶段一 · 规约变更闸门")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose"); p.add_argument("--by", required=True)
    p.add_argument("--reason", required=True); p.add_argument("--new-file", required=True)

    p = sub.add_parser("attest"); p.add_argument("--proposal", required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--decision", required=True, choices=["approve", "reject"])
    p.add_argument("--note", default="")

    p = sub.add_parser("commit"); p.add_argument("--proposal", required=True)
    p.add_argument("--new-file", required=True)

    sub.add_parser("history")
    a = ap.parse_args()
    sys.exit({"propose": cmd_propose, "attest": cmd_attest,
              "commit": cmd_commit, "history": lambda _a: cmd_history()}[a.cmd](a))


if __name__ == "__main__":
    main()
