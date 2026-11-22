#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活网 → 网络大模型：构建计划图（22 步）
输出两件：可编辑 .excalidraw + 预览 PNG（同一套坐标）
"""
import json
import os

OUT = r"F:\Obsidian法律知识库\Excalidraw"
NAME = "活网-网络大模型-计划图"
W, H = 1520, 1544

STEPS = [
    ("P1 底座", "已建", [
        ("S1", "规约 v11 ＋ 锚链", "check 退出 0｜11/11｜4/4", "done"),
        ("S2", "18 类关系引擎", "test_engine 18/18", "done"),
        ("S3", "144 词位账本", "8 域 × 18 关系", "done"),
    ]),
    ("P2 词表", "已建", [
        ("S4", "真事入 propose()", "串行 0.72｜并行 0.88", "done"),
        ("S5", "跨域对照", "144 压不到 18 格", "done"),
        ("S6", "v2 六十格", "关系 36 ＋ 域 24", "done"),
    ]),
    ("P3 判断力", "已建", [
        ("S7", "三层闸拆分", "一致 20｜分歧 0", "done"),
        ("S8", "公示期 ＋ 否决", "4 提案｜闸拒 1｜否决 1", "done"),
    ]),
    ("P4 梯度", "在修", [
        ("S9", "批评者登记", "3 主体｜票重 2/2/1", "done"),
        ("S10", "否决权重·信用", "分叉 4/5｜上限 1.5×", "part"),
        ("S11", "批量五件", "稳定格 2/6", "done"),
        ("S12", "回灌参数化判据", "已装｜正 5/5 负 10/10", "done"),
        ("S13", "区片表", "Ⅰ/Ⅱ/Ⅳ 已填，Ⅲ 缺档", "done"),
    ]),
    ("P5 结构", "在修", [
        ("S14", "第二层聚合", "三层各拦一类｜件级一条", "done"),
        ("S15", "学习率·衰减", "EMA＋沉默衰减＋阈值会动\n需回应 18→0", "done"),
        ("S16", "死锁与裁决", "K1–K4｜七件冻 2", "done"),
    ]),
    ("P6 落地", "在修", [
        ("S17", "三处介质落地", "账包离线可验｜处1 已置\n处2/3 待物理动作", "part"),
        ("S18", "真外部主体否决", "异议＋复核｜未公示即拒", "done"),
        ("S19", "规模测试 3→9", "判据 9/9｜否决率 5.3%", "done"),
    ]),
    ("P7 联网", "已建", [
        ("S20", "触须对接", "五铁律｜3 节点｜联邦 90\n冲突 24｜异宗 1｜重复 0", "done"),
        ("S21", "免疫层（仿生）", "行为谱认自己人｜首见隔离\n三拍成熟｜异己反应降滴度", "done"),
        ("S22", "复核主体换人", "v11 一号洞：提案人不得\n兼复核人（未做）", "warn"),
    ]),
]

MILESTONES = [
    ("M1", "通道通", "S8 完成", "已到"),
    ("M2", "尺子准", "S12–S13", "已到"),
    ("M3", "成网络", "S14 起", "已到"),
    ("M4", "有正当性", "S18", "已到"),
]

# 伦理底盘 · 私有技能隔离区：独立于 22 步构建线之外，不排期、不并入、不触须传递
ISOLATION = [
    ("【私有技能隔离区】", "独立于火种网络之外 · 不参与全网同步"),
    ("18 种关系界定 / 貔貅调度", "私有定制部分，不打包、不触须传递"),
    ("活字复用 / 逆向取证", "个人工具归个人，不向任何节点扩散"),
    ("╳ 与网络之间：无数据流通", "只传四类事实包；夹带私技即异宗拒并留痕"),
]

COLOR = {
    "done": ("#2f9e44", "#d3f9d8"),
    "part": ("#f59f00", "#fff9db"),
    "todo": ("#495057", "#f8f9fa"),
    "warn": ("#c92a2a", "#ffe3e3"),
    "phase": ("#862e9c", "#f3d9fa"),
    "mile": ("#1971c2", "#e7f5ff"),
}

ROW_Y0, ROW_H, ROW_GAP = 118, 110, 12
PX, PW = 34, 172
SX, SW, SGAP = 222, 222, 16


def img_items():
    """(x,y,w,h,stroke,fill,text,size,bold) —— 文本条目 y 即文本顶部"""
    items = []
    tits = [(40, 14, 1400, 40, "活网 → 网络大模型 · 构建计划：共 22 步", 28, True),
            (40, 60, 1440, 26,
             "绿＝已建　黄＝在建／待回灌　灰＝未建　红＝未建但为前置（不先做，扩维白费）　紫＝阶段　蓝＝里程碑", 13, False)]
    for i, (ph, note, steps) in enumerate(STEPS):
        y = ROW_Y0 + i * (ROW_H + ROW_GAP)
        s, f = COLOR["phase"]
        items.append((PX, y, PW, ROW_H, s, f, "", 0, False))
        tits.append((PX + 10, y + 12, PW - 20, 22, ph, 14, True))
        tits.append((PX + 10, y + ROW_H - 26, PW - 20, 18, note, 12, False))
        for j, (sid, title, desc, st) in enumerate(steps):
            x = SX + j * (SW + SGAP)
            s, f = COLOR[st]
            items.append((x, y, SW, ROW_H, s, f, "", 0, False))
            tits.append((x + 10, y + 10, SW - 20, 20, f"{sid}　{title}", 12.5, True))
            tits.append((x + 10, y + 34, SW - 20, 60, desc, 10.5, False))
    my = ROW_Y0 + len(STEPS) * (ROW_H + ROW_GAP) + 14
    s, f = COLOR["mile"]
    items.append((PX, my, 1400, 104, s, f, "", 0, False))
    tits.append((PX + 12, my + 10, 140, 22, "里程碑", 15, True))
    for k, (mid, t, d, when) in enumerate(MILESTONES):
        x = PX + 150 + k * 310
        items.append((x, my + 18, 290, 72, s, "#ffffff", "", 0, False))
        tits.append((x + 10, my + 24, 270, 22, f"{mid}　{t}", 13.5, True))
        tits.append((x + 10, my + 48, 270, 18, f"{d}　·　{when}", 11, False))
    ny = my + 124
    tits.append((40, ny, 1440, 84,
                 "怎么数步：已建 19 步（S1–S9、S11–S16、S18–S21，除 S10 在建）、在建 2 步（S10 信用与寡头、S17 三处介质 1/3）、未建 1 步（S22 复核主体换人）。\n"
                 "顺序：规约已 v11；S15 已把「需回应」18→0；S20 触须跑一次即织一次；S21 免疫层默认关（LW_IMMUNE=1 才启用），三拍成熟、异己反应降滴度。下一步 S22：复核主体换人（v11 一号洞，红框未做）。", 10.5, False))

    # 私有技能隔离区：独立分支，不排在 22 步内，无箭头连入构建线
    iy = ny + 96
    s, f = ("#e8590c", "#fff4e6")
    items.append((40, iy, 1400, 28, s, f, "", 0, False))
    tits.append((52, iy + 5, 1380, 20,
                 "伦理底盘 · 【私有技能隔离区】——独立于火种网络之外，不参与全网同步、不随触须传递（见 ethic_root.md）", 13, True))
    row_y = iy + 36
    for k, (t1, t2) in enumerate(ISOLATION):
        bx = 40 + k * 354
        items.append((bx, row_y, 342, 78, s, f, "", 0, False))
        tits.append((bx + 12, row_y + 8, 322, 26, t1, 12, True))
        tits.append((bx + 12, row_y + 40, 322, 34, t2, 10, False))
    tits.append((40, row_y + 90, 1400, 22,
                 "↑ 隔离区不占 22 步任何一步、无箭头连入构建线：同源范式，无数据流通。火种归网络公众，私技始终归个人。", 11, False))
    return items, tits


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
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    shapes, texts = img_items()
    for x, y, w, h, s, f, *_ in shapes:
        if s and f:
            ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=6",
                                        linewidth=1.6, edgecolor=s, facecolor=f))
    for x, y, w, h, txt, size, bold in texts:
        ax.text(x, y, txt, fontproperties=(fpb if bold else fp), fontsize=size,
                color="#1e1e1e", va="top", ha="left", linespacing=1.45)
    path = os.path.join(OUT, NAME + ".png")
    fig.savefig(path, dpi=100, facecolor="white")
    print("png ->", path)
    return path


def element(eid, etype, x, y, w, h, stroke="#1e1e1e", fill="transparent"):
    return {"id": eid, "type": etype, "x": x, "y": y, "width": w, "height": h, "angle": 0,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1, "opacity": 100,
            "groupIds": [], "frameId": None, "roundness": {"type": 3}, "boundElements": [],
            "updated": 1, "link": None, "locked": False}


def text_el(eid, x, y, w, h, txt, size=16, bold=False):
    d = element(eid, "text", x, y, w, h, "#1e1e1e", "transparent")
    d.update({"text": txt, "fontSize": size, "fontFamily": 1, "textAlign": "left",
              "verticalAlign": "top", "containerId": None, "originalText": txt, "lineHeight": 1.25})
    if bold:
        d["strokeWidth"] = 2
    return d


def excalidraw():
    els = [text_el("title", 40, 14, 1400, 40, "活网 → 网络大模型 · 构建计划：共 22 步", 30),
           text_el("legend", 40, 58, 1400, 26,
                   "绿＝已建　黄＝在建／待回灌　灰＝未建　红＝未建但为前置　紫＝阶段　蓝＝里程碑", 13)]
    for i, (ph, note, steps) in enumerate(STEPS):
        y = ROW_Y0 + i * (ROW_H + ROW_GAP)
        s, f = COLOR["phase"]
        els.append(element(f"ph{i}", "rectangle", PX, y, PW, ROW_H, s, f))
        els.append(text_el(f"pht{i}", PX + 8, y + 10, PW - 16, 24, ph, 15))
        els.append(text_el(f"phn{i}", PX + 8, y + ROW_H - 26, PW - 16, 20, note, 12))
        for j, (sid, title, desc, st) in enumerate(steps):
            x = SX + j * (SW + SGAP)
            s, f = COLOR[st]
            els.append(element(f"b{sid}", "rectangle", x, y, SW, ROW_H, s, f))
            els.append(text_el(f"s{sid}", x + 8, y + 8, SW - 16, 22, f"{sid}　{title}", 14))
            els.append(text_el(f"d{sid}", x + 8, y + 36, SW - 16, 40, desc, 12))
    my = ROW_Y0 + len(STEPS) * (ROW_H + ROW_GAP) + 14
    s, f = COLOR["mile"]
    els.append(element("mbar", "rectangle", PX, my, 1400, 108, s, f))
    els.append(text_el("mt", PX + 12, my + 10, 140, 22, "里程碑", 16))
    for k, (mid, t, d, when) in enumerate(MILESTONES):
        x = PX + 150 + k * 310
        els.append(element(f"m{k}", "rectangle", x, my + 20, 290, 76, s, "#ffffff"))
        els.append(text_el(f"mm{k}", x + 10, my + 26, 270, 22, f"{mid}　{t}", 14))
        els.append(text_el(f"md{k}", x + 10, my + 50, 270, 18, f"{d}　·　{when}", 12))
    ny = my + 128
    els.append(text_el("foot", 40, ny, 1400, 80,
                       "怎么数步：已建 10 步（S1–S11，除 S10 在建）、在建 1 步（S10）、未建 6 步（S12 S13 S14 S15 S17 S19）、"
                       "先决未建 2 步（S16 S18）。\n"
                       "顺序：S12→S13 先修尺子与立表，S14 起才谈第二层聚合；S16 裁决规则须先于任何扩维，否则死锁。", 12))
    # 私有技能隔离区（excalidraw）：独立分支，无箭头连入构建线
    iy = ny + 96
    s, f = ("#e8590c", "#fff4e6")
    els.append(element("isobar", "rectangle", 40, iy, 1400, 28, s, f))
    els.append(text_el("isotitle", 52, iy + 5, 1380, 20,
                       "伦理底盘 · 【私有技能隔离区】——独立于火种网络之外，不参与全网同步、不随触须传递（见 ethic_root.md）", 13))
    row_y = iy + 36
    for k, (t1, t2) in enumerate(ISOLATION):
        bx = 40 + k * 354
        els.append(element(f"iso{k}", "rectangle", bx, row_y, 342, 78, s, f))
        els.append(text_el(f"isot{k}", bx + 12, row_y + 8, 322, 26, t1, 12))
        els.append(text_el(f"isod{k}", bx + 12, row_y + 40, 322, 34, t2, 10))
    els.append(text_el("isofoot", 40, row_y + 90, 1400, 22,
                       "↑ 隔离区不占 22 步任何一步、无箭头连入构建线：同源范式，无数据流通。火种归网络公众，私技始终归个人。", 11))
    doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
           "elements": els, "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"}, "files": {}}
    path = os.path.join(OUT, NAME + ".excalidraw")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)
    print("excalidraw ->", path, len(els), "elements")
    return path


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    png()
    excalidraw()
    n = sum(len(s[2]) for s in STEPS)
    print("steps:", n)

