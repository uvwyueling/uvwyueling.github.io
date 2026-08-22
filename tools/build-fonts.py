#!/usr/bin/env python3
"""从 Google Fonts 的 &text= 子集接口拉取本站需要的 woff2 子集。

用法：
    python3 tools/collect-chars.py      # 先抽字符集
    python3 tools/build-fonts.py        # 下载到 build/fonts/ 并报体积
    python3 tools/build-fonts.py --install   # 再校验覆盖率并装进 fonts/

为什么要有这个脚本：子集只含**当前文案**用到的字形。以后改了中文文案，
新字会掉到系统字体。改完文案重跑这两条命令即可。

注意 fonts/noto-*.woff2 和 fonts.css 是 data-viz-studio-skill.html 在用的，
本脚本不碰它们。
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARS = os.path.join(ROOT, "build", "chars")
OUT = os.path.join(ROOT, "build", "fonts")
FONTS = os.path.join(ROOT, "fonts")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# (输出名前缀, Google family 规格, 用哪份字符集)
# 必须带现代 Chrome UA，否则 Google 会退回发 ttf 而不是 woff2。
JOBS = [
    ("fraunces",    "Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600", "perception.txt"),
    ("spacemono",   "Space Mono:wght@400;700",                             "perception.txt"),
    ("notoserifsc", "Noto Serif SC:wght@500;600",                          "perception.txt"),
    ("notosanssc",  "Noto Sans SC:wght@300;400;500",                       "perception.txt"),
    ("hanken",      "Hanken Grotesk:wght@400;500;600",                     "hanken-union.txt"),
]


def fetch_css(family, text):
    r = subprocess.run(
        ["curl", "-sS", "--get", "-H", f"User-Agent: {UA}", "--fail",
         "--data-urlencode", f"family={family}",
         "--data-urlencode", f"text={text}",
         "--data-urlencode", "display=swap",
         "https://fonts.googleapis.com/css2"],
        capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"取 CSS 失败 [{family}]: {r.stderr.strip()}")
    return r.stdout


def parse(css):
    """返回 [(weight, url)]，顺序即 CSS 中出现顺序。"""
    out = []
    for block in css.split("@font-face")[1:]:
        w = re.search(r"font-weight:\s*([\d ]+);", block)
        u = re.search(r"src:\s*url\((\S+?)\)", block)
        if w and u:
            out.append((w.group(1).strip(), u.group(1)))
    return out


def download(url, path):
    r = subprocess.run(["curl", "-sS", "--fail", "-H", f"User-Agent: {UA}",
                        "-o", path, url], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"下载失败 {path}: {r.stderr.strip()}")
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true",
                    help="校验覆盖率后装进 fonts/")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    texts = {n: open(os.path.join(CHARS, n), encoding="utf-8").read()
             for n in {j[2] for j in JOBS}}

    total = 0
    manifest = []          # (文件名, 覆盖的字重列表, 字节数, 用的字符集)
    for prefix, family, textfile in JOBS:
        faces = parse(fetch_css(family, texts[textfile]))
        if not faces:
            sys.exit(f"没解析出 @font-face：{family}")

        # 同一个 URL 说明 Google 发的是可变字体，一个文件覆盖多个字重 —— 去重
        by_url = {}
        for w, u in faces:
            by_url.setdefault(u, []).append(w)

        for i, (url, weights) in enumerate(by_url.items()):
            if len(by_url) == 1:
                name = f"{prefix}-var.woff2" if len(weights) > 1 else f"{prefix}-{weights[0]}.woff2"
            else:
                name = f"{prefix}-{weights[0]}.woff2"
            path = os.path.join(OUT, name)
            size = download(url, path)
            total += size
            manifest.append((name, weights, size, textfile))

    w = max(len(m[0]) for m in manifest)
    print(f"{'文件'.ljust(w)}  {'覆盖字重':<14} {'体积':>9}   字符集")
    print("-" * (w + 44))
    for name, weights, size, tf in manifest:
        print(f"{name.ljust(w)}  {','.join(weights):<14} {size/1024:8.1f}K   {tf}")
    print("-" * (w + 44))
    print(f"{'合计'.ljust(w)}  {'':<14} {total/1024:8.1f}K")

    if args.install:
        install(manifest, texts)


def install(manifest, texts):
    from fontTools.ttLib import TTFont

    print("\n=== 覆盖率校验 ===")
    ok = True
    for name, _weights, _size, textfile in manifest:
        cmap = set(TTFont(os.path.join(OUT, name)).getBestCmap())
        need = texts[textfile]
        # 拉丁字体本来就没有汉字，只校验它「该有」的部分：
        # 即该字体 cmap 与需求集的交集之外，不能有需求集里属于本字体脚本范围的漏字。
        miss = [c for c in need if ord(c) not in cmap]
        cjk_miss = [c for c in miss if 0x4E00 <= ord(c) <= 0x9FFF]
        latin_miss = [c for c in miss if c.isascii()]
        flag = "OK"
        if name.startswith(("notoserifsc", "notosanssc")) and (cjk_miss or latin_miss):
            flag, ok = "缺字!", False
        elif name.startswith(("fraunces", "spacemono", "hanken")) and latin_miss:
            flag, ok = "缺字!", False
        print(f"  {name:<24} 字形 {len(cmap):>4}  漏 ASCII {len(latin_miss):>2}  "
              f"漏汉字 {len(cjk_miss):>3}  {flag}")
        if flag != "OK":
            print(f"      缺: {''.join(miss[:60])}")

    # hanken-var.woff2 是首页也在用的文件，覆盖它有回归风险。
    # 真正要守的不变式不是「新 cmap ⊇ 旧 cmap」——旧子集可能本来就多带了没人用的
    # 字形（实测确实多带了一个 ©）。要守的是：**掉的每个字形，都没有任何页面在用**。
    old = os.path.join(FONTS, "hanken-var.woff2")
    new = next((m[0] for m in manifest if m[0].startswith("hanken")), None)
    if new and os.path.exists(old):
        o = set(TTFont(old).getBestCmap())
        n = set(TTFont(os.path.join(OUT, new)).getBestCmap())
        lost = sorted(o - n)
        used = set(texts["hanken-union.txt"])
        still_used = [chr(c) for c in lost if chr(c) in used]
        print(f"\n  hanken 覆盖首页校验: 旧 {len(o)} 字形 -> 新 {len(n)} 字形")
        if lost:
            print(f"      掉了 {len(lost)} 个: {''.join(chr(c) for c in lost)}"
                  f"（均未被任何页面使用）" if not still_used else "")
        if still_used:
            print(f"      有页面在用却掉了: {''.join(still_used)}  回归!")
            ok = False
        else:
            print("      OK — 没有任何在用字形丢失")

    if not ok:
        sys.exit("\n校验未通过，未安装。")

    print("\n=== 安装到 fonts/ ===")
    import shutil
    for name, _w, _s, _t in manifest:
        dst = os.path.join(FONTS, "hanken-var.woff2" if name.startswith("hanken") else name)
        shutil.copy2(os.path.join(OUT, name), dst)
        print(f"  -> fonts/{os.path.basename(dst)}")


if __name__ == "__main__":
    main()
