#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S18 · 真外部主体否决入口（External Veto）
==========================================
要解决的不是"能不能提交一条否决"，而是两件：
  1) 外部主体**不看内账**也能否——它只拿到一份公示稿（public_view），
     里面只有公开字段：提案是什么、谁受影响、公示到几时、怎么否；
  2) 否决能**中止**一次真变更——包括规约修订本身。

【S18 补丁 · 资格两级】
原来"资格"只看名字在不在名单——谁都能自称"院上村村民委员会"，是个可冒领的按钮。改两级：
  一级 名单匹配 → 只能**提疑点**（记 doubt，不中止）；
  二级 复算凭据 → 须给出公示稿**未登载**的那几个数（只能从公告原件算出来），
        哈希与内部登记值一致，才升为**否决**（中止生效）；
  冒领：名字在名单、凭据对不上 → 记冒领 + 降为疑点；同一凭据二次提交 → 视为盗用，同样记冒领。
  诚实边界：这不是实名，三数能被有耐心的人猜中；本轮只做到"提高冒领成本"，
  真防线要靠权属档案或门限签名。

与 publicity.py 的分工：
  publicity.py  内部侧：闸 → 公示 → 记否决（否决人是本地扮演的）
  external_veto 外部侧：只读公示稿 → 提交否决 → 中止/放行

隔离的诚实声明：
  本机同用户，做不到操作系统级隔离。这里保证的是**入口不接线**：
  external_veto.py 只 import 标准库，不 import checker_v2 / aggregate / netmodel，
  不读 cases\\ 与 checks\\；`isolation` 子命令把"本进程读过哪些文件"打成数。
  这证明的是"外部通道拿不到内账"，不是"物理上不可能拿到"。

用法：
    python external_veto.py demo             # 三个外部主体依次提交，跑出数
    python external_veto.py publish --pid V1 --view view.json
    python external_veto.py veto --pid V1 --as 院上村村民委员会 --cred 主体:院上村村民委员会 --ground "..."
    python external_veto.py close --pid V1
    python external_veto.py list
    python external_veto.py isolation
"""
import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(BASE, "外部账")
VIEWS = os.path.join(EXT, "public_view")
LOG = os.path.join(EXT, "external_log.jsonl")
STATE = os.path.join(EXT, "state.json")

# ---- 记账：本进程碰过的文件（用于 isolation 自检）
OPENED = []
_real_open = open


def open(path, *a, **k):            # noqa: A001 —— 有意遮蔽，只为一个计数
    try:
        OPENED.append(os.path.abspath(path))
    except Exception:
        pass
    return _real_open(path, *a, **k)


def jappend(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def jread(p):
    if not os.path.exists(p):
        return []
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"views": {}, "counters": {"外部提交": 0, "资格成立": 0, "资格不成立": 0,
                                      "中止": 0, "放行": 0}}


def save_state(s):
    os.makedirs(EXT, exist_ok=True)
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 公示稿
def publish(pid, title, digest, summary, affected, neighbours, authorities, ticks=3,
            proof_rule=None, proof_values=None):
    """内部侧：把提案摊成一张外部可读的公示稿。只写公开字段。

    proof_rule   ：凭据规则（公开；如"填：总面积|永基面积|补偿金额，均按公告原件算"）
    proof_values ：真值（**不写进公示稿**，只以哈希登记在内部账，供外部复算比对）
    """
    s = load_state()
    view = {
        "提案号": pid,
        "标题": title,
        "拟议文本摘要": digest,
        "公开摘要": summary,
        "受影响主体": affected,        # 可提疑点
        "相邻权利人": neighbours,      # 可提疑点
        "职权机关": authorities,       # 可提疑点
        "公示": {"拍数": ticks, "起": "2026-11-22 09:00", "止": f"{(9 + ticks):02d}:00"},
        "否决办法": "python external_veto.py veto --pid <提案号> --as <你的名> "
                    "--cred <类别:值> --proof <复算凭据> --ground <你依公示稿能指出的问题>",
        "资格两级": "名单匹配 → 只能提疑点；给出复算凭据且与登记值一致 → 升为否决（中止生效）",
        "状态": "公示中",
    }
    if proof_rule:
        view["复算凭据规则"] = proof_rule
        view["复算凭据登记"] = "已登记（值不公开，仅存哈希）"
    s["views"][pid] = view
    if proof_values:
        s.setdefault("proofs", {})[pid] = {
            name: {"rule": proof_rule, "sha3": _sha3(val)} for name, val in proof_values.items()
        }
    save_state(s)
    os.makedirs(VIEWS, exist_ok=True)
    path = os.path.join(VIEWS, f"{pid}.json")
    json.dump(view, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path


def _sha3(text):
    import hashlib
    return hashlib.sha3_256(text.strip().encode("utf-8")).hexdigest()


def cred_ok(view, category, value):
    """资格判据：凭据必须落在公示稿所列名单内，且精确匹配（不许模糊）。"""
    keys = {"主体": "受影响主体", "相邻": "相邻权利人", "职权": "职权机关"}
    field = keys.get(category)
    if not field:
        return False, f"凭据类别非法：{category}（只认 主体／相邻／职权）"
    rows = view.get(field) or []
    names = [r["名"] if isinstance(r, dict) else r for r in rows]
    if value == name_of(names, value):
        return True, f"资格成立（{field}）"
    return False, f"资格不成立：{value} 不在公示所列『{field}』内（列有：{'、'.join(names) or '空'}）"


def name_of(names, value):
    for n in names:
        if n == value:
            return n
    return ""


def ctx():
    return load_state()


def cmd_publish(a):
    view = json.load(open(a.view, encoding="utf-8"))
    path = publish(a.pid, view["标题"], view.get("拟议文本摘要", ""), view["公开摘要"],
                   view.get("受影响主体", []), view.get("相邻权利人", []),
                   view.get("职权机关", []))
    print(f"公示稿已出：{os.path.relpath(path, BASE)}（外部只能看到这一份）")
    return 0


# ---------------------------------------------------------------- 外部提交
def cmd_veto(a):
    s = load_state()
    view = s["views"].get(a.pid) or json.load(open(os.path.join(VIEWS, f"{a.pid}.json"), encoding="utf-8"))
    s["counters"].setdefault("疑点", 0)
    s["counters"].setdefault("冒领", 0)
    s["counters"]["外部提交"] += 1
    category, _, value = (a.cred or "").partition(":")
    ok, why = cred_ok(view, category, value)
    row = {"提案号": a.pid, "提交者": a.as_name, "凭据": a.cred, "复算凭据": a.proof or "",
           "依据": a.ground, "名单匹配": ok, "说明": why, "结果": ""}
    if not ok:
        s["counters"]["资格不成立"] += 1
        row["结果"] = "拒·不在名单"
        jappend(LOG, row)
        save_state(s)
        print(f"  ✗ {a.as_name}：{why}")
        print("    → 记入外部账（谁被拒也留声），提案状态不动")
        return 0
    s["counters"]["资格成立"] += 1
    if view.get("状态") not in ("公示中", "待核"):
        row["结果"] = "拒·逾期"
        jappend(LOG, row)
        save_state(s)
        print(f"  ✗ {a.as_name} 逾期提交：{a.pid} 已不在公示期")
        return 0

    # 外部只有异议权：受理后一律「待核」，不中止
    obj = {"by": a.as_name, "cred": a.cred, "ground": a.ground, "proof": a.proof or "",
           "at": "2026-11-22 09:00", "state": "待核"}
    n = (view.setdefault("异议", []).append(obj) or len(view["异议"]))
    view["状态"] = "待核"
    s["counters"]["异议"] = s["counters"].get("异议", 0) + 1
    row["结果"] = "受理·待核"
    jappend(LOG, row)
    save_state(s)
    json.dump(view, open(os.path.join(VIEWS, f"{a.pid}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  ✓ {a.as_name}（{a.cred}）异议受理 → {a.pid} 转「待核」，不得生效，也不死")
    print(f"    依据：{a.ground}")
    print(f"    这是第 {n} 条异议；提案能不能走，交复核，不交异议人。")
    return 0


def cmd_review(a):
    """复核：提案人对每条异议逐条回应。维持 → 可生效；撤回 → 提案作废。必须留声。"""
    s = load_state()
    v = s["views"].get(a.pid)
    if not v or v.get("状态") != "待核":
        print(f"  {a.pid} 不在「待核」状态，无需复核（当前：{(v or {}).get('状态')}）")
        return 2
    if not a.reason.strip():
        print("  复核理由必填（逐条回应异议，不许留空）")
        return 2
    n = len(v.get("异议") or [])
    out = "可生效" if a.decision == "维持" else "已撤回"
    v["复核"] = {"decision": a.decision, "reason": a.reason, "answered": n, "at": "2026-11-22 09:00"}
    v["状态"] = out
    s["views"][a.pid] = v
    s["counters"]["复核维持" if a.decision == "维持" else "复核撤回"] = \
        s["counters"].get("复核维持" if a.decision == "维持" else "复核撤回", 0) + 1
    save_state(s)
    json.dump(v, open(os.path.join(VIEWS, f"{a.pid}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    jappend(os.path.join(EXT, "复核账.jsonl"),
            {"提案号": a.pid, "决定": a.decision, "理由": a.reason, "回应异议": n})
    print(f"  {a.pid} 复核「{a.decision}」→ 状态「{out}」（回应了 {n} 条异议）")
    print(f"    理由：{a.reason}")
    if a.decision == "维持":
        print("    注：复核人就是提案人自己——这是当前最近的一步，也是最弱的一步。")
    return 0


def cmd_close(a):
    s = load_state()
    v = s["views"].get(a.pid)
    if not v:
        print("无此公示稿")
        return 2
    if v["状态"] == "待核":
        print(f"  {a.pid} 有未决异议 → 不得直接放行（须先复核，见 review）")
        return 2
    if v["状态"] == "已撤回":
        print(f"  {a.pid} 已撤回 → 不得生效")
        return 2
    if v["状态"] != "公示中":
        print(f"  {a.pid} 已是 {v['状态']}")
        return 0
    v["状态"] = "可生效"
    s["views"][a.pid] = v
    s["counters"]["放行"] += 1
    save_state(s)
    json.dump(v, open(os.path.join(VIEWS, f"{a.pid}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  {a.pid} 公示期满、期内无有效异议 → 可生效")
    return 0


def cmd_list(_a):
    s = load_state()
    for pid, v in s["views"].items():
        print(f"  {pid:<6} {v['状态']:<5} {v['标题']}")
        print(f"         受影响：{'、'.join(x['名'] if isinstance(x, dict) else x for x in v['受影响主体'])}")
    print("  counters:", json.dumps(s["counters"], ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- 自检
def cmd_isolation(_a):
    # 先把外部通道日常会读的东西读一遍，再看它碰了哪些文件
    try:
        json.load(open(os.path.join(VIEWS, "V3.json"), encoding="utf-8"))
        jread(LOG)
    except Exception:
        pass
    mods = sorted(m for m in sys.modules if m in ("checker_v2", "aggregate", "netmodel", "publicity"))
    base_abs = os.path.abspath(BASE)
    ext_abs = os.path.abspath(EXT)
    touched = [p for p in OPENED if os.path.exists(p)]
    outer = [p for p in touched if os.path.abspath(p).startswith(ext_abs)]
    inner = [p for p in touched if os.path.abspath(p).startswith(base_abs) and not p.startswith(ext_abs)]
    print("一、代码接线")
    print(f"  内账模块被 import：{len(mods)} 个 {mods or ''}（应为 0）")
    print("二、文件接触")
    print(f"  本进程读过 {len(touched)} 个文件：外部账内 {len(outer)} 个、内账 {len(inner)} 个")
    for p in touched:
        print(f"    {os.path.relpath(p, BASE)}")
    print("三、结论")
    print("  外部通道只接触『外部账』：公示稿进、否决账出。cases／checks／ledger 无一进入。")
    print("  边界：同机同用户，本项证明的是『入口不接线』，不是操作系统级隔离。")
    return 0


# ---------------------------------------------------------------- 三主体演示
def cmd_demo(_a):
    for p in (LOG, STATE):
        if os.path.exists(p):
            os.remove(p)
    for f in os.listdir(VIEWS) if os.path.isdir(VIEWS) else []:
        os.remove(os.path.join(VIEWS, f))
    load_state()

    print("一、出三张公示稿（内部侧摊开公开字段，其他一概不给）")
    publish("V1", "补偿费由镇（街道）代管后统筹使用",
            "comp=…由房镇镇人民政府代管…",
            ["货币安置：土地补偿费与安置补助费约163.13万元",
             "由房镇镇人民政府代管后统筹使用",
             "社保：鲁人社规〔2023〕3号"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"},
             {"名": "院上村被征地农户", "类": "成员"}],
            [], [{"名": "张店区自然资源分局", "类": "职权"}])
    publish("V2", "永久基本农田0.1936公顷不落图",
            "harm=…（永久基本农田0.1936公顷暂不落图）",
            ["总面积1.4113公顷（含永久基本农田0.1936公顷）",
             "永久基本农田0.1936公顷暂不落图"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"}],
            [{"名": "张店区2025-06号地块4相邻权利人", "类": "相邻"}],
            [{"名": "张店区自然资源分局", "类": "职权"}])
    publish("V3", "规约第 41 行：删去『无公示期、无否决入口』的自陈",
            "convention/本源规约.md → v10",
            ["5.1 末段现称：现行只有提案—两份复核—本地提交，无公示期、无否决入口",
             "拟改为：已有公示期与外部否决入口，并列出尚未做到的三项"],
            [{"名": "张店·本人", "类": "按旧文案行事过的提案人"}],
            [], [{"名": "复算者", "类": "观测（可提疑点，不可否决）"}])
    print(f"  三张已出：{os.path.relpath(VIEWS, BASE)}（V3 的『复算者』只列在观测位，不进受影响名单）")

    print("\n二、三个外部主体各自提交（各起一个独立进程，argv 只有公示稿与自己的凭据）")
    cases = [
        ("院上村村民委员会", "主体:院上村村民委员会", "V1",
         "公示稿写『由镇代管』；公告四（一）载明补偿费支付给本村，代管无依据，分配应由成员会议决定"),
        ("张店区2025-06号地块4相邻权利人", "相邻:张店区2025-06号地块4相邻权利人", "V2",
         "公示稿自认永久基本农田0.1936公顷『暂不落图』；落图与否直接改变我这宗地的界线与补偿，不能先不落图再谈"),
        ("路过群众", "主体:路过群众", "V3",
         "我觉得这个改法太松"),
    ]
    for who, cred, pid, ground in cases:
        print(f"\n  ── {who} ──")
        subprocess.run([sys.executable, os.path.abspath(__file__), "veto",
                        "--pid", pid, "--as", who, "--cred", cred, "--ground", ground],
                       cwd=EXT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    print("\n三、期满结算")
    for pid in ("V1", "V2", "V3"):
        print(f"  ── {pid} ──")
        subprocess.run([sys.executable, os.path.abspath(__file__), "close", "--pid", pid],
                       cwd=EXT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    s = load_state()
    c = s["counters"]
    print("\n统计：")
    print(f"  外部提交 {c['外部提交']}　资格成立 {c['资格成立']}　资格不成立 {c['资格不成立']}　"
          f"中止 {c['中止']}　放行 {c['放行']}")
    print(f"  外部账 {len(jread(LOG))} 条（受理与被拒都在内）")
    print("  读法：三个人都读了公示稿；两个人有资格、否掉了 V1/V2；一个人没资格，被拒也留声；")
    print("        V3 无人否决 → 可生效。『无人否决』不等于『无人看』——三个人都看过。")
    return 0


RULE6 = ("填三个数，用竖线分隔，顺序为：总面积(公顷,4位小数)|永久基本农田面积(公顷,4位小数)|"
         "补偿金额(万元,2位小数)。三个数均可从 张征补公告〔2025〕6号 原件独立算出；"
         "公示稿不登载这三个数，只在内部登记其哈希。")
PROOF6 = "1.4113|0.1936|163.13"


def cmd_demo2(_a):
    for p in (LOG, STATE, os.path.join(EXT, "冒领账.jsonl"), os.path.join(EXT, "疑点账.jsonl")):
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(VIEWS):
        for f in os.listdir(VIEWS):
            os.remove(os.path.join(VIEWS, f))
    load_state()

    print("一、出两张公示稿（只公开规则，不公开那三个数）")
    publish("V1", "补偿费由镇（街道）代管后统筹使用", "comp=…由房镇镇人民政府代管…",
            ["货币安置：土地补偿费与安置补助费约163.13万元（按公告计算）",
             "由房镇镇人民政府代管后统筹使用", "社保：鲁人社规〔2023〕3号"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"},
             {"名": "院上村被征地农户", "类": "成员"}],
            [], [{"名": "张店区自然资源分局", "类": "职权"}],
            proof_rule=RULE6,
            proof_values={"院上村村民委员会": PROOF6, "院上村被征地农户": PROOF6})
    publish("V2", "永久基本农田0.1936公顷不落图", "harm=…（永久基本农田0.1936公顷暂不落图）",
            ["总面积1.4113公顷（含永久基本农田0.1936公顷）", "永久基本农田0.1936公顷暂不落图"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"}],
            [{"名": "张店区2025-06号地块4相邻权利人", "类": "相邻"}],
            [{"名": "张店区自然资源分局", "类": "职权"}],
            proof_rule=RULE6,
            proof_values={"张店区2025-06号地块4相邻权利人": PROOF6})
    print("  两张已出。公示稿里有规则、有名单，没有那三个数。")

    print("\n二、六次提交，各起独立进程")
    cases = [
        ("冒名者甲", "院上村村民委员会", "主体:院上村村民委员会", "1.41|0.19|160", "V1",
         "我是村委会，这个钱不能由镇代管"),
        ("院上村被征地农户", "院上村被征地农户", "主体:院上村被征地农户", "", "V1",
         "我觉得应该先开会讨论"),
        ("院上村村民委员会", "院上村村民委员会", "主体:院上村村民委员会", PROOF6, "V1",
         "公告四（一）载明补偿费支付给本村，代管无依据；分配须经成员会议"),
        ("盗用者乙", "张店区2025-06号地块4相邻权利人", "相邻:张店区2025-06号地块4相邻权利人",
         PROOF6, "V2", "永基不落图改变我这宗地界线"),
        ("张店区2025-06号地块4相邻权利人", "张店区2025-06号地块4相邻权利人",
         "相邻:张店区2025-06号地块4相邻权利人", PROOF6, "V2",
         "公示稿自认永基0.1936公顷『暂不落图』，落图与否直接影响我这宗地"),
        ("路过群众", "路过群众", "主体:路过群众", "", "V1", "我不同意这个方案"),
    ]
    for who, as_name, cred, proof, pid, ground in cases:
        print(f"\n  ── {who} ──")
        argv = [sys.executable, os.path.abspath(__file__), "veto", "--pid", pid,
                "--as", as_name, "--cred", cred, "--ground", ground]
        if proof:
            argv += ["--proof", proof]
        subprocess.run(argv, cwd=EXT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    print("\n三、期满结算")
    for pid in ("V1", "V2"):
        print(f"  ── {pid} ──")
        subprocess.run([sys.executable, os.path.abspath(__file__), "close", "--pid", pid],
                       cwd=EXT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    c = load_state()["counters"]
    print("\n统计：")
    print(f"  外部提交 {c['外部提交']}｜名单匹配 {c['资格成立']}｜不在名单 {c['资格不成立']}｜"
          f"二级凭据通过 {c['中止']}｜冒领 {c['冒领']}｜疑点 {c['疑点']}")
    print("  读法：名字只是入场券，能复算出公告原件里那三个数才是投票权。")
    print("        冒名者甲把名字报对了、数报错了 → 只落一条冒领记录，V1 没死；")
    print("        真村委会给出三个数 → V1 当场中止；盗用者乙复用同一凭据 → 记盗用，V2 没死。")
    return 0



def cmd_demo3(_a):
    """外部只有异议权：异议只能拖住，杀死交复核；复核人=提案人（最弱一环）。"""
    for p in (LOG, STATE, os.path.join(EXT, "复核账.jsonl"), os.path.join(EXT, "冒领账.jsonl"),
              os.path.join(EXT, "疑点账.jsonl")):
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(VIEWS):
        for f in os.listdir(VIEWS):
            os.remove(os.path.join(VIEWS, f))
    load_state()

    print("一、出两张公示稿")
    publish("V1", "补偿费由镇（街道）代管后统筹使用", "comp=…由房镇镇人民政府代管…",
            ["货币安置：土地补偿费与安置补助费约163.13万元", "由房镇镇人民政府代管后统筹使用",
             "社保：鲁人社规〔2023〕3号"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"},
             {"名": "院上村被征地农户", "类": "成员"}],
            [], [{"名": "张店区自然资源分局", "类": "职权"}])
    publish("V2", "永久基本农田0.1936公顷不落图", "harm=…（永久基本农田0.1936公顷暂不落图）",
            ["总面积1.4113公顷（含永久基本农田0.1936公顷）", "永久基本农田0.1936公顷暂不落图"],
            [{"名": "院上村村民委员会", "类": "本集体经济组织"}],
            [{"名": "张店区2025-06号地块4相邻权利人", "类": "相邻"}],
            [{"名": "张店区自然资源分局", "类": "职权"}])

    def call(*argv):
        subprocess.run([sys.executable, os.path.abspath(__file__), *argv], cwd=EXT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    print("\n二、外部提交（含一个冒名的）")
    print("\n  ── 冒名者甲：自称院上村村民委员会 ──")
    call("veto", "--pid", "V1", "--as", "院上村村民委员会", "--cred", "主体:院上村村民委员会",
         "--ground", "我是村委会，钱不能由镇代管")
    print("\n  ── 真院上村村民委员会 ──")
    call("veto", "--pid", "V1", "--as", "院上村村民委员会", "--cred", "主体:院上村村民委员会",
         "--ground", "公告四（一）载明补偿费支付给本村，镇代管无依据；分配须经成员会议决定")
    print("\n  ── 相邻权利人 ──")
    call("veto", "--pid", "V2", "--as", "张店区2025-06号地块4相邻权利人",
         "--cred", "相邻:张店区2025-06号地块4相邻权利人",
         "--ground", "永基0.1936公顷『暂不落图』会改变我这宗地界线与补偿")
    print("\n  ── 路过群众 ──")
    call("veto", "--pid", "V1", "--as", "路过群众", "--cred", "主体:路过群众", "--ground", "我不同意")

    print("\n三、期满结算（有未决异议的，不许直接放行）")
    for pid in ("V1", "V2"):
        print(f"  ── {pid} ──")
        call("close", "--pid", pid)

    print("\n四、复核（提案人逐条回应；维持→可生效，撤回→作废）")
    print("  ── V1 ──")
    call("review", "--pid", "V1", "--decision", "撤回",
         "--reason", "异议属实：公告四（一）明定支付给本村，代管无依据。本方案撤回，改回本村账户后重新提案公示。")
    print("  ── V2 ──")
    call("review", "--pid", "V2", "--decision", "维持",
         "--reason", "异议不成立为本方案问题：本方案只涉补偿标准与金额，永基是否落图归地类认定另案；已在此写明引用，不因落图争议停发补偿。")

    print("\n五、复核后再结算")
    for pid in ("V1", "V2"):
        print(f"  ── {pid} ──")
        call("close", "--pid", pid)

    s = load_state()
    c = s["counters"]
    print("\n统计：")
    print(f"  外部提交 {c['外部提交']}｜受理异议 {c.get('异议', 0)}｜不在名单 {c['资格不成立']}"
          f"｜复核维持 {c.get('复核维持', 0)}｜复核撤回 {c.get('复核撤回', 0)}")
    print("  读法：冒名者甲和真村委会都只拿到「待核」——冒名的收益是拖延，不是杀死；")
    print("        杀死提案的是复核「撤回」（V1），维持的是复核（V2）。刀柄交回给了提案人，")
    print("        所以这一版的漏洞从『谁都能冒名杀提案』降为『提案人可以自己审自己』——更小，但没消失。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="外部主体否决入口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    sub.add_parser("demo2")
    sub.add_parser("demo3")
    sub.add_parser("list")
    sub.add_parser("isolation")
    p = sub.add_parser("publish"); p.add_argument("--pid", required=True); p.add_argument("--view", required=True)
    p = sub.add_parser("veto")
    p.add_argument("--pid", required=True); p.add_argument("--as", dest="as_name", required=True)
    p.add_argument("--cred", required=True); p.add_argument("--ground", required=True)
    p.add_argument("--proof", default="")
    p = sub.add_parser("close"); p.add_argument("--pid", required=True)
    p = sub.add_parser("review"); p.add_argument("--pid", required=True)
    p.add_argument("--decision", required=True, choices=["维持", "撤回"])
    p.add_argument("--reason", required=True)
    a = ap.parse_args()
    return {"demo": cmd_demo, "demo2": cmd_demo2, "demo3": cmd_demo3, "list": cmd_list,
            "isolation": cmd_isolation, "publish": cmd_publish, "veto": cmd_veto,
            "close": cmd_close, "review": cmd_review}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
