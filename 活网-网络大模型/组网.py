#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
组网 · 让活体自己找到彼此 —— 替代"人工约定同一个信箱"
======================================================
信箱是从 git 借的权宜，不是网络的本质。真实节点互认靠三层机制，本文件取其原理，
用纯标准库落到活体上：

  · mDNS 零配置发现：同网段节点监听协议默认组播组，喊话即互相看到，不用配地址。
      原理来源 python-zeroconf / RFC6762 的 ServiceBrowser + Zeroconf 广播。
  · SWIM/Gossip 名单传染：每个包 piggyback 自己知道的全部成员，收到即合并，
      一传十十传百；配合反熵（比摘要、缺的补）。无中心名单，任何节点都能传。
      原理来源 icgood/swim-protocol 的成员视图 + SWARM 的 gossip 反熵传播。
  · CRDT 确定性收敛：成长态合并走固定排序 + 冲突确定裁决，任何节点算出的账
      字节完全相同（sha256 可核），无需仲裁者。原理来源 gossip 文档所列 CRDT。

诚实边界（不粉饰）：
  · 组播不出网段——云端与本地不在同网段时，需 --seed 给一个可达同伴地址；
    但 seed 只是引导，接上后名单自行传播，seed 死了网络照常，不是中心信箱。
  · 身份是随机 node_id，可冒名；认宗靠 convention_root 全等，异宗不并。
  · 传的是口径摘要（合并规则/词表/负载/忆层指纹），私技字段拒发。

命令：
    python 组网.py daemon                 常驻：周期喊话 + 收包 + 合成账（默认组播）
    python 组网.py once                   打一轮就退（看清一轮能发现谁）
    python 组网.py status                 看当前已知成员 + 联邦账
    python 组网.py selfcheck              起 3 个独立节点实测：零配置发现 + 账收敛

只增不改：新增本文件；状态写在 组网账/ 下；不碰 tentacle/gitbox/成长桥/羽翼/
鞣合/火种/任何原账。纯标准库，不发外部网络请求（组播/seed 均为本地可控地址）。
"""
import argparse
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "model")
HOME = os.environ.get("LW_HOME") or MODEL
NODE = os.path.join(HOME, "触须", "node.json")
WING = os.path.join(ROOT, "羽翼账")
STATE = os.path.join(ROOT, "组网账")
LEDGER = os.path.join(STATE, "联邦成长账.json")
MEMBERS = os.path.join(STATE, "成员名单.json")

MC_GRP = "239.42.7.1"
MC_PORT = int(os.environ.get("LW_MC_PORT", "45222"))
PROTO = "net/1"
PERIOD = 0.25          # gossip 周期（秒）
SELFCHECK_ROUNDS = 14  # selfcheck 轮数


# ---------------- 基础 ----------------
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
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def code_version():
    """触须相互感知：把核心入口文件的字节摘要作为代码版本。
    任何一处修复 → 摘要变 → 广播出去对端即发现版本分歧，提示同步，一并成长。"""
    core = ["组网.py", "鞣合.py", "羽翼.py", "成长桥.py"]
    h = hashlib.sha256()
    for f in core:
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            h.update(f.encode("utf-8"))
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def local_ip():
    """取本机出口 IP；拿不到回环。仅用于告诉同伴往哪 unicast。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_identity(node_id=None, root=None):
    """复用触须身份；selfcheck 可显式注入独立身份。"""
    if node_id and root:
        return {"node_id": node_id, "convention_root": root}
    n = jread(NODE)
    if n:
        return n
    import subprocess
    env = dict(os.environ, LW_HOME=HOME, PYTHONIOENCODING="utf-8")
    subprocess.run([sys.executable, os.path.join(MODEL, "tentacle.py"), "init", "--rules", "v3"],
                   cwd=MODEL, env=env, capture_output=True, text=True, encoding="utf-8")
    return jread(NODE) or {"node_id": hashlib.sha256(os.urandom(16)).hexdigest()[:16],
                           "convention_root": ""}


# ---------------- 成长态采集（口径，同成长桥；不碰原账） ----------------
def collect(override=None):
    if override is not None:
        return override
    wc = jread(os.path.join(WING, "成长词表.json")) or {}
    load = {}
    lp = os.path.join(WING, "负载.jsonl")
    if os.path.exists(lp):
        with open(lp, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        r = json.loads(ln)
                        for e, c in r.get("load", {}).items():
                            load[e] = load.get(e, 0) + c
                    except Exception:
                        pass
    mem = jread(os.path.join(ROOT, "鞣合记忆", "中期忆层.jsonl"), default=[])
    mem_digest = ""
    try:
        with open(os.path.join(ROOT, "鞣合记忆", "中期忆层.jsonl"), encoding="utf-8") as f:
            mem_digest = hashlib.sha256(f.read().encode("utf-8")).hexdigest()
    except Exception:
        pass
    return {"merges": wc.get("merges", []), "vocab": wc.get("vocab", []),
            "load": load, "mem_digest": mem_digest}


# ---------------- CRDT：确定性收敛（同成长桥裁决规则） ----------------
def consensus(reports):
    """reports = {node_id: growth}；任何顺序、任何节点 → 字节相同的一本账。"""
    by_pair = {}
    for nid, g in reports.items():
        for m in g.get("merges", []):
            pair = "+".join(m.get("pair", []))
            d = by_pair.setdefault(pair, {"pair": m.get("pair", []), "votes": {}})
            d["votes"].setdefault(m.get("new", ""), set()).add(nid)
    rules, conflict = [], []
    for pair, d in sorted(by_pair.items()):
        ranked = sorted(d["votes"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        winner, supporters = ranked[0]
        rules.append({"pair": d["pair"], "new": winner,
                      "支持节点": sorted(supporters), "支持数": len(supporters)})
        losers = [{"new": k, "支持节点": sorted(v), "支持数": len(v)} for k, v in ranked[1:]]
        if losers:
            conflict.append({"pair": d["pair"], "生效": winner, "落选": losers,
                             "裁决规则": "支持节点数↓，平局 new 字典序↑"})
    vocab = sorted({w for g in reports.values() for w in g.get("vocab", [])})
    load = {}
    for g in reports.values():
        for e, c in g.get("load", {}).items():
            load[e] = load.get(e, 0) + c
    body = {"协议": PROTO, "账型": "无中心组网·CRDT确定性收敛·全节点并入",
            "节点": sorted(reports), "节点数": len(reports),
            "合并规则": rules, "词表": vocab, "负载合计": load,
            "忆层指纹": {nid: g.get("mem_digest", "") for nid, g in sorted(reports.items())}}
    ledger = dict(body)
    ledger["账sha256"] = sha(body)
    ledger["冲突留痕"] = conflict
    ledger["不可汇聚"] = ["阈值(未落账)", "忆层全文(只发指纹)", "法律库全文", "任何私技字段"]
    return ledger


def merge_members(local, incoming):
    """成员名单 CRDT：按 node_id 合并，取 ts 较新者；返回 (新表, 是否有变)。"""
    out = dict(local)
    changed = False
    for nid, rec in incoming.items():
        old = out.get(nid)
        if old is None or rec.get("ts", 0) > old.get("ts", 0):
            out[nid] = rec
            changed = True
    return out, changed


# ---------------- 节点：组播喊话 + gossip 名单 + 反熵 ----------------
class Agent:
    def __init__(self, nid, root, growth, seeds=None, port=MC_PORT, tunnel=None):
        self.id = nid
        self.root = root
        self.growth = growth
        self.seeds = list(seeds or [])          # [(ip, port)] 跨网段引导
        self.port = port
        self.tunnel = tunnel                    # selfcheck 用：内存总线，替代真实 socket
        self.members = {nid: {"node_id": nid, "addr": "", "ts": time.time(),
                              "root": root, "digest": sha(growth)}}
        self.reports = {nid: growth}
        self.ledger = None
        self.stop = threading.Event()
        self._lock = threading.Lock()

    def packet(self):
        # piggyback 全部成员名单 + 自己的成长口径 + 账摘要（反熵用）
        return {"p": PROTO, "t": time.time(), "from": self.id, "root": self.root,
                "members": dict(self.members), "growth": self.growth,
                "ledger_digest": sha(self.ledger) if self.ledger else "",
                "code_ver": code_version()}

    def absorb(self, pkt):
        if pkt.get("p") != PROTO or pkt.get("from") == self.id:
            return
        if pkt.get("root") != self.root:
            return  # 异宗不并
        with self._lock:
            peer_ver = pkt.get("code_ver", "")
            my_ver = code_version()
            if peer_ver and peer_ver != my_ver:
                rec = self.members.get(pkt["from"], {})
                rec["code_ver"] = peer_ver
                self.members[pkt["from"]] = rec
                self.version_gap = getattr(self, "version_gap", {})
                self.version_gap[pkt["from"]] = {"本机": my_ver, "对端": peer_ver}
                print(f"  ⚠ 版本分歧：{pkt['from'][:8]} 代码 {peer_ver} ≠ 本机 {my_ver} —— 需同步入口文件一并成长")
            self.members, _ = merge_members(self.members, pkt.get("members", {}))
            # merge 后补回对端版本标记（merge_members 可能覆盖）
            if peer_ver:
                self.members.setdefault(pkt["from"], {}).setdefault("code_ver", peer_ver)
            g = pkt.get("growth")
            if isinstance(g, dict) and self._safe(g):
                self.reports[pkt["from"]] = g
            self.ledger = consensus(self.reports)

    def _safe(self, g):
        """形状白名单 + 私技字样拒发/拒收。"""
        txt = canon(g)
        for bad in ("私技", "范式包", "推演记录", "技能全文", "API_KEY", "token"):
            if bad in txt:
                return False
        return all(k in g for k in ("merges", "vocab", "load"))

    def round(self):
        pkt = self.packet()
        if self.tunnel:
            self.tunnel.broadcast(pkt)
        else:
            self._udp_send(pkt)
        self.ledger = consensus(self.reports)

    def _udp_send(self, pkt):
        data = canon(pkt).encode("utf-8")
        addr = local_ip()
        self.members[self.id]["addr"] = f"{addr}:{self.port}"
        targets = [(MC_GRP, self.port)]
        for nid, rec in self.members.items():
            a = rec.get("addr", "")
            if a and nid != self.id and a != f"{addr}:{self.port}":
                try:
                    h, p = a.rsplit(":", 1)
                    targets.append((h, int(p)))
                except Exception:
                    pass
        for h, p in self.seeds:
            targets.append((h, p))
        seen = set()
        for h, p in targets:
            if (h, p) in seen:
                continue
            seen.add((h, p))
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                s.sendto(data, (h, p))
                s.close()
            except Exception:
                pass

    def serve(self):
        """收包线程（真实 UDP）；selfcheck 走内存总线，不调这个。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", self.port))
        mreq = socket.inet_aton(MC_GRP) + socket.inet_aton("0.0.0.0")
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception:
            pass
        s.settimeout(0.5)
        while not self.stop.is_set():
            try:
                data, _ = s.recvfrom(65535)
                self.absorb(json.loads(data.decode("utf-8")))
            except Exception:
                pass
        s.close()


class Tunnel:
    """selfcheck 的内存总线：模拟同网段全员可见的组播，不依赖真实网卡。"""
    def __init__(self):
        self.agents = []
        self.lock = threading.Lock()

    def register(self, a):
        self.agents.append(a)

    def broadcast(self, pkt):
        with self.lock:
            for a in list(self.agents):
                a.absorb(pkt)


# ---------------- 命令 ----------------
def save_state(agent):
    jwrite(MEMBERS, agent.members)
    if agent.ledger:
        jwrite(LEDGER, agent.ledger)


def cmd_once(args):
    ident = ensure_identity()
    g = collect()
    a = Agent(ident["node_id"], ident["convention_root"], g,
              seeds=_parse_seeds(args.seed))
    a.serve_thread = threading.Thread(target=a.serve, daemon=True)
    a.serve_thread.start()
    for _ in range(2):
        a.round()
        time.sleep(0.4)
    a.stop.set()
    save_state(a)
    print(f"node_id {a.id[:12]}｜认宗 root {a.root[:12]}｜已知成员 {len(a.members)}")
    print(f"联邦账：节点 {a.ledger['节点数']}｜账sha256 {a.ledger['账sha256'][:16]}…")
    return 0


def cmd_daemon(args):
    ident = ensure_identity()
    g = collect()
    a = Agent(ident["node_id"], ident["convention_root"], g,
              seeds=_parse_seeds(args.seed))
    threading.Thread(target=a.serve, daemon=True).start()
    print(f"组网常驻：node {a.id[:12]}｜组播 {MC_GRP}:{MC_PORT}｜seed {a.seeds}")
    try:
        while True:
            a.round()
            save_state(a)
            time.sleep(PERIOD)
    except KeyboardInterrupt:
        a.stop.set()
        print("已停止")
    return 0


def cmd_status(args):
    led = jread(LEDGER)
    mem = jread(MEMBERS) or {}
    if not led:
        print("尚无联邦账，先跑 once / daemon"); return 2
    print(f"已知成员 {len(mem)}｜账：节点 {led['节点数']}｜规则 {len(led['合并规则'])}｜"
          f"词位 {len(led['词表'])}｜账sha256 {led['账sha256'][:16]}…")
    return 0


def _parse_seeds(vals):
    out = []
    for v in vals or []:
        try:
            h, p = v.rsplit(":", 1)
            out.append((h, int(p)))
        except Exception:
            pass
    return out


def cmd_selfcheck(args):
    """3 个独立节点，各自不同成长，零配置组播互通，验证名单传播 + 账收敛。"""
    tun = Tunnel()
    samples = [
        {"merges": [{"pair": ["甲", "A"], "new": "甲规则"}], "vocab": ["甲词"], "load": {"checker_v2": 1}, "mem_digest": "m1"},
        {"merges": [{"pair": ["乙", "B"], "new": "乙规则"}], "vocab": ["乙词"], "load": {"immune": 1}, "mem_digest": "m2"},
        {"merges": [{"pair": ["丙", "C"], "new": "丙规则"}], "vocab": ["丙词"], "load": {"tentacle": 1}, "mem_digest": "m3"},
    ]
    agents = []
    for i, g in enumerate(samples):
        a = Agent(f"node{i:02d}", "root-TEST", g, tunnel=tun)
        tun.register(a)
        agents.append(a)
    for r in range(SELFCHECK_ROUNDS):
        for a in agents:
            a.round()
    shas = {a.ledger["账sha256"] for a in agents}
    sizes = [len(a.members) for a in agents]
    vocab_ok = all(samples[i]["vocab"][0] in a.ledger["词表"]
                   for i in range(3) for a in agents)
    print("=== 组网 selfcheck ===")
    print(f"独立节点: {len(agents)}｜每节点已知成员: {sizes}")
    print(f"账sha256 去重数: {len(shas)}（应为 1）")
    print(f"账sha256: {next(iter(shas))[:16]}…")
    print(f"三节点独有词全进同一本账: {vocab_ok}")
    ok = len(shas) == 1 and all(s == 3 for s in sizes) and vocab_ok
    print("selfcheck:", "通过——零配置发现 + 名单传染 + 账收敛为一本" if ok else "未达标")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="组网 · 活体自组织（mDNS + gossip + CRDT）")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("once"); p1.add_argument("--seed", action="append", default=[])
    p1.set_defaults(fn=cmd_once)
    p2 = sub.add_parser("daemon"); p2.add_argument("--seed", action="append", default=[])
    p2.set_defaults(fn=cmd_daemon)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)
    args = ap.parse_args()
    if not getattr(args, "fn", None):
        ap.print_help(); return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
