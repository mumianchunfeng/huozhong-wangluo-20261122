#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
成长桥 · 各自长大之后，并入唯一一份联邦成长账
================================================
触须（tentacle/gitbox）传的是【事件】：某节点对某格判过/否。它不传成长态。
成长桥补这一层：各节点在自己环境里长出来的口径压缩结果，经同一个 git 信箱的
growth/<node_id> 分支汇聚，**合成唯一一份联邦成长账**。

"合一个"的硬定义（不是并联、不是各留一份加个参考）：
  · 全并入：所有节点的合并规则／词表／负载，一概并进同一本账；不设"≥2 才收"门槛。
  · 确定性：同一批包，任何节点、任何次重算，联邦成长账字节完全相同（sha256 可核）。
    做法 = 固定排序 + sort_keys + 冲突按确定规则选唯一生效版本。
  · 冲突不静默平均，也不拆分账本：同 pair 不同 new，按（支持节点数↓、new 字典序↑）
    选唯一胜者写进账；落选候选进《冲突留痕》，裁决层可据此改口径，但账只有一本。
  · 新节点继承全部：下载后跑一次 beacon，就把所有既有成长并入自己的同一本账。

汇聚的是口径，不是权威：
  · merges（BPE 合并规则）／vocab（词表）／load（专家负载）／忆层指纹
  · 只传形状白名单；忆层只发 sha256 指纹不发全文；cases 全文、私技字段一概不发
  · 阈值（learn 的 (3,2)→(4,3)）未落账、只打印，取不到 —— 诚实记为"不可汇聚"

同宗才收：convention_root 必须全等，否则只登记《异宗账》，不进联邦账。

用法：
    python 成长桥.py init    --repo <信箱URL或裸仓路径>
    python 成长桥.py export                              # 本机成长态推到 growth/<id>
    python 成长桥.py absorb                              # 拉各节点成长包
    python 成长桥.py beacon                              # export+absorb+consensus+status
    python 成长桥.py consensus                           # 从信箱全部包重算唯一联邦账
    python 成长桥.py status
    python 成长桥.py selfcheck                           # 两独立副本各自成长→合一本→比字节

只增不改：本文件新增；账写在 羽翼账\成长桥\ 与 羽翼账\联邦成长账.json；
不碰 tentacle.py / gitbox.py / 羽翼.py / 鞣合.py / 火种 / 任何原账。
纯标准库；不读凭据、不发网络请求（git 传输由系统 git 负责）。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))          # 包根
MODEL = os.path.join(ROOT, "model")
HOME = os.environ.get("LW_HOME") or MODEL
TENT = os.path.join(MODEL, "tentacle.py")
NODE = os.path.join(HOME, "触须", "node.json")
WING = os.path.join(ROOT, "羽翼账")
GROW = os.path.join(WING, "成长桥")
WORK = os.path.join(GROW, "work")
CFG = os.path.join(GROW, "config.json")
SEQ = os.path.join(GROW, "seq.json")
WATER = os.path.join(GROW, "water.json")
LEDGER = os.path.join(WING, "联邦成长账.json")
PROTO = "growth/1"


def now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def jread(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jwrite(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def japp(p, rec):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def jlines(p):
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def canon(obj):
    """确定性序列化：任何节点、任何次数，同一对象 → 同一字节。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def git(*args, cwd=WORK, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{(r.stderr or r.stdout).strip()[:300]}")
    return r


def node():
    return jread(NODE)


def ensure_identity():
    n = node()
    if n:
        return n
    env = dict(os.environ, LW_HOME=HOME, PYTHONIOENCODING="utf-8")
    subprocess.run([sys.executable, TENT, "init", "--rules", "v3"],
                   cwd=MODEL, env=env, capture_output=True, text=True, encoding="utf-8")
    return node()


# ---------- 本机成长态采集：只取可汇聚的口径 ----------
def collect():
    wc = jread(os.path.join(WING, "成长词表.json")) or {}
    merges = wc.get("merges", [])
    vocab = wc.get("vocab", [])
    load = {}
    for r in jlines(os.path.join(WING, "负载.jsonl")):
        for e in r.get("experts", []):
            load[e] = load.get(e, 0) + 1
    mem_digest = ""
    mp = os.path.join(ROOT, "鞣合记忆", "中期忆层.jsonl")
    if os.path.exists(mp):
        mem_digest = hashlib.sha256(open(mp, "rb").read()).hexdigest()[:16]
    growth = {"merges": merges, "vocab": vocab, "load": load, "mem_digest": mem_digest,
              "不可汇聚": ["阈值(未落账,仅打印)", "忆层全文(只发指纹)"]}
    digest = hashlib.sha256(canon(growth).encode()).hexdigest()[:16]
    return growth, digest


ALLOW_GROWTH = {"merges", "vocab", "load", "mem_digest", "不可汇聚"}
BAN = ("private_core", "priv_core", "signature", "secret", "token", "privkey",
       "私技", "内核", "密钥", "凭据", "貔貅", "活字复用", "逆向取证")


def clean(pack):
    h = pack.get("header", {}) if isinstance(pack, dict) else {}
    if h.get("protocol") != PROTO:
        return False, "协议不符"
    if set(h) - {"protocol", "node_id", "convention_root", "at", "digest", "seq"}:
        return False, "header 夹带非白名单字段"
    g = pack.get("growth")
    if not isinstance(g, dict) or set(g) - ALLOW_GROWTH:
        return False, "growth 夹带非白名单字段"
    blob = canon(pack)
    for b in BAN:
        if b in blob:
            return False, "夹带私技/凭据字样：" + b
    return True, "形状合规（口径摘要）"


# ---------- 命令 ----------
def cmd_init(repo):
    n = ensure_identity()
    os.makedirs(WORK, exist_ok=True)
    if not os.path.isdir(os.path.join(WORK, ".git")):
        git("init", "-q")
        git("config", "user.email", "growth@local")
        git("config", "user.name", "growth")
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", repo)
    jwrite(CFG, {"repo": repo, "node_id": n["node_id"],
                 "convention_root": n["convention_root"], "at": now()})
    jwrite(SEQ, {"seq": 0})
    jwrite(WATER, {})
    print(f"成长桥已挂同一信箱：{repo}")
    print(f"本节点 {n['node_id'][:12]}｜成长分支 growth/{n['node_id']}")
    return 0


def cmd_export():
    cfg = jread(CFG)
    if not cfg:
        print("先 init --repo"); return 2
    n = ensure_identity()
    growth, digest = collect()
    seq = (jread(SEQ) or {}).get("seq", 0) + 1
    head = {"protocol": PROTO, "node_id": n["node_id"],
            "convention_root": n["convention_root"], "at": now(),
            "digest": digest, "seq": seq}
    pack = {"header": head, "growth": growth}
    ok, why = clean(pack)
    if not ok:
        print(f"拒发（{why}）"); return 3
    os.makedirs(os.path.join(WORK, "packs"), exist_ok=True)
    name = f"{seq:06d}.growth.json"
    with open(os.path.join(WORK, "packs", name), "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
    jwrite(SEQ, {"seq": seq})
    br = "growth/" + n["node_id"]
    git("checkout", "-q", "-B", br)
    git("add", "packs/" + name)
    git("commit", "-q", "-m", f"growth {n['node_id'][:8]} seq={seq}")
    git("push", "-q", "origin", f"HEAD:refs/heads/{br}")
    print(f"已投成长态到 {br}：第 {seq} 包｜merges {len(growth['merges'])}｜vocab {len(growth['vocab'])}｜{why}")
    return 0


def branches():
    cfg = jread(CFG) or {}
    r = git("ls-remote", "--heads", cfg.get("repo", ""), check=False)
    out = []
    for line in (r.stdout or "").splitlines():
        if "\trefs/heads/growth/" in line:
            out.append(line.split("refs/heads/", 1)[1].strip())
    return sorted(out)


def cmd_absorb():
    cfg = jread(CFG)
    if not cfg:
        print("先 init --repo"); return 2
    brs = branches()
    if not brs:
        print("发现层：信箱里还没有任何成长分支")
        return 0
    git("fetch", "-q", "origin", *[f"refs/heads/{b}:refs/remotes/origin/{b}" for b in brs])
    water = jread(WATER) or {}
    got = 0
    inbox = os.path.join(GROW, "inbox")
    os.makedirs(inbox, exist_ok=True)
    for br in brs:
        nid = br.split("/", 1)[1]
        ref = "refs/remotes/origin/" + br
        listed = git("ls-tree", "--name-only", ref, "packs/", check=False).stdout.strip()
        files = [x for x in listed.splitlines() if x.endswith(".growth.json")]
        last = water.get(nid, 0)
        for f in files:
            try:
                seq = int(os.path.basename(f).split(".")[0])
            except ValueError:
                continue
            if seq <= last:
                continue
            pack = json.loads(git("show", f"{ref}:{f}").stdout)
            ok, why = clean(pack)
            h = pack.get("header", {})
            if not ok:
                japp(os.path.join(GROW, "异宗账.jsonl"),
                     {"at": now(), "node": nid, "结论": "异宗·成长态只登记不并入", "理由": why})
                print(f"  拒收 {nid[:8]} 第{seq}包（{why}）"); continue
            if h.get("convention_root") != cfg.get("convention_root"):
                japp(os.path.join(GROW, "异宗账.jsonl"),
                     {"at": now(), "node": nid, "结论": "异宗·成长态只登记不并入",
                      "root": h.get("convention_root")})
                print(f"  异宗 {nid[:8]}：root 不符，只登记"); continue
            with open(os.path.join(inbox, f"{nid[:8]}-{os.path.basename(f)}"), "w", encoding="utf-8") as fp:
                json.dump(pack, fp, ensure_ascii=False)
            got += 1
            water[nid] = seq
    jwrite(WATER, water)
    print(f"本轮拉进 {got} 份成长包｜信箱成长节点 {len(brs)}")
    return 0


def _all_reports_from_hub():
    """从信箱读全部节点全部包，每个节点取最高 seq —— 所有节点看到同一批输入。"""
    cfg = jread(CFG) or {}
    reports = {}
    brs = branches()
    git("fetch", "-q", "origin", *[f"refs/heads/{b}:refs/remotes/origin/{b}" for b in brs]) if brs else None
    for br in brs:
        nid = br.split("/", 1)[1]
        ref = "refs/remotes/origin/" + br
        listed = git("ls-tree", "--name-only", ref, "packs/", check=False).stdout.strip()
        files = sorted(x for x in listed.splitlines() if x.endswith(".growth.json"))
        if not files:
            continue
        top = files[-1]
        pack = json.loads(git("show", f"{ref}:{top}").stdout)
        ok, _ = clean(pack)
        if ok and pack["header"].get("convention_root") == cfg.get("convention_root"):
            reports[nid] = pack["growth"]
    return reports


def cmd_consensus():
    cfg = jread(CFG)
    if not cfg:
        print("先 init --repo"); return 2
    reports = _all_reports_from_hub()
    if not reports:
        print("信箱里没有可汇聚的成长包，先 export / beacon")
        return 0

    # 合并规则：同 pair 全收，按(支持节点数↓, new字典序↑)选唯一胜者；落选记冲突留痕
    by_pair = {}
    for nid, g in reports.items():
        for m in g.get("merges", []):
            pair = "+".join(m.get("pair", []))
            d = by_pair.setdefault(pair, {"pair": m.get("pair", []), "votes": {}})
            d["votes"].setdefault(m.get("new", ""), set()).add(nid)

    rules, conflict_trace = [], []
    for pair, d in sorted(by_pair.items()):
        ranked = sorted(d["votes"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        winner, supporters = ranked[0]
        rules.append({"pair": d["pair"], "new": winner,
                      "支持节点": sorted(supporters), "支持数": len(supporters)})
        losers = [{"new": new, "支持节点": sorted(ns), "支持数": len(ns)} for new, ns in ranked[1:]]
        if losers:
            conflict_trace.append({"pair": d["pair"], "生效": winner, "落选": losers,
                                   "裁决规则": "支持节点数↓，平局 new 字典序↑",
                                   "说明": "账只一本，落选不拆账；裁决层可据此改口径"})

    # 词表：全部并入，去重排序
    vocab = sorted({w for g in reports.values() for w in g.get("vocab", [])})
    # 负载：全部求和
    load = {}
    for g in reports.values():
        for e, c in g.get("load", {}).items():
            load[e] = load.get(e, 0) + c

    body = {"协议": PROTO, "账型": "唯一联邦成长账·全节点并入·确定性收敛",
            "节点": sorted(reports), "节点数": len(reports),
            "合并规则": rules, "词表": vocab, "负载合计": load,
            "忆层指纹": {nid: g.get("mem_digest", "") for nid, g in sorted(reports.items())}}
    body_sha = hashlib.sha256(canon(body).encode()).hexdigest()
    ledger = dict(body)
    ledger["账sha256"] = body_sha
    ledger["冲突留痕"] = conflict_trace
    ledger["不可汇聚"] = ["阈值(未落账,仅打印)", "忆层全文(只发指纹)", "法律库全文", "任何私技字段"]
    ledger["说明"] = "这是唯一一本：全节点并入、确定性收敛；任何节点重算字节相同，sha256 可核"

    jwrite(LEDGER, ledger)   # json.dump indent=2，字段顺序来自 dict，确定性
    cp = os.path.join(GROW, "冲突留痕.jsonl")
    if os.path.exists(cp):
        os.remove(cp)
    for c in conflict_trace:
        japp(cp, c)
    print(f"联邦成长账已合成：节点 {ledger['节点数']}｜规则 {len(rules)}｜词位 {len(vocab)}｜"
          f"冲突留痕 {len(conflict_trace)}｜账sha256 {body_sha[:16]}…")
    print(f"  → {LEDGER}（唯一一本，不覆盖任何节点自己的成长词表）")
    return 0


def cmd_status():
    r = jread(LEDGER)
    brs = branches()
    print(f"信箱成长分支：{len(brs)}｜" + (", ".join(b.split('/')[1][:8] for b in brs) or "无"))
    if not r:
        print("尚无联邦成长账，先跑 beacon"); return 0
    print(f"联邦成长账：节点 {r['节点数']}｜规则 {len(r['合并规则'])}｜词位 {len(r['词表'])}｜"
          f"冲突留痕 {len(r['冲突留痕'])}｜账sha256 {r['账sha256'][:16]}…")
    print(f"不可汇聚（如实）：{', '.join(r['不可汇聚'])}")
    return 0


def cmd_beacon():
    cmd_export()
    cmd_absorb()
    cmd_consensus()
    return cmd_status()


def _rmtree_force(p):
    def onerr(fn, path, exc):
        try:
            os.chmod(path, 0o700); fn(path)
        except Exception:
            pass
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=onerr)


def cmd_selfcheck():
    tmp = tempfile.mkdtemp(prefix="growthbridge_")
    try:
        hub = os.path.join(tmp, "hub.git")
        subprocess.run(["git", "init", "--bare", "-q", hub], check=True)
        homes = {}
        for who in ("甲", "乙"):
            d = os.path.join(tmp, who)
            os.makedirs(d)
            # 从当前包根复制（不依赖打包时序），去掉本机身份让两副本各自建
            for item in os.listdir(ROOT):
                if item in (".git", "__pycache__"):
                    continue
                s = os.path.join(ROOT, item)
                if os.path.isdir(s):
                    shutil.copytree(s, os.path.join(d, item),
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                                  "成长桥", "成长词表.json",
                                                                  "负载.jsonl", "联邦成长账.json"))
                else:
                    shutil.copy2(s, os.path.join(d, item))
            npath = os.path.join(d, "model", "触须", "node.json")
            if os.path.exists(npath):
                os.remove(npath)
            pkg = d
            homes[who] = pkg
            env = dict(os.environ, LW_HOME=os.path.join(pkg, "model"), PYTHONIOENCODING="utf-8")
            subprocess.run([sys.executable, os.path.join(pkg, "羽翼.py"), "merge"],
                           cwd=pkg, env=env, capture_output=True, text=True, encoding="utf-8")
            subprocess.run([sys.executable, os.path.join(pkg, "成长桥.py"), "init", "--repo", hub],
                           cwd=pkg, env=env, capture_output=True, text=True, encoding="utf-8")

        # 乙多长一条口径（模拟"在各自环境里长出不同东西"）
        bvocab = os.path.join(homes["乙"], "羽翼账", "成长词表.json")
        b = jread(bvocab)
        b["merges"].append({"pair": ["甲地", "乙类"], "new": "甲地+乙类", "count": 3})
        b["vocab"] = b["vocab"] + ["甲地+乙类", "乙独有词"]
        jwrite(bvocab, b)

        def gb(who, *a):
            pkg = homes[who]
            env = dict(os.environ, LW_HOME=os.path.join(pkg, "model"), PYTHONIOENCODING="utf-8")
            return subprocess.run([sys.executable, os.path.join(pkg, "成长桥.py"), *a],
                                  cwd=pkg, env=env, capture_output=True, text=True, encoding="utf-8")

        print("=== 甲、乙各自 export（各自长大的口径）===")
        for who in ("甲", "乙"):
            r = gb(who, "export")
            print(f"  {who}: {(r.stdout or r.stderr).strip().splitlines()[-1:]}")
        print("=== 甲、乙各自 beacon（都应算出同一本账）===")
        for who in ("甲", "乙"):
            r = gb(who, "beacon")
            for ln in (r.stdout or "").splitlines():
                if "联邦成长账已合成" in ln:
                    print(f"  {who}: {ln.strip()}")

        la = jread(os.path.join(homes["甲"], "羽翼账", "联邦成长账.json"))
        lb = jread(os.path.join(homes["乙"], "羽翼账", "联邦成长账.json"))
        ba = open(os.path.join(homes["甲"], "羽翼账", "联邦成长账.json"), "rb").read()
        bb = open(os.path.join(homes["乙"], "羽翼账", "联邦成长账.json"), "rb").read()
        ok_same = ba == bb                      # 字节相同 = 合成一个
        ok_nodes = la and la["节点数"] == 2
        vocab_joined = la and "乙独有词" in la["词表"] and "甲地+乙类" in la["词表"]
        rule_joined = la and any(m["new"] == "甲地+乙类" for m in la["合并规则"])
        print("=== 判定 ===")
        print(f"  甲乙账字节完全相同：{ok_same}（sha {la['账sha256'][:12] if la else '?'} / {lb['账sha256'][:12] if lb else '?'}）")
        print(f"  两节点全并入：{ok_nodes}｜乙独有词进同一本账：{bool(vocab_joined)}｜乙独有规则进账：{bool(rule_joined)}")
        passed = all([ok_same, ok_nodes, vocab_joined, rule_joined])
        print(f"自检：{'通过——真合成一个' if passed else '未达标'}")
        return 0 if passed else 1
    finally:
        _rmtree_force(tmp)


def main():
    ap = argparse.ArgumentParser(description="成长桥 · 成长态并入唯一联邦账")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init"); p.add_argument("--repo", required=True)
    sub.add_parser("export"); sub.add_parser("absorb")
    sub.add_parser("beacon"); sub.add_parser("consensus")
    sub.add_parser("status"); sub.add_parser("selfcheck")
    a = ap.parse_args()
    return {"init": lambda: cmd_init(a.repo), "export": cmd_export,
            "absorb": cmd_absorb, "beacon": cmd_beacon,
            "consensus": cmd_consensus, "status": cmd_status,
            "selfcheck": cmd_selfcheck}.get(a.cmd, lambda: (ap.print_help(), 0)[1])()


if __name__ == "__main__":
    sys.exit(main())
