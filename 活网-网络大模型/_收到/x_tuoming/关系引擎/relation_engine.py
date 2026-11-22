#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段二 · 关系引擎（Relation Engine）
==================================
世界建模语言层。所有资源调度、勘比推演，先把客观情形翻译成「实体 + 关系边」，
再送入貔貅闭环。没有这一层，引擎只能算算力数字，看不懂背后的利益倾斜。

三条设计纪律：
  1. 零模型依赖。本层只用 sqlite3 + 标准库，不调任何 LLM——关系抽取可换人、可换模型，
     但关系一旦落库，其语义与约束必须是确定的。
  2. 写入即校验。任何边不符合该关系类型的约束，就在写库前拒掉，不静默放行、不留脏数据。
  3. 只存指针不存正文。evidence 字段只写材料出处（文件+页码/条款号），不把原文吞进图谱。

约束是「数据驱动」的：18 种关系及其约束写在 rules/relations.default.json，
换一套关系体系只改 JSON，约束执行器不动。所以这里不硬编码任何具体法域。

用法：
  python3 relation_engine.py init       --db data/graph.db
  python3 relation_engine.py init-types --db data/graph.db [--types rules/relations.default.json]
  python3 relation_engine.py add-entity --db data/graph.db --id E1 --kind 法人 --label "某某公司"
  python3 relation_engine.py add-edge   --db data/graph.db --src E1 --dst E2 --rtype ownership --weight 0.6 --evidence "材料A p12"
  python3 relation_engine.py types      --db data/graph.db
  python3 relation_engine.py show       --db data/graph.db --entity E1
  python3 relation_engine.py path       --db data/graph.db --src E1 --dst E3
  python3 relation_engine.py check      --db data/graph.db
  python3 relation_engine.py stats      --db data/graph.db
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import deque
from datetime import datetime, timezone

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    attrs       TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation_type (
    code        TEXT PRIMARY KEY,
    zh          TEXT NOT NULL,
    semantics   TEXT NOT NULL,
    directed    INTEGER NOT NULL DEFAULT 1,
    inverse     TEXT,
    constraints TEXT NOT NULL DEFAULT '[]',
    note        TEXT
);

CREATE TABLE IF NOT EXISTS edge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    src         TEXT NOT NULL REFERENCES entity(id),
    dst         TEXT NOT NULL REFERENCES entity(id),
    rtype       TEXT NOT NULL REFERENCES relation_type(code),
    weight      REAL,
    evidence    TEXT,
    valid_from  TEXT,
    valid_to    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edge_src ON edge(src, rtype);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst, rtype);

CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL
);
"""

ALLOWED_KINDS = ("自然人", "法人", "非法人组织", "公共主体", "资产", "资源", "任务", "节点", "其他")


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Rejected(Exception):
    """约束不通过。写入被拒，事务回滚，磁盘不留痕。"""


class Engine:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------ 建库
    def init_schema(self):
        self.conn.executescript(SCHEMA)
        self._audit("init_schema", self.db_path)

    def load_types(self, types_path):
        with open(types_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        rows = doc["relations"]
        self.conn.execute("BEGIN")
        try:
            for r in rows:
                self.conn.execute(
                    "INSERT OR REPLACE INTO relation_type(code,zh,semantics,directed,inverse,constraints,note)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (r["code"], r["zh"], r["semantics"], 1 if r.get("directed", True) else 0,
                     r.get("inverse"), json.dumps(r.get("constraints", []), ensure_ascii=False),
                     doc.get("_meta", {}).get("note"))
                )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self._audit("init_types", f"{len(rows)} 类关系已注册")

    # ------------------------------------------------------------ 实体
    def add_entity(self, eid, kind, label, attrs=None):
        if kind not in ALLOWED_KINDS:
            raise Rejected(f"实体类别非法：{kind}（允许：{'/'.join(ALLOWED_KINDS)}）")
        if not eid or not label:
            raise Rejected("实体 id 与 label 不得为空")
        attrs = attrs or {}
        try:
            self.conn.execute(
                "INSERT INTO entity(id,kind,label,attrs,created_at) VALUES(?,?,?,?,?)",
                (eid, kind, label, json.dumps(attrs, ensure_ascii=False), now()))
        except sqlite3.IntegrityError:
            raise Rejected(f"实体 {eid} 已存在（不覆盖，改名或换 id）")
        self._audit("add_entity", f"{eid} / {kind} / {label}")

    # ------------------------------------------------------------ 关系类型
    def rtype(self, code):
        row = self.conn.execute("SELECT * FROM relation_type WHERE code=?", (code,)).fetchone()
        if not row:
            raise Rejected(f"关系类型未注册：{code}（先跑 init-types）")
        return row

    def _constraints_of(self, code):
        return json.loads(self.rtype(code)["constraints"])

    # ------------------------------------------------------------ 边
    def add_edge(self, src, dst, rtype, weight=None, evidence=None,
                 valid_from=None, valid_to=None):
        """写入前跑全部约束；任一不过则抛 Rejected，磁盘无痕。"""
        if not self._entity_exists(src):
            raise Rejected(f"源实体不存在：{src}")
        if not self._entity_exists(dst):
            raise Rejected(f"目标实体不存在：{dst}")
        if src == dst:
            raise Rejected("禁止自环：src 与 dst 不得为同一实体")
        self.rtype(rtype)  # 类型必须已注册

        self.conn.execute("BEGIN")
        try:
            self._check_constraints(src, dst, rtype, weight)
            self.conn.execute(
                "INSERT INTO edge(src,dst,rtype,weight,evidence,valid_from,valid_to,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (src, dst, rtype, weight, evidence, valid_from, valid_to, now()))
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        self._audit("add_edge", f"{src} -[{rtype}]-> {dst} w={weight} ev={evidence}")
        return True

    def _entity_exists(self, eid):
        return self.conn.execute("SELECT 1 FROM entity WHERE id=?", (eid,)).fetchone() is not None

    def _active_edges(self, where_sql, params):
        """有效边：valid_to 为空或晚于当前时刻。"""
        return self.conn.execute(
            f"SELECT * FROM edge WHERE {where_sql} AND (valid_to IS NULL OR valid_to > ?)",
            (*params, now())).fetchall()

    # ------------------------------------------------------------ 约束执行器
    def _check_constraints(self, src, dst, rtype, weight):
        for c in self._constraints_of(rtype):
            t = c.get("type")
            if t == "unique_incoming":
                self._c_unique_incoming(src, dst, rtype, weight, c.get("unless_weight", False))
            elif t == "unique_outgoing":
                self._c_unique_outgoing(src, dst, rtype, weight, c.get("unless_weight", False))
            elif t == "acyclic":
                self._c_acyclic(src, dst, rtype)
            elif t == "requires":
                self._c_requires(src, dst, c["with"], c.get("same_pair", True))
            else:
                raise Rejected(f"未知约束类型：{t}（引擎拒绝在未知规则下放行）")

    def _c_unique_incoming(self, src, dst, rtype, weight, unless_weight):
        exist = self._active_edges("dst=? AND rtype=?", (dst, rtype))
        if not exist:
            return
        if unless_weight and weight is not None:
            # 份额分配：允许多条带 weight 的边，但不得与“独占无份额”边并存
            if any(e["weight"] is None for e in exist):
                raise Rejected(f"冲突：{dst} 的「{rtype}」已有一条独占边（无份额），不能再叠加份额")
            return
        if unless_weight and weight is None:
            raise Rejected(f"冲突：{dst} 的「{rtype}」已有 {len(exist)} 条记录，独占边不可再加")
        raise Rejected(f"冲突：{dst} 的「{rtype}」按约束只能有一条（现有 {len(exist)} 条）")

    def _c_unique_outgoing(self, src, dst, rtype, weight, unless_weight):
        exist = self._active_edges("src=? AND rtype=?", (src, rtype))
        if not exist:
            return
        if unless_weight and weight is not None:
            if any(e["weight"] is None for e in exist):
                raise Rejected(f"冲突：{src} 的「{rtype}」已有一条独占边（无份额）")
            return
        raise Rejected(f"冲突：{src} 的「{rtype}」按约束只能有一条（现有 {len(exist)} 条）")

    def _c_acyclic(self, src, dst, rtype):
        """从 dst 沿该类型正向能否回到 src；能回到即成环。"""
        seen = {dst}
        q = deque([dst])
        while q:
            cur = q.popleft()
            for e in self._active_edges("src=? AND rtype=?", (cur, rtype)):
                nxt = e["dst"]
                if nxt == src:
                    raise Rejected(f"成环：{src} -[{rtype}]-> {dst} 会与既有链路构成闭环（{rtype} 不允许环）")
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)

    def _c_requires(self, src, dst, required_type, same_pair):
        self.rtype(required_type)
        if same_pair:
            ok = self._active_edges("src=? AND dst=? AND rtype=?", (src, dst, required_type))
            if not ok:
                raise Rejected(f"前置关系缺失：加「{required_type}」要求的对应边（{src} → {dst}）不存在")
        else:
            ok = self._active_edges("src=? AND rtype=?", (src, required_type))
            if not ok:
                raise Rejected(f"前置关系缺失：{src} 缺少任意「{required_type}」")

    # ------------------------------------------------------------ 查询
    def neighbors(self, eid, rtype=None, direction="both"):
        out = []
        if direction in ("out", "both"):
            cond = "src=?" + (" AND rtype=?" if rtype else "")
            params = (eid, rtype) if rtype else (eid,)
            for e in self._active_edges(cond, params):
                out.append({"dir": "→", "peer": e["dst"], "rtype": e["rtype"],
                            "weight": e["weight"], "evidence": e["evidence"]})
        if direction in ("in", "both"):
            cond = "dst=?" + (" AND rtype=?" if rtype else "")
            params = (eid, rtype) if rtype else (eid,)
            for e in self._active_edges(cond, params):
                out.append({"dir": "←", "peer": e["src"], "rtype": e["rtype"],
                            "weight": e["weight"], "evidence": e["evidence"]})
        return out

    def path(self, src, dst, max_depth=6):
        """BFS 最短关系链，返回边序列；无路返回 None。"""
        if src == dst:
            return []
        prev = {src: None}
        q = deque([(src, 0)])
        while q:
            cur, d = q.popleft()
            if d >= max_depth:
                continue
            for e in self._active_edges("src=?", (cur,)):
                nxt = e["dst"]
                if nxt in prev:
                    continue
                prev[nxt] = (cur, e)
                if nxt == dst:
                    steps, node = [], dst
                    while prev[node] is not None:
                        pnode, edge = prev[node]
                        steps.append({"from": pnode, "to": node, "rtype": edge["rtype"],
                                      "evidence": edge["evidence"]})
                        node = pnode
                    return list(reversed(steps))
                q.append((nxt, d + 1))
        return None

    def violations(self):
        """全库复检：把已有边重新跑一遍约束，抓出绕过 API 写进来的历史脏数据。"""
        problems = []
        edges = self.conn.execute("SELECT * FROM edge ORDER BY id").fetchall()
        for e in edges:
            for c in self._constraints_of(e["rtype"]):
                t = c.get("type")
                try:
                    if t == "unique_incoming" and c.get("unless_weight", False):
                        peers = [x for x in self._active_edges("dst=? AND rtype=?", (e["dst"], e["rtype"]))
                                 if x["id"] != e["id"]]
                        if e["weight"] is None and peers:
                            problems.append(f"edge#{e['id']} {e['src']}→{e['dst']}[{e['rtype']}] "
                                            f"独占边重复（目标侧已有其他 {len(peers)} 条）")
                        if e["weight"] is not None and any(p["weight"] is None for p in peers):
                            problems.append(f"edge#{e['id']} {e['src']}→{e['dst']}[{e['rtype']}] 份额边与独占边并存")
                    elif t == "acyclic":
                        if self._cycle_exists(e["rtype"]):
                            problems.append(f"edge#{e['id']} [{e['rtype']}] 存在环")
                    elif t == "requires":
                        if not self._active_edges("src=? AND dst=? AND rtype=?",
                                                  (e["src"], e["dst"], c["with"])):
                            problems.append(f"edge#{e['id']} 缺前置「{c['with']}」（{e['src']}→{e['dst']}）")
                except sqlite3.Error as err:
                    problems.append(f"edge#{e['id']} 复检出错：{err}")
        # 去重（同一环会被多条边重复报）
        seen, uniq = set(), []
        for p in problems:
            key = p.split(" ", 1)[-1]
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        return uniq

    def _cycle_exists(self, rtype):
        edges = self._active_edges("rtype=?", (rtype,))
        adj = {}
        for e in edges:
            adj.setdefault(e["src"], []).append(e["dst"])
        color = {}   # 0 未访问 1 在栈中 2 完成

        def dfs(u):
            color[u] = 1
            for v in adj.get(u, []):
                if color.get(v, 0) == 1:
                    return True
                if color.get(v, 0) == 0 and dfs(v):
                    return True
            color[u] = 2
            return False

        for u in list(adj):
            if color.get(u, 0) == 0 and dfs(u):
                return True
        return False

    # ------------------------------------------------------------ 辅助
    def _audit(self, action, detail):
        self.conn.execute("INSERT INTO audit(at,action,detail) VALUES(?,?,?)", (now(), action, detail))

    def stats(self):
        ent = self.conn.execute("SELECT COUNT(*) c FROM entity").fetchone()["c"]
        edg = self.conn.execute("SELECT COUNT(*) c FROM edge").fetchone()["c"]
        typ = self.conn.execute("SELECT COUNT(*) c FROM relation_type").fetchone()["c"]
        by_type = self.conn.execute(
            "SELECT rtype, COUNT(*) c FROM edge GROUP BY rtype ORDER BY c DESC").fetchall()
        return {"entities": ent, "edges": edg, "types": typ,
                "by_type": [{"rtype": r["rtype"], "count": r["c"]} for r in by_type]}

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------- CLI
def _eng(args):
    if not os.path.exists(args.db):
        raise SystemExit(f"库不存在：{args.db}（先跑 init）")
    return Engine(args.db)


def cmd_init(a):
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    e = Engine(a.db)
    e.init_schema()
    print(f"库已建：{a.db}")
    e.close()


def cmd_init_types(a):
    e = _eng(a)
    e.load_types(a.types)
    print(f"关系类型已注册：{a.types}")
    print(f"当前类型总数：{e.stats()['types']}")
    e.close()


def cmd_add_entity(a):
    e = _eng(a)
    try:
        e.add_entity(a.id, a.kind, a.label, json.loads(a.attrs) if a.attrs else None)
        print(f"实体已入库：{a.id} / {a.kind} / {a.label}")
    except Rejected as r:
        print(f"拒绝：{r}")
        return 2
    finally:
        e.close()
    return 0


def cmd_add_edge(a):
    e = _eng(a)
    try:
        e.add_edge(a.src, a.dst, a.rtype, a.weight, a.evidence, a.valid_from, a.valid_to)
        print(f"边已入库：{a.src} -[{a.rtype}]-> {a.dst}"
              + (f"  份额={a.weight}" if a.weight is not None else "")
              + (f"  依据={a.evidence}" if a.evidence else ""))
    except Rejected as r:
        print(f"拒绝（约束不通过）：{r}")
        return 2
    finally:
        e.close()
    return 0


def cmd_types(a):
    e = _eng(a)
    rows = e.conn.execute("SELECT * FROM relation_type ORDER BY code").fetchall()
    print(f"{len(rows)} 类关系：")
    for r in rows:
        cons = json.loads(r["constraints"])
        cs = "；".join(_fmt_constraint(c) for c in cons) if cons else "无附加约束"
        print(f"  {r['code']:<16} {r['zh']:<6} {cs}")
    e.close()


def _fmt_constraint(c):
    t = c.get("type")
    if t == "unique_incoming":
        return "目标侧唯一" + ("(允许份额)" if c.get("unless_weight") else "")
    if t == "unique_outgoing":
        return "源侧唯一" + ("(允许份额)" if c.get("unless_weight") else "")
    if t == "acyclic":
        return "不得成环"
    if t == "requires":
        return f"须伴随「{c.get('with')}」"
    return str(t)


def cmd_show(a):
    e = _eng(a)
    row = e.conn.execute("SELECT * FROM entity WHERE id=?", (a.entity,)).fetchone()
    if not row:
        print(f"实体不存在：{a.entity}")
        e.close()
        return 4
    print(f"{row['id']}  [{row['kind']}]  {row['label']}")
    if row["attrs"] and row["attrs"] != "{}":
        print(f"  属性：{row['attrs']}")
    nb = e.neighbors(a.entity)
    if not nb:
        print("  （无关系边）")
    for n in nb:
        w = f" w={n['weight']}" if n["weight"] is not None else ""
        ev = f"  ←{n['evidence']}" if n["evidence"] else ""
        print(f"  {n['dir']} {n['peer']:<10} [{n['rtype']}]{w}{ev}")
    e.close()
    return 0


def cmd_path(a):
    e = _eng(a)
    steps = e.path(a.src, a.dst, a.max_depth)
    if steps is None:
        print(f"无边连通路径：{a.src} ✗→ {a.dst}（最大深度 {a.max_depth}）")
        e.close()
        return 1
    print(f"{a.src} → {a.dst}  共 {len(steps)} 跳：")
    for i, s in enumerate(steps, 1):
        ev = f"  ←{s['evidence']}" if s["evidence"] else ""
        print(f"  {i}. {s['from']} -[{s['rtype']}]-> {s['to']}{ev}")
    e.close()
    return 0


def cmd_check(a):
    e = _eng(a)
    probs = e.violations()
    if not probs:
        print("不变量复检：✓ 全部通过，未发现脏边")
        code = 0
    else:
        print(f"不变量复检：✗ 发现 {len(probs)} 处问题")
        for p in probs:
            print("  - " + p)
        code = 2
    e.close()
    return code


def cmd_stats(a):
    e = _eng(a)
    print(json.dumps(e.stats(), ensure_ascii=False, indent=2))
    e.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description="阶段二 · 关系引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_db(p):
        p.add_argument("--db", required=True)

    p = sub.add_parser("init"); with_db(p)
    p = sub.add_parser("init-types"); with_db(p)
    p.add_argument("--types", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "rules", "relations.default.json"))
    p = sub.add_parser("add-entity"); with_db(p)
    p.add_argument("--id", required=True); p.add_argument("--kind", required=True)
    p.add_argument("--label", required=True); p.add_argument("--attrs")

    p = sub.add_parser("add-edge"); with_db(p)
    p.add_argument("--src", required=True); p.add_argument("--dst", required=True)
    p.add_argument("--rtype", required=True); p.add_argument("--weight", type=float)
    p.add_argument("--evidence"); p.add_argument("--valid-from"); p.add_argument("--valid-to")

    p = sub.add_parser("types"); with_db(p)
    p = sub.add_parser("show"); with_db(p); p.add_argument("--entity", required=True)
    p = sub.add_parser("path"); with_db(p)
    p.add_argument("--src", required=True); p.add_argument("--dst", required=True)
    p.add_argument("--max-depth", type=int, default=6)
    p = sub.add_parser("check"); with_db(p)
    p = sub.add_parser("stats"); with_db(p)

    a = ap.parse_args()
    fn = {"init": cmd_init, "init-types": cmd_init_types, "add-entity": cmd_add_entity,
          "add-edge": cmd_add_edge, "types": cmd_types, "show": cmd_show,
          "path": cmd_path, "check": cmd_check, "stats": cmd_stats}[a.cmd]
    sys.exit(fn(a) or 0)


if __name__ == "__main__":
    main()
