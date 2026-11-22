# -*- coding: utf-8 -*-
"""
活网 · gitbox —— 触须的 git 信箱（通道层，纯标准库）

把「信箱＝本机目录」换成「信箱＝git 裸仓」：
  · 每个节点一个分支 node/<node_id>，只往自己分支 append 包；
  · 发现层 = git ls-remote --heads（谁在仓里开分支谁就是节点，不靠 fork；
    fork 出来不回流，实测已证伪，所以绝不走 fork）；
  · 水位 = 包序号 seq，只取上次水位之后的新包（增量，不整包重传）；
  · 传输的仍是触须原生产出的脱敏事实包（header + 件×格判定），
    不夹带法律库全文、私技字段、Obsidian 库内容。

接口沿用 tentacle：bundle / absorb / beacon / status。
收到包后仍调 tentacle.py absorb —— 协议校验、异宗判定、伦理守卫、
免疫守卫、去重并账、冲突记账全部复用；gitbox 只替换「包怎么送、怎么拉」。

身份仍不签名：node_id 是随机串，分支名即声明。这不是认证，
只是「把包放到哪条枝上」的寻址方式；真假仍归三层校验器。

依赖：系统 PATH 里有 git（本机实测 2.55.0）。Python 只用标准库。

用法：
  python gitbox.py init      --repo <裸仓路径或URL>
  python gitbox.py bundle
  python gitbox.py absorb                    # 只拉包不投包
  python gitbox.py beacon                    # 投包 + 拉包 + 状态
  python gitbox.py status
  python gitbox.py selfcheck                 # 本机 A/B 裸仓自测，全在临时目录
"""
import os
import sys
import json
import shutil
import argparse
import subprocess
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
TENT = os.path.join(BASE, "tentacle.py")
HOME = os.environ.get("LW_HOME") or BASE
TEN = os.path.join(HOME, "触须")
NODE = os.path.join(TEN, "node.json")
OUT = os.path.join(TEN, "out")
INBOX = os.path.join(TEN, "inbox")
BOX = os.path.join(TEN, "gitbox")
WORK = os.path.join(BOX, "work")
SEQ = os.path.join(BOX, "seq.json")
WATER = os.path.join(BOX, "water.json")
CFG = os.path.join(BOX, "config.json")


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


def git(*args, cwd=WORK, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{(r.stderr or r.stdout).strip()[:300]}")
    return r


def tent(*args):
    env = dict(os.environ, LW_HOME=HOME, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, TENT, *args], cwd=BASE, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def node():
    return jread(NODE)


def ensure_identity():
    n = node()
    if n:
        return n
    r = tent("init", "--rules", "v3")
    if r.returncode != 0:
        raise RuntimeError("建身份失败：" + (r.stderr or r.stdout).strip()[:200])
    return node()


# ---------- 脱敏白名单：推送前只认事实包的字段形状 ----------
ALLOW_HEAD = {"protocol", "node_id", "convention_root", "rules",
              "watermark", "exported_at", "digest"}
BAN_KEYS = ("private_core", "signature", "secret", "token", "privkey",
            "私技", "内核", "密钥", "凭据")


def clean_pack(pack):
    """只检查形状，不判内容真假（真假归三层校验器）。夹带私技字段即拒发。"""
    if not isinstance(pack, dict) or "header" not in pack or "events" not in pack:
        return False, "不是 {header,events} 事实包"
    h = pack["header"]
    if set(h) - ALLOW_HEAD:
        return False, "header 夹带非白名单字段：" + ",".join(sorted(set(h) - ALLOW_HEAD))
    for e in pack["events"]:
        if set(e) - {"key", "v", "layer", "why"}:
            return False, "事件夹带非白名单字段：" + ",".join(sorted(set(e) - {"key", "v", "layer", "why"}))
    blob = json.dumps(pack, ensure_ascii=False)
    for b in BAN_KEYS:
        if b in blob:
            return False, "夹带私技/凭据字样：" + b
    return True, "形状合规（脱敏事实包）"


# ---------- 命令 ----------
def cmd_init(repo):
    n = ensure_identity()
    os.makedirs(WORK, exist_ok=True)
    if not os.path.isdir(os.path.join(WORK, ".git")):
        git("init", "-q")
        git("config", "user.email", "gitbox@local")
        git("config", "user.name", "gitbox")
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", repo)
    jwrite(CFG, {"repo": repo, "node_id": n["node_id"], "at": now()})
    jwrite(SEQ, {"seq": 0})
    jwrite(WATER, {})
    print(f"gitbox 已挂接：{repo}")
    print(f"本节点 {n['node_id'][:12]}｜分支 node/{n['node_id']}")
    return 0


def branches_local(repo=None):
    """ls-remote 列远端所有 node/ 分支——这就是发现层。"""
    cfg = jread(CFG) or {}
    r = git("ls-remote", "--heads", repo or cfg.get("repo", ""), check=False)
    out = []
    for line in (r.stdout or "").splitlines():
        if "\trefs/heads/node/" not in line:
            continue
        out.append(line.split("refs/heads/", 1)[1].strip())
    return sorted(out)


def cmd_bundle():
    cfg = jread(CFG)
    if not cfg:
        print("先 init --repo"); return 2
    n = ensure_identity()
    r = tent("bundle")
    print((r.stdout or r.stderr).strip()[:300])
    if r.returncode != 0:
        return r.returncode
    # 找本节点刚产出的包
    cands = [os.path.join(OUT, f) for f in os.listdir(OUT)
             if f.startswith(n["node_id"] + "-") and f.endswith(".bundle.json")] \
             if os.path.isdir(OUT) else []
    if not cands:
        print("没找到本节点的包"); return 2
    src = max(cands, key=os.path.getmtime)
    pack = jread(src)
    ok, why = clean_pack(pack)
    if not ok:
        print(f"拒发（{why}）——私技/凭据不出本机"); return 3
    seq = (jread(SEQ) or {}).get("seq", 0) + 1
    name = f"{seq:06d}.bundle.json"
    os.makedirs(os.path.join(WORK, "packs"), exist_ok=True)
    shutil.copy2(src, os.path.join(WORK, "packs", name))
    jwrite(SEQ, {"seq": seq})
    br = "node/" + n["node_id"]
    git("checkout", "-q", "-B", br)
    git("add", "packs/" + name)
    git("commit", "-q", "-m", f"bundle {n['node_id'][:8]} seq={seq}")
    git("push", "-q", "origin", f"HEAD:refs/heads/{br}")
    print(f"已投到 {br}：第 {seq} 包｜{why}")
    return 0


def fetch_branches(brs):
    if not brs:
        return
    git("fetch", "-q", "origin", *[f"refs/heads/{b}:refs/remotes/origin/{b}" for b in brs])


def cmd_absorb():
    cfg = jread(CFG)
    if not cfg:
        print("先 init --repo"); return 2
    me = cfg["node_id"]
    brs = [b for b in branches_local() if b != "node/" + me]
    if not brs:
        print("发现层：只有自己一个节点，没有可拉的包")
        return 0
    fetch_branches(brs)
    water = jread(WATER) or {}
    os.makedirs(INBOX, exist_ok=True)
    got = 0
    for br in brs:
        nid = br.split("/", 1)[1]
        ref = "refs/remotes/origin/" + br
        listed = git("ls-tree", "--name-only", ref, "packs/", check=False).stdout.strip()
        files = [x for x in listed.splitlines() if x.endswith(".bundle.json")]
        last = water.get(nid, 0)
        for f in files:
            try:
                seq = int(os.path.basename(f).split(".")[0])
            except ValueError:
                continue
            if seq <= last:
                continue
            body = git("show", f"{ref}:{f}").stdout
            target = os.path.join(INBOX, f"{nid[:8]}-{os.path.basename(f)}")
            with open(target, "w", encoding="utf-8") as fp:
                fp.write(body)
            ok, why = clean_pack(jread(target) or {})
            if not ok:
                print(f"  拒收 {nid[:8]} 第{seq}包（{why}）"); continue
            r = tent("absorb", "--bundle", target)
            print((r.stdout or r.stderr).strip()[:240])
            got += 1
            water[nid] = seq
    jwrite(WATER, water)
    print(f"本轮拉进 {got} 包｜发现节点 {len(brs) + 1}（含本机）")
    return 0


def cmd_status():
    cfg = jread(CFG) or {}
    if not cfg.get("repo"):
        print("未配置信箱、尚未发现节点（先跑 init --repo <信箱>）")
        return 0
    brs = branches_local()
    n = node() or {}
    fed = os.path.join(TEN, "联邦账.jsonl")
    rows = 0
    if os.path.exists(fed):
        with open(fed, encoding="utf-8") as f:
            rows = sum(1 for x in f if x.strip())
    print(f"gitbox 发现节点：{len(brs)}｜分支：" + (", ".join(b.split('/')[1][:8] for b in brs) or "无"))
    print(f"本机 {n.get('node_id','?')[:12]}｜联邦账 {rows} 条")
    return 0


def cmd_beacon():
    cmd_bundle()
    cmd_absorb()
    return tent_status()


def tent_status():
    r = tent("status")
    out = (r.stdout or "").strip()
    print(out[-600:] if out else (r.stderr or "")[:400])
    return 0


def _rmtree_force(p):
    def onerr(fn, path, exc):
        try:
            os.chmod(path, 0o700)
            fn(path)
        except Exception:
            pass
    shutil.rmtree(p, onerror=onerr) if os.path.isdir(p) else None


def cmd_selfcheck():
    tmp = tempfile.mkdtemp(prefix="gitbox_")
    try:
        hub = os.path.join(tmp, "hub.git")
        subprocess.run(["git", "init", "--bare", "-q", hub], check=True)
        homes = {}
        for who in ("A", "B"):
            h = os.path.join(tmp, who)
            os.makedirs(h)
            homes[who] = h
            env = dict(os.environ, LW_HOME=h, PYTHONIOENCODING="utf-8")
            subprocess.run([sys.executable, TENT, "init", "--rules", "v3"],
                           cwd=BASE, env=env, capture_output=True, text=True, encoding="utf-8")
            subprocess.run([sys.executable, __file__, "init", "--repo", hub],
                           cwd=BASE, env=env, capture_output=True, text=True, encoding="utf-8")
        def gb(who, *a):
            env = dict(os.environ, LW_HOME=homes[who], PYTHONIOENCODING="utf-8")
            return subprocess.run([sys.executable, __file__, *a], cwd=BASE, env=env,
                                  capture_output=True, text=True, encoding="utf-8")
        print("=== A、B 各投一包 ===")
        for who in ("A", "B"):
            r = gb(who, "bundle")
            print(f"  {who} bundle: 退出 {r.returncode}｜{(r.stdout or r.stderr).strip().splitlines()[-1:]}")
        print("=== A 拉包（应见节点2｜联邦45）===")
        r = gb("A", "beacon")
        out = r.stdout or ""
        key = [x.strip() for x in out.splitlines() if "节点" in x or "联邦事件" in x or "拉进" in x]
        for x in key[-5:]:
            print("  " + x)
        ok2 = any("发现节点 2" in x or "节点 2" in x for x in key)
        ok45 = any("联邦事件：45" in x for x in key)
        print(f"自检：{'通过' if (ok2 and ok45) else '未达标'}（节点2={ok2}｜联邦45={ok45}）")
        return 0 if (ok2 and ok45) else 1
    finally:
        _rmtree_force(tmp)


def main():
    ap = argparse.ArgumentParser(description="触须 git 信箱")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init"); p.add_argument("--repo", required=True)
    sub.add_parser("bundle"); sub.add_parser("absorb")
    sub.add_parser("beacon"); sub.add_parser("status"); sub.add_parser("selfcheck")
    a = ap.parse_args()
    if a.cmd == "init":
        return cmd_init(a.repo)
    if a.cmd == "bundle":
        return cmd_bundle()
    if a.cmd == "absorb":
        return cmd_absorb()
    if a.cmd == "beacon":
        return cmd_beacon()
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "selfcheck":
        return cmd_selfcheck()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
