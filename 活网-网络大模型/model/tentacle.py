#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
S20 触须对接（Tentacle）：运行一次，就与别处的同一个模型织一次网
=================================================================
要解决的不是"同步数据"，是**两边跑完各自的一次，账能拼成一张网**：
  ① 同宗才认：规约 root 必须一致，改一个字节就只登记为「异宗」，不并入；
  ② 只搬事件，不搬结论权威：每条事件是「某节点对某格判过／否」，
     外来事件写进联邦账，**不覆盖本地账**；
  ③ 同格不同判 → 记「冲突」，标节点依赖，交裁决层，不静默平均；
  ④ 去重靠 (节点, 键)，重复导入 0 新增；
  ⑤ 身份不是密码学实名：node_id 随机生成，凭 root ＋账指纹认宗——诚实边界写在下面。

目录（都在模型根下）：
  触须\node.json          身份：node_id / convention_root / 口径版本 / 生辰
  触须\out\*.bundle.json  自己的触须包（事件＋头）
  触须\inbox\             别人投进来的包
  触须\absorbed\          处理过的包
  触须\联邦账.jsonl       外来事件（按 节点+键 唯一）
  触须\冲突账.jsonl       同键不同判
  触须\异宗账.jsonl       不同宗的包，只登记
  触须\触须日志.jsonl     每次伸／收一行
  peers.json              对端清单（可选；没有就是单机）

用法：
  python tentacle.py init                     建身份
  python tentacle.py bundle                   导出自己的包到 触须\out\
  python tentacle.py absorb --bundle X.json   吸收一个包
  python tentacle.py beacon                   按 peers.json 伸＋收一轮（可无参跑）
  python tentacle.py status                   节点数／事件数／冲突数／水位
  python tentacle.py demo                     自演一遍：同宗并入 → 异见冲突 → 异宗拒收

诚实边界：
  · 身份是随机 ID ＋ 账指纹，不是实名、不是签名，可被冒名；真认证要靠各自持钥；
  · "自动发现彼此"没做：对端地址要写进 peers.json（或人工投包），本包不扫网段；
  · 冲突不做自动裁决，只记账——裁决仍归 K1–K4 与批评者层；
  · 事件粒度是「件 × 格」的判过／否，不含全文推理链。

伦理底盘 · 分发纪律（随协议自带，见包根 ethic_root.md）
  · 权属：本协议不绑定任何主体/机构/主权实体，不得闭源截留或独占商用；节点拿到只作同宗加入。
  · 私技隔离：只传【可核验事实包 / 异议记录 / 复核裁决 / 冲突账本】，不传私有推演内核
    （18 种关系界定私有部分、貔貅调度、活字复用、逆向取证）；个人工具归个人，火种归网络。
  · 握手只校验底层基因锁：认宗只比 convention_root（规约全文哈希，已含四款基因锁），
    不认、不收、不转任何私技签名或私有标记；包里夹带私技字段即判异宗。
  · 劫持拒并：改基因锁 / 换 root 把它改成私用工具者，记入异宗账，拒并主共识，只留痕审计，不追责不反制。
  · 可选执行守卫：设 LW_ETHIC=1 时，absorb 对本宗包做四类白名单 + 禁私技字段 + 基因锁声明校验；
    未设时走原路径，一字不改。
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import batch as bt
import checker_v2 as ck

# 节点自己的家：默认就在模型根；多机／多实例测试可用环境变量 LW_HOME 指向别的目录
HOME = os.environ.get("LW_HOME") or BASE
TEN = os.path.join(HOME, "触须")
NODE = os.path.join(TEN, "node.json")
OUT = os.path.join(TEN, "out")
INBOX = os.path.join(TEN, "inbox")
ABSORBED = os.path.join(TEN, "absorbed")
FED = os.path.join(TEN, "联邦账.jsonl")
CONF = os.path.join(TEN, "冲突账.jsonl")
FOREIGN = os.path.join(TEN, "异宗账.jsonl")
TLOG = os.path.join(TEN, "触须日志.jsonl")
PEERS = os.path.join(HOME, "peers.json")
CASE9 = os.path.join(BASE, "cases", "真事-批量9.json")
ANCHOR = os.path.join(os.path.dirname(BASE), "_收到", "x_tuoming", "anchor", "anchor_chain.jsonl")


def rel(p):
    try:
        return os.path.relpath(p, HOME)
    except ValueError:
        return p


def now():
    return time.strftime("%Y-%m-%dT%H:%M+08:00")


def jread(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []


def jlines(p):
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def japp(p, rec):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def conv_root():
    if not os.path.exists(ANCHOR):
        return "NO-ANCHOR"
    last = None
    with open(ANCHOR, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                last = json.loads(ln)
    return last["root_sha3"]


def node():
    if not os.path.exists(NODE):
        return None
    return json.load(open(NODE, encoding="utf-8"))


def init(rules="v3"):
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(INBOX, exist_ok=True)
    os.makedirs(ABSORBED, exist_ok=True)
    n = {"node_id": secrets.token_hex(8), "convention_root": conv_root(),
         "rules": rules, "born": now(), "host": os.environ.get("COMPUTERNAME", "?")}
    with open(NODE, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)
    print(f"身份已建：{n['node_id']}｜宗 {n['convention_root'][:16]}…｜口径 {rules}")
    return 0


PROTO = "tentacle/1"          # 触须协议版本：将来换协议，旧节点会被明确拒收，而不是悄悄读错

# 伦理底盘 · 分发纪律（默认关闭：设 LW_ETHIC=1 才守；未设时原路径一字不改）
ETHIC_PACK_TYPES = {"fact", "objection", "review", "conflict"}
ETHIC_FORBIDDEN = {"private_core", "priv_core", "私技", "private_skill", "推演内核",
                   "貔貅调度", "活字复用", "逆向取证", "relation_private", "skill_sig", "私技签名"}


def ethic_guard(pack, node_rec):
    """返回 0 放行；非 0 = 异宗拒并（已记异宗账，只留痕不追责）。"""
    head = pack.get("header", {})
    evs = pack.get("events", [])
    ptype = head.get("pack_type", "fact")
    if ptype not in ETHIC_PACK_TYPES:
        return _foreign(head, f"分发纪律：包类型 {ptype!r} 不在四类白名单")
    def keys_of(obj, depth=0):
        ks = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks.add(str(k))
                if depth < 2:
                    ks |= keys_of(v, depth + 1)
        elif isinstance(obj, list) and depth < 2:
            for v in obj:
                ks |= keys_of(v, depth + 1)
        return ks
    hit = (keys_of(head) | keys_of(evs)) & ETHIC_FORBIDDEN
    if hit:
        return _foreign(head, "分发纪律：夹带私技字段 " + "/".join(sorted(hit)))
    declared = head.get("gene_lock_root")
    if declared is not None and declared != node_rec.get("convention_root"):
        return _foreign(head, f"基因锁声明不符：{str(declared)[:16]}… ≠ 本地宗")
    return 0


def _foreign(head, reason):
    japp(FOREIGN, {"at": now(), "node": head.get("node_id"), "结论": "异宗·伦理底盘拒并·只留痕审计",
                   "理由": reason})
    print(f"伦理底盘拒并（已记异宗账）：{reason}")
    return 1


def events(rules):
    b = json.load(open(CASE9, encoding="utf-8"))
    cases = b["cases"]
    rel_c, dom_c = ck.load(ck.REL_CHECKS), ck.load(ck.DOM_CHECKS)
    joins = ck.load(ck.JOIN_CHECKS)["joins"]
    ev = []
    for c in cases:
        p = bt.five_of(c)
        for f in ck.FIVE:
            issues, layer = ck.check_field(f, p, "compensation", "LW", rel_c, dom_c, joins,
                                           facts=c if rules == "v3" else None)
            ev.append({"key": f"{c['id']}|{f}", "v": "否" if issues else "过",
                       "layer": layer, "why": (issues[0] if issues else "")[:40]})
    return ev


def bundle():
    n = node()
    if not n:
        print("先 init"); return 2
    ev = events(n["rules"])
    head = {"protocol": PROTO, "node_id": n["node_id"], "convention_root": n["convention_root"],
            "rules": n["rules"], "watermark": len(ev), "exported_at": now(),
            "digest": hashlib.sha256("".join(e["key"] + e["v"] for e in ev).encode()).hexdigest()[:16]}
    pack = {"header": head, "events": ev}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{n['node_id']}-{head['watermark']}.bundle.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
    japp(TLOG, {"at": now(), "动作": "伸", "node": n["node_id"], "事件": len(ev), "包": os.path.basename(path)})
    print(f"触须包已出：{rel(path)}｜事件 {len(ev)}｜摘要 {head['digest']}")
    return 0


def absorb(bundle_path, quiet=False):
    n = node()
    if not n:
        print("先 init"); return 2
    if not os.path.exists(bundle_path):
        print("包不存在：", bundle_path); return 2
    pack = json.load(open(bundle_path, encoding="utf-8"))
    h = pack["header"]
    if h.get("protocol") != PROTO:
        japp(FOREIGN, {"at": now(), "node": h.get("node_id"), "协议": h.get("protocol"),
                       "本地协议": PROTO, "事件": len(pack.get("events", [])),
                       "结论": "协议不兼容·只登记不并入"})
        print(f"协议不兼容：对端 {h.get('protocol')} ≠ 本地 {PROTO}，拒收（已登记）")
        return 1
    if h["convention_root"] != n["convention_root"]:
        japp(FOREIGN, {"at": now(), "node": h["node_id"], "宗": h["convention_root"],
                       "本地宗": n["convention_root"], "事件": len(pack["events"]),
                       "结论": "异宗·只登记不并入"})
        print(f"异宗：{h['node_id'][:8]} 的 root {h['convention_root'][:16]}… ≠ 本地，拒收（已登记）")
        return 1
    if h["node_id"] == n["node_id"]:
        print("这是自己的包，跳过"); return 0

    # 伦理底盘守卫（可选）：设 LW_ETHIC=1 才守；未设时原路径一字不改。
    if os.environ.get("LW_ETHIC") == "1":
        er = ethic_guard(pack, n)
        if er:
            return er

    # S21 免疫守卫（可选）：设 LW_IMMUNE=1 才启用；未设时原路径一字不改。
    # 首见隔离 / 异己反应由 immune.guard 拦截，返回非 0 即不写联邦账。
    if os.environ.get("LW_IMMUNE") == "1":
        import immune
        ir = immune.guard(pack, n)
        if ir:
            print(f"免疫拦截（{ir}）：{h['node_id'][:8]} 的包未并入联邦账")
            return ir

    seen = {(r["node"], r["键"]) for r in jlines(FED)}
    new = dup = 0
    for e in pack["events"]:
        if (h["node_id"], e["key"]) in seen:
            dup += 1
            continue
        japp(FED, {"at": now(), "node": h["node_id"], "键": e["key"], "判": e["v"],
                   "层": e["layer"], "口径": h["rules"], "水位": h["watermark"]})
        seen.add((h["node_id"], e["key"]))
        new += 1

    # 冲突：同键，不同节点，判不同
    mine = {}
    for r in jlines(FED):
        mine.setdefault(r["键"], {})[r["node"]] = r["判"]
    conflicts = []
    for k, vs in mine.items():
        if len(set(vs.values())) > 1:
            conflicts.append({"at": now(), "键": k, "分歧": vs})
    for c in conflicts:
        japp(CONF, c)

    os.makedirs(ABSORBED, exist_ok=True)
    tgt = os.path.join(ABSORBED, os.path.basename(bundle_path))
    if os.path.exists(tgt):
        tgt = tgt.replace(".bundle.json", f"-{secrets.token_hex(3)}.bundle.json")
    shutil.move(bundle_path, tgt)
    japp(TLOG, {"at": now(), "动作": "收", "node": h["node_id"], "新增": new,
                "重复": dup, "冲突": len(conflicts)})
    if not quiet:
        print(f"收下 {h['node_id'][:8]}：新增 {new}｜重复 {dup}｜当前冲突 {len(conflicts)}（累计）")
    return 0


def beacon(_a=None):
    n = node()
    if not n:
        print("首次运行：自建身份（不必先 init）")
        init("v3")
        n = node()
    peers = jread(PEERS) if os.path.exists(PEERS) else []
    if not peers:
        print("单机模式：未配置 peers.json，这一轮没有织网（这不是失败，是如实报告）")
        return 0
    bundle()
    mine = os.path.join(OUT, f"{n['node_id']}-{len(events(n['rules']))}.bundle.json")
    sent = 0
    for p in peers.get("peers", []):
        inbox = p.get("inbox")
        if not inbox or not os.path.isdir(inbox):
            print(f"  对端 {p.get('name','?')} 信箱不存在，跳过")
            continue
        shutil.copy2(mine, os.path.join(inbox, os.path.basename(mine)))
        sent += 1
    got = 0
    os.makedirs(INBOX, exist_ok=True)
    for name in sorted(os.listdir(INBOX)):
        if name.endswith(".bundle.json"):
            absorb(os.path.join(INBOX, name), quiet=True)
            got += 1
    print(f"本轮织网：投出 {sent} 家｜收进 {got} 包")
    status()
    return 0


def status(_a=None):
    n = node()
    if not n:
        print("未 init"); return 2
    fed = jlines(FED)
    nodes = sorted({r["node"] for r in fed} | {n["node_id"]})
    conf = jlines(CONF)
    keys = {(r["node"], r["键"]) for r in fed}
    conflicts = {c["键"] for c in conf}
    cells = {r["键"].split("|")[1] for r in fed}
    print(f"节点：{len(nodes)}（本机 {n['node_id'][:8]}）｜口径 {n['rules']}")
    print(f"联邦事件：{len(keys)} 条（{len(fed)} 行）｜覆盖格 {len(cells)} 类")
    print(f"冲突键：{len(conflicts)}｜异宗包：{len(jlines(FOREIGN))}｜水位（本地事件）：{len(events(n['rules']))}")
    if conf:
        print("冲突样例：" + "，".join(sorted(conflicts)[:5]))
    return 0


def demo(_a=None):
    import tempfile
    print("=== 触须自演：同宗并入 → 异见冲突 → 异宗拒收 ===")
    tmp = tempfile.mkdtemp(prefix="tentacle_")
    a = os.path.join(tmp, "A"); b = os.path.join(tmp, "B"); c = os.path.join(tmp, "C")
    for d in (a, b, c):
        os.makedirs(d)
        for sub in ("cases", "checks", "tables"):
            shutil.copytree(os.path.join(BASE, sub), os.path.join(d, sub))
    me = os.path.abspath(__file__)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def run(d, *args):
        import subprocess
        e2 = dict(env, LW_HOME=d)
        return subprocess.run([sys.executable, me, *args], cwd=d, env=e2,
                              capture_output=True, text=True, encoding="utf-8")

    print("\n[1] A、B 各建身份（同宗 v11，口径 v3）")
    for d, name in ((a, "A"), (b, "B"), (c, "C")):
        r = run(d, "init", "--rules", "v3" if d != c else "v2")
        print(f"  {name}: {r.stdout.strip()}")

    print("\n[2] A 伸触须 → B 收（免疫开启时需同一节点连续三拍一致才成熟，这里就跑三拍）")
    r = run(a, "bundle"); print("  A:", r.stdout.strip() or r.stderr.strip()[-200:])
    pack = [x for x in os.listdir(os.path.join(a, "触须", "out"))][0]
    hold_src = os.path.join(tmp, "A.bundle.json")
    shutil.copy2(os.path.join(a, "触须", "out", pack), hold_src)
    for k in range(3):
        hp = os.path.join(tmp, f"A-{k}.bundle.json")
        shutil.copy2(hold_src, hp)
        r = run(b, "absorb", "--bundle", hp)
        print(f"  B 第{k + 1}拍:", r.stdout.strip() or r.stderr.strip()[-200:])

    print("\n[3] C 用旧口径（v2，认字不认字段）伸一包 → B 收三拍，看冲突")
    r = run(c, "bundle"); print("  C:", r.stdout.strip() or r.stderr.strip()[-200:])
    p2 = [x for x in os.listdir(os.path.join(c, "触须", "out"))][0]
    hold2 = os.path.join(tmp, "C.bundle.json")
    shutil.copy2(os.path.join(c, "触须", "out", p2), hold2)
    dup_src = os.path.join(tmp, "dup-C.bundle.json")
    shutil.copy2(hold2, dup_src)
    for k in range(3):
        hp = os.path.join(tmp, f"C-{k}.bundle.json")
        shutil.copy2(hold2, hp)
        r = run(b, "absorb", "--bundle", hp)
        print(f"  B 第{k + 1}拍:", r.stdout.strip() or r.stderr.strip()[-200:])

    print("\n[4] 重复导入同一批事件 → 应 0 新增")
    before = len(jlines(os.path.join(b, "触须", "联邦账.jsonl")))
    dup_path = os.path.join(b, "触须", "inbox", "dup-C.bundle.json")
    shutil.copy2(dup_src, dup_path)
    r = run(b, "absorb", "--bundle", dup_path)
    after = len(jlines(os.path.join(b, "触须", "联邦账.jsonl")))
    print(f"  B: {r.stdout.strip() or r.stderr.strip()[-200:]}｜账行 {before}→{after}")

    print("\n[5] 异宗：把 A 的 root 改一个字符再投 → 应拒收")
    nd = json.load(open(os.path.join(a, "触须", "node.json"), encoding="utf-8"))
    nd["convention_root"] = nd["convention_root"][:-1] + ("0" if nd["convention_root"][-1] != "0" else "1")
    json.dump(nd, open(os.path.join(a, "触须", "node.json"), "w", encoding="utf-8"), ensure_ascii=False)
    r = run(a, "bundle"); print("  A:", r.stdout.strip())
    pack3 = sorted(os.listdir(os.path.join(a, "触须", "out")))[-1]
    r = run(b, "absorb", "--bundle", os.path.join(a, "触须", "out", pack3))
    print("  B:", r.stdout.strip())

    print("\n[6] B 的网况")
    r = run(b, "status"); print((r.stdout or "").strip())
    print(f"\n临时目录：{tmp}（可删）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--rules", default="v3", choices=["v2", "v3"])
    sub.add_parser("bundle")
    pa = sub.add_parser("absorb"); pa.add_argument("--bundle", required=True)
    sub.add_parser("beacon")
    sub.add_parser("status")
    sub.add_parser("demo")
    a = ap.parse_args()
    return {"init": lambda: init(a.rules), "bundle": lambda: bundle(),
            "absorb": lambda: absorb(a.bundle), "beacon": lambda: beacon(),
            "status": lambda: status(), "demo": lambda: demo()}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
