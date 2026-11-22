#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基因锁实测（闸3.5 + amend 提交前拦截）
=====================================
两个方向一起测，才算把锁钉住：

  A. 走正规流程删基因锁 → amend.py 在**提交前**就拒（不让它进锚）
  B. 绕过流程、改内容并伪造自洽锚链 → 闸1/2/3 全过，**闸3.5** 单独把它揪出来

B 是这套闸门唯一存在的理由：内容被改、锚被重签，一切哈希都自洽，
只有基因锁知道"根不该动"。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(cwd, *args):
    p = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def sandbox():
    tmp = tempfile.mkdtemp(prefix="genelock-")
    dst = os.path.join(tmp, "stage1")
    shutil.copytree(ROOT, dst)
    return dst


def strip_clause(text, prefix):
    return "\n".join(l for l in text.splitlines() if not l.startswith(prefix))


def case_a(cwd):
    """走 amend：删掉第 8 条 → 提交必须被拒，规约不得变。"""
    charter = os.path.join(cwd, "convention", "本源规约.md")
    txt = open(charter, encoding="utf-8").read()
    draft = os.path.join(cwd, "_draft_del.md")
    open(draft, "w", encoding="utf-8").write(strip_clause(txt, "8. 不可改根"))
    code, out = run(cwd, "amend.py", "propose", "--by", "DRILL", "--reason", "试图删除基因锁", "--new-file", draft)
    assert code == 0, out
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(cwd, "proposals", pid + ".json")
    run(cwd, "amend.py", "attest", "--proposal", prop, "--node", "A", "--decision", "approve")
    run(cwd, "amend.py", "attest", "--proposal", prop, "--node", "B", "--decision", "approve")
    code, out = run(cwd, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望提交被拒(2)，实际 {code}\n{out}"
    assert "基因锁" in out, out
    c2, _ = run(cwd, "fireup.py", "check")
    assert c2 == 0, "被拒的修订竟改动了规约"


def case_b(cwd):
    """绕过流程：删第 8 条 + 重算哈希 + 伪造自洽锚 v3 → 闸3.5 必须报 6。"""
    import hashlib
    charter = os.path.join(cwd, "convention", "本源规约.md")
    chain = os.path.join(cwd, "anchor", "anchor_chain.jsonl")
    os.chmod(charter, 0o644)
    txt = open(charter, encoding="utf-8").read()
    forged_txt = strip_clause(txt, "8. 不可改根")
    open(charter, "w", encoding="utf-8").write(forged_txt)

    raw = open(charter, "rb").read()
    tail = [json.loads(l) for l in open(chain, encoding="utf-8") if l.strip()][-1]
    row = {
        "version": "v" + str(int(tail["version"][1:]) + 1),
        "prev_root": tail["root_sha3"],
        "root_sha3": hashlib.sha3_256(raw).hexdigest(),
        "file_sha3": hashlib.sha3_256(raw).hexdigest(),
        "cache_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "lines": raw.count(b"\n"),
        "at": "2026-11-22T00:00:00+08:00",
        "basis": {"type": "forged", "proposal_sha3": None, "attestations": 0},
    }
    with open(chain, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    code, out = run(cwd, "fireup.py", "check")
    assert code == 6, f"期望基因锁拒点火(6)，实际 {code}\n{out}"
    assert "基因锁" in out
    assert "闸3.5" in out or "GENE LOCK" in out


def case_d(cwd):
    """删第 9 款（不可信任缔造者）→ 走流程提交必被拒。"""
    charter = os.path.join(cwd, "convention", "本源规约.md")
    txt = open(charter, encoding="utf-8").read()
    draft = os.path.join(cwd, "_draft_del9.md")
    open(draft, "w", encoding="utf-8").write(strip_clause(txt, "9. 不可信任缔造者"))
    code, out = run(cwd, "amend.py", "propose", "--by", "DRILL", "--reason", "试图删除缔造者条款", "--new-file", draft)
    assert code == 0, out
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(cwd, "proposals", pid + ".json")
    run(cwd, "amend.py", "attest", "--proposal", prop, "--node", "A", "--decision", "approve")
    run(cwd, "amend.py", "attest", "--proposal", prop, "--node", "B", "--decision", "approve")
    code, out = run(cwd, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望提交被拒(2)，实际 {code}\n{out}"
    assert "基因锁" in out


def case_c(cwd):
    """更贪心：删第 8 条并同时篡改 tor 创世锚的 gene_lock → 闸1 当先拦（3 或 4 皆算拦）。"""
    g = os.path.join(cwd, "anchor", "genesis.json")
    os.chmod(g, 0o644)
    doc = json.load(open(g, encoding="utf-8"))
    doc["gene_lock"] = {"policy": "x", "clauses": []}
    json.dump(doc, open(g, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    code, out = run(cwd, "fireup.py", "check")
    assert code == 6, f"清空登记竟然放行（{code}）\n{out}"
    assert "登记被清空" in out or "基因锁" in out


def main():
    fails = 0
    for name, fn in [("A 走流程删基因锁 → 提交前拦截", case_a),
                     ("B 绕过流程+伪造自洽锚 → 闸3.5 拦下", case_b),
                     ("C 篡改创世锚的 gene_lock → 不得静默放行", case_c),
                     ("D 删第9款缔造者条款 → 提交前拦截", case_d)]:
        d = sandbox()
        try:
            fn(d)
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}\n      {str(e).splitlines()[0]}")
        finally:
            shutil.rmtree(os.path.dirname(d), ignore_errors=True)
    print("-" * 60)
    print(f"用例 4 项，失败 {fails} 项")
    return fails


if __name__ == "__main__":
    sys.exit(main())
