#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画「实际运作流程图」——不是计划，是现在真跑起来长什么样
输出：F:\\Obsidian法律知识库\\Excalidraw\\活网-实际流程图.{png,excalidraw}
"""
import json
import os

OUT = r"F:\Obsidian法律知识库\Excalidraw"
NAME = "活网-实际流程图"
W, H = 1520, 1512

# (栏标题, 副标题, [(步骤名, 细节, 状态)])
COLS = [
    ("A　跑一次：八步自检（run.py）", "只读；第 7 步无 peers 时报单机，第 8 步免疫自检", [
        ("run.py", "入口｜Python ≥3.9｜实测 3.13.18", "done"),
        ("① 三层闸逐格", "一致 20 格｜分歧 0", "done"),
        ("② v3 参数化判据", "一致 19｜分歧 1（旧闸漏放，已知）", "done"),
        ("③ 九件批量", "整件 9/9｜错例拦 18/18", "done"),
        ("④ 信用学习", "需回应 18→0｜旧规则 19/19 被单方否决", "done"),
        ("⑤ 层聚合 K1–K4", "成立 1｜不成立 3｜暂缓 1｜冻结 2", "done"),
        ("⑥ 账包离线验算", "金额 9/9｜账行 49 条｜总哈希对上", "done"),
        ("⑦ 触须织网", "3 节点｜90 事件｜冲突 24｜异宗 1", "done"),
        ("⑧ 免疫筛查", "行为谱认人｜首见隔离｜三拍成熟｜默认关", "done"),
    ]),
    ("B　一件提案：从公告到账", "真事＝张征补公告〔2025〕6 号（院上村）", [
        ("公告原件", "1.4113 公顷｜Ⅳ 112.5｜永基 0.1936", "done"),
        ("词表定位", "域 LW × 关系 compensation", "done"),
        ("五格切片", "who / rule / basis / harm / comp", "done"),
        ("三层校验", "关系表 → 域表 → 跨表算式", "done"),
        ("公示稿", "public_view：只放公开字段", "done"),
        ("外部异议", "提交 4｜受理 3｜名单外 1", "done"),
        ("复核决断", "维持 1｜撤回 1｜理由必填留声", "done"),
        ("写账", "events / rejects，驳回落到具体错处", "done"),
    ]),
    ("C　一次织网：一个节点 → 一张网", "每次运行伸一次、收一次；同宗才认", [
        ("身份", "规约 root ＋ 随机 node_id（非实名）", "done"),
        ("伸包", "45 事件 ＋ digest ＋ 协议 tentacle/1", "done"),
        ("投递", "peers.json 指向对端信箱", "part"),
        ("吸收", "同宗判定｜按(节点,键)去重｜重复 0 新增", "done"),
        ("三本账", "联邦 90｜冲突 24｜异宗 1", "done"),
        ("裁决回流", "冲突交 K1–K4 → 口径修正再进下一轮", "part"),
    ]),
]

GAPS = [
    ("签名身份", "node_id 可冒名，真认证要各自持钥"),
    ("增量寻址", "现在整包交换，百万级要 Merkle／按格订阅"),
    ("公网中继", "现在只能同盘信箱，过网要中继或打洞"),
    ("跨法域分域", "征地数据出县未必合法，全球网须按域分"),
]

# 伦理底盘 · 私有技能隔离区：独立于三栏网络之外，无箭头相连（范式同源、无数据流通）
ISOLATION = [
    ("【私有技能隔离区】", "独立于火种网络之外 · 不参与全网同步"),
    ("18 种关系界定 / 貔貅调度", "私有定制部分，不打包、不触须传递"),
    ("活字复用 / 逆向取证", "个人工具归个人，不向任何节点扩散"),
    ("╳ 与网络之间：无数据流通", "只传四类事实包；夹带私技即异宗拒并留痕"),
]

COLOR = {"done": ("#2f9e44", "#d3f9d8"), "part": ("#f59f00", "#fff9db"),
         "todo": ("#495057", "#f8f9fa"), "gap": ("#c92a2a", "#ffe3e3"),
         "col": ("#862e9c", "#f3d9fa")}

GAP_Y = 126
CARD_H, GAP_V = 68, 22
COL_W = 452
COL_X = [40, 534, 1028]


def disp_w(s, size):
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w * size * 0.62


def items():
    shapes, texts = [], []
    texts.append((40, 16, 1400, 46, "活网 · 实际运作流程（v1 实测 · 2026-11-22）", 26, True))
    texts.append((40, 66, 1450, 24,
                  "绿＝已跑通　黄＝需人动作／未闭环　红＝明确未做的缺口　紫＝栏　"
                  "三条线：跑一次自检｜一件提案的一生｜一个节点织成网", 13, False))

    for ci, (title, sub, cards) in enumerate(COLS):
        x = COL_X[ci]
        s, f = COLOR["col"]
        shapes.append((x, GAP_Y, COL_W, CARD_H + 8, s, f, "", 0, False))
        texts.append((x + 12, GAP_Y + 6, COL_W - 22, 24, title, 15, True))
        texts.append((x + 12, GAP_Y + 36, COL_W - 22, 22, sub, 11, False))
        y = GAP_Y + CARD_H + 44
        for i, (name, detail, st) in enumerate(cards):
            s2, f2 = COLOR[st]
            shapes.append((x, y, COL_W, CARD_H, s2, f2, "", 0, False))
            texts.append((x + 12, y + 8, COL_W - 24, 24, name, 14, True))
            texts.append((x + 12, y + 34, COL_W - 24, 34, detail, 10.5, False))
            if i < len(cards) - 1:
                ax = x + COL_W / 2
                shapes.append((ax - 1.2, y + CARD_H, 2.4, GAP_V, "#868e96", "#ffffff", "", 0, False))
            y += CARD_H + GAP_V

    # 缺口条
    gy = GAP_Y + CARD_H + 44 + 9 * (CARD_H + GAP_V) + 18
    s, f = COLOR["gap"]
    shapes.append((40, gy, 1440, 96, s, f, "", 0, False))
    texts.append((52, gy + 8, 200, 24, "明确未做（不粉饰）", 14, True))
    texts.append((52, gy + 34, 1416, 56,
                  "　".join(f"{a}：{b}" for a, b in GAPS[:2]) + "\n"
                  + "　".join(f"{a}：{b}" for a, b in GAPS[2:]), 10.5, False))

    ny = gy + 118
    texts.append((40, ny, 1440, 44,
                  "真实节点数：1（本机）｜demo 里的 3 个节点只做机理验证，不计入真实网络规模\n"
                  "铁律：同宗才认（root 全等）｜异见不静默（同格不同判必记冲突）｜账与判据分离（换判据不动账）",
                  11.5, False))

    # 私有技能隔离区：独立分支框，无箭头接入上方三栏（范式同源、无数据流通）
    iy = ny + 66
    iso_stroke, iso_fill = "#e8590c", "#fff4e6"
    shapes.append((40, iy, 1440, 28, iso_stroke, iso_fill, "", 0, False))
    texts.append((52, iy + 5, 1400, 20,
                  "伦理底盘 · 【私有技能隔离区】——独立于火种网络之外，不参与全网同步、不随触须传递（见 ethic_root.md）",
                  13, True))
    row_y = iy + 34
    for k, (t1, t2) in enumerate(ISOLATION):
        bx = 40 + k * 362
        shapes.append((bx, row_y, 350, 78, iso_stroke, iso_fill, "", 0, False))
        texts.append((bx + 12, row_y + 8, 330, 26, t1, 12, True))
        texts.append((bx + 12, row_y + 40, 330, 34, t2, 10, False))
    # 明确标注：无连接线（不是漏画，是隔离）
    texts.append((40, row_y + 90, 1440, 22,
                  "↑ 以上隔离区与上方 A/B/C 三栏之间没有任何箭头：同源范式，无数据流通。火种归网络公众，私技始终归个人。",
                  11, False))
    return shapes, texts


def png():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import FancyBboxPatch

    fp = FontProperties(fname=r"C:\Windows\Fonts\msyh.ttc")
    fpb = FontProperties(fname=r"C:\Windows\Fonts\msyhbd.ttc")
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    shapes, texts = items()
    for x, y, w, h, s, f, *_ in shapes:
        if s and f:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=6",
                                        linewidth=1.6, edgecolor=s, facecolor=f))
    for x, y, w, h, txt, size, bold in texts:
        ax.text(x, y, txt, fontproperties=(fpb if bold else fp), fontsize=size,
                color="#1e1e1e", va="top", ha="left", linespacing=1.5)
    p = os.path.join(OUT, NAME + ".png")
    fig.savefig(p, dpi=100, facecolor="white")
    print("png ->", p)
    return p


def el(eid, etype, x, y, w, h, stroke="#1e1e1e", fill="transparent"):
    return {"id": eid, "type": etype, "x": x, "y": y, "width": w, "height": h, "angle": 0,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
            "groupIds": [], "frameId": None, "roundness": {"type": 3}, "boundElements": [],
            "updated": 1, "link": None, "locked": False}


def txt(eid, x, y, w, h, t, size=16, bold=False):
    d = el(eid, "text", x, y, w, h, "#1e1e1e", "transparent")
    d.update({"text": t, "fontSize": size, "fontFamily": 1, "textAlign": "left",
              "verticalAlign": "top", "containerId": None, "originalText": t, "lineHeight": 1.25})
    return d


def excalidraw():
    shapes, texts = items()
    els, n = [], 0
    for x, y, w, h, s, f, *_ in shapes:
        n += 1
        els.append(el(f"r{n}", "rectangle", x, y, w, h, s, f))
    for x, y, w, h, t, size, bold in texts:
        n += 1
        els.append(txt(f"t{n}", x, y, w, h, t, size, bold))
    doc = {"type": "excalidraw", "version": 2, "source": "flow_chart.py",
           "elements": els, "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
           "files": {}}
    p = os.path.join(OUT, NAME + ".excalidraw")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    print("excalidraw ->", p, len(els), "elements")
    return p


if __name__ == "__main__":
    png(); excalidraw()

