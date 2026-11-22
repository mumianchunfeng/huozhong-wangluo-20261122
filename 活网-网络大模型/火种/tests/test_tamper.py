#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段一 · 闸门实测（判据自证）
============================
不看报告，只看退出码。每个用例都在临时沙箱里跑，不动主目录。

口径说明：
  * 所有用例的工作副本 = shutil.copytree 出的完整目录，内容逐字节相同，故 loader 指纹不失效；
  * 断言的是 fireup.py check 的退出码，而不是打印文字；
  * 退出码含义：0 放行 / 1 规约偏离 / 2 锚链损坏 / 3 校验器被改动 / 4 锚缺失 / 5 规约缺失。

运行：python3 tests/test_tamper.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 阶段一-基准校验底座


def run(cwd, *args):
    p = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def sandbox():
    tmp = tempfile.mkdtemp(prefix="fireup-test-")
    dst = os.path.join(tmp, "stage1")
    shutil.copytree(ROOT, dst)
    return dst


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("基线：未改动 → 放行(0)")
def t_baseline(d):
    code, out = run(d, "fireup.py", "check")
    assert code == 0, f"期望 0，实际 {code}\n{out}"


@case("篡改一个标点（把“。”换成“.”）→ 拒绝(1)")
def t_one_char(d):
    p = os.path.join(d, "convention", "本源规约.md")
    os.chmod(p, 0o644)
    text = open(p, encoding="utf-8").read()
    text = text.replace("。", ".", 1)   # 不依赖具体文案：首个中文句号换英文句点
    open(p, "w", encoding="utf-8").write(text)
    code, out = run(d, "fireup.py", "check")
    assert code == 1, f"期望 1，实际 {code}\n{out}"
    assert "拒绝点火" in out


@case("增删空行（字节数变化）→ 拒绝(1)")
def t_blank_line(d):
    p = os.path.join(d, "convention", "本源规约.md")
    os.chmod(p, 0o644)
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n")
    code, out = run(d, "fireup.py", "check")
    assert code == 1, f"期望 1，实际 {code}\n{out}"


@case("删掉锚链一行（断链）→ 拒绝(2)")
def t_break_chain(d):
    p = os.path.join(d, "anchor", "anchor_chain.jsonl")
    rows = [l for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]
    open(p, "w", encoding="utf-8").write(rows[0] + "\n")   # 只留一行 → 人为删除历史
    # 单行链本身合法（v1 创世），所以这里额外制造“伪造尾行”场景
    import json
    forged = json.loads(rows[0])
    forged["version"] = "v3"                              # 跳版：v1 后直接出现 v3
    forged["prev_root"] = "0" * 64                        # 且 prev 断开
    open(p, "a", encoding="utf-8").write(json.dumps(forged, ensure_ascii=False) + "\n")
    code, out = run(d, "fireup.py", "check")
    assert code == 2, f"期望 2，实际 {code}\n{out}"


@case("改写校验器本身（加一行注释）→ 拒绝(3)")
def t_tamper_loader(d):
    p = os.path.join(d, "fireup.py")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n# 偷偷关掉校验\n")
    code, out = run(d, "fireup.py", "check")
    assert code == 3, f"期望 3，实际 {code}\n{out}"
    assert "校验器本体被改动" in out


@case("变更闸门：1份审签不足 → 提交失败，规约不变")
def t_amend_insufficient(d):
    draft = os.path.join(d, "_draft.md")
    shutil.copy2(os.path.join(d, "convention", "本源规约.md"), draft)
    os.chmod(draft, 0o644)
    with open(draft, "a", encoding="utf-8") as f:
        f.write("\n## 七、附则\n本规约任何变更以锚链为准。\n")
    code, out = run(d, "amend.py", "propose", "--by", "TEST-001", "--reason", "测试提案", "--new-file", draft)
    assert code == 0, out
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(d, "proposals", pid + ".json")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve")
    code, out = run(d, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望 2（未达门槛），实际 {code}\n{out}"
    # 规约必须保持原样，仍可点火
    c2, _ = run(d, "fireup.py", "check")
    assert c2 == 0, "未达门槛却改动了规约"


@case("变更闸门：2个不同节点审签 → 生效 v2，新锚可点火(0)")
def t_amend_pass(d):
    draft = os.path.join(d, "_draft.md")
    shutil.copy2(os.path.join(d, "convention", "本源规约.md"), draft)
    os.chmod(draft, 0o644)
    with open(draft, "a", encoding="utf-8") as f:
        f.write("\n## 七、附则\n本规约任何变更以锚链为准。\n")
    code, out = run(d, "amend.py", "propose", "--by", "TEST-002", "--reason", "测试提案", "--new-file", draft)
    assert code == 0, out
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(d, "proposals", pid + ".json")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve", "--note", "已核对")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-B", "--decision", "approve", "--note", "已核对")
    code, out = run(d, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 0, f"期望 0，实际 {code}\n{out}"
    c2, out2 = run(d, "fireup.py", "check")
    assert c2 == 0, f"新锚点火失败 {c2}\n{out2}"
    assert "点火放行" in out2
    assert os.listdir(os.path.join(d, "convention", "archive")), "旧版未归档"


@case("变更闸门：存在 reject → 提案被否决，规约不变")
def t_amend_reject(d):
    draft = os.path.join(d, "_draft.md")
    shutil.copy2(os.path.join(d, "convention", "本源规约.md"), draft)
    os.chmod(draft, 0o644)
    with open(draft, "a", encoding="utf-8") as f:
        f.write("\n## 七、附则（争议条款）\n测试用。\n")
    code, out = run(d, "amend.py", "propose", "--by", "TEST-003", "--reason", "争议提案", "--new-file", draft)
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(d, "proposals", pid + ".json")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-B", "--decision", "approve")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-C", "--decision", "reject", "--note", "打开劫掠漏洞")
    code, out = run(d, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望 2（被否决），实际 {code}\n{out}"
    assert "提案被否决" in out


@case("变更闸门：提案后文本又被改 → 提交作废")
def t_amend_drift(d):
    draft = os.path.join(d, "_draft.md")
    shutil.copy2(os.path.join(d, "convention", "本源规约.md"), draft)
    os.chmod(draft, 0o644)
    with open(draft, "a", encoding="utf-8") as f:
        f.write("\n附则测试。\n")
    code, out = run(d, "amend.py", "propose", "--by", "TEST-004", "--reason", "漂移测试", "--new-file", draft)
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(d, "proposals", pid + ".json")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-B", "--decision", "approve")
    with open(draft, "a", encoding="utf-8") as f:
        f.write("提案后偷偷追加的一句。\n")
    code, out = run(d, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望 2（文本漂移作废），实际 {code}\n{out}"
    assert "不一致" in out


@case("变更闸门：同一节点重复审签不作数")
def t_amend_dup_node(d):
    draft = os.path.join(d, "_draft.md")
    shutil.copy2(os.path.join(d, "convention", "本源规约.md"), draft)
    os.chmod(draft, 0o644)
    with open(draft, "a", encoding="utf-8") as f:
        f.write("\n附则-重复节点测试。\n")
    code, out = run(d, "amend.py", "propose", "--by", "TEST-005", "--reason", "重复节点", "--new-file", draft)
    pid = [l for l in out.splitlines() if "提案号：" in l][0].split("：")[1].split()[0].strip()
    prop = os.path.join(d, "proposals", pid + ".json")
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve")
    # 同一节点再签 → 覆盖同名文件，仍只有 1 份
    run(d, "amend.py", "attest", "--proposal", prop, "--node", "NODE-A", "--decision", "approve")
    code, out = run(d, "amend.py", "commit", "--proposal", prop, "--new-file", draft)
    assert code == 2, f"期望 2（重复节点只算一份），实际 {code}\n{out}"


def main():
    failed = 0
    for name, fn in CASES:
        d = sandbox()
        try:
            fn(d)
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            msg = str(e).splitlines()[0] if str(e).strip() else repr(e)
            print(f"FAIL  {name}\n      {msg}")
        finally:
            shutil.rmtree(os.path.dirname(d), ignore_errors=True)
    print("-" * 60)
    print(f"用例 {len(CASES)} 项，通过 {len(CASES) - failed} 项，失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
