# -*- coding: utf-8 -*-
"""
S18 补丁 · 三种资格设计对照（纯模拟，不改任何账）
======================================================
同一组事件，三种"谁能否、否了算多大"的设计，看冒名者的净收益：

  A 名字制（S18 原版）      名单里有名字就行 → 直接中止
  B 公开事实凭据（本轮试的） 须复算公告里的三个数 → 直接中止
  C 署名＋暂缓＋待核       无核验的异议 → 只能暂缓（可恢复）；有登记簿号的 → 中止

事件（同一宗地、同一份公告）：
  e1 冒名者甲：自称"院上村村民委员会"，未读过原件／读过后瞎猜
  e2 真村委会：持有本村登记簿，可给出登记号
  e3 相邻权利人：同一宗地，能算出同一组三个数（凭据不唯一）
  e4 盗用者乙：拿 e2/e3 用过的凭据再投一次

复算： python mode_compare.py
"""
MODES = ("A 名字制", "B 公开事实凭据", "C 署名＋暂缓＋待核")
EVENTS = [
    ("e1 冒名者甲（自称村委会，凭据瞎猜）", False, False),
    ("e2 真村委会（持登记簿号）", True, True),
    ("e3 相邻权利人（同组三数，凭据不唯一）", False, True),
    ("e4 盗用者乙（复用已用过的凭据）", False, False),
]


def judge(mode, has_book, knows_numbers, used_numbers):
    """返回 (处置, 是否可恢复)。处置 ∈ 中止 / 暂缓 / 疑点 / 盗用 / 拒。"""
    if mode == "A 名字制":
        return "中止", False                       # 只看名字，冒名也能杀
    if mode == "B 公开事实凭据":
        if used_numbers:
            return "盗用", True                    # 凭据不唯一 → 真权利人也会撞
        if knows_numbers:
            return "中止", False                   # 读过公告就能算，冒名照样杀
        return "疑点", True
    # C
    if has_book:
        return "中止", False                       # 有登记簿号才是实名
    return "暂缓", True                            # 没有核验凭据 → 最多拖延，不能杀


def run():
    print("同一组事件，三种资格设计（纯模拟，不动账）\n")
    print(f"{'设计':<20}{'中止':<6}{'暂缓':<6}{'疑点／盗用':<10}{'误伤':<6}{'冒名净收益'}")
    for mode in MODES:
        used = False
        stat = {"中止": 0, "暂缓": 0, "疑点": 0, "盗用": 0, "拒": 0}
        harm = 0
        for name, book, nums in EVENTS:
            # e4 复用：把"凭据已被用过"置为真
            reuse = name.startswith("e4")
            d, rec = judge(mode, book, nums, used and reuse)
            if d == "中止" and not book:
                harm += 1                          # 无实名的中止 = 误杀
            if d == "盗用":
                harm += 1                          # 把真权利人判成盗用 = 误伤
            if reuse and d == "中止":
                stat["中止"] += 0                  # 盗用者拿到中止，不计（下面单独看）
            stat[d] += 1
            if nums:
                used = True
        gain = "杀得掉" if harm else "杀不掉"
        print(f"{mode:<20}{stat['中止']:<7}{stat['暂缓']:<7}{stat['疑点'] + stat['盗用']:<12}"
              f"{harm:<7}{gain}")

    print("\n读法：")
    print("  A 只看名字 → 冒名者一票就能把提案杀死，且不可恢复。冒名净收益最大。")
    print("  B 加'复算三数' → 三数是公告上的公开事实，冒名者读一遍原件就会算；")
    print("     更糟的是三数不唯一（同一宗地上的人算出同一组），'同一凭据只用一次'会先把真权利人打成盗用。")
    print("  C 承认没有外部核验方 → 无实名的异议只能暂缓（可恢复），有登记簿号的才中止。")
    print("     冒名最坏后果从'提案被杀死'降为'提案被拖住等核'，冒名的净收益归零。")
    print("\n代价：C 里没有登记簿号的人（比如真正的农户个人）也只能暂缓——通道变慢，但不会被冒名者当成刀。")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
