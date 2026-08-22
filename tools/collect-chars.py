#!/usr/bin/env python3
"""抽取页面用到的唯一字符，供字体子集化使用。

刻意取「整个文件」而不是「可见文本」——多带几个 ASCII 字形几乎不要钱，
漏字则会导致线上掉字。JS 注入的文本（如「机器看见」）就在 <script> 里，
按可见文本抽会漏掉。

输出到 build/chars/：
  perception.txt   感知页全部字符      -> Fraunces / Space Mono / Noto Serif SC / Noto Sans SC
  hanken-union.txt 感知页 ∪ 首页 的非 CJK -> hanken-var.woff2（两页共用，必须是并集）
"""
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "chars")

PERCEPTION = ["visual-perception-machine.html"]
INDEX = ["index.html", "assets/app.js"]


def decode_escapes(rel, text):
    """把「字面量里看不见、渲染时才出现」的字符还原出来。

    两个真实存在的坑：
      - HTML 实体：&copy; 这种写法，源文件里根本没有 © 这个字符
      - assets/app.js 是 esbuild 压缩产物，中文和符号被转成了 \\uXXXX

    多解出来的字符（比如正则里的 Unicode 区间边界 \\u4E00-\\u9FFF）不要紧：
    Google 的 &text= 只会返回字体里真实存在的字形，多要不会变大多少。
    漏字才是会上线的 bug。
    """
    if rel.endswith((".html", ".htm")):
        text = html.unescape(text)
    if rel.endswith(".js"):
        text += "".join(
            chr(int(m, 16)) for m in re.findall(r"\\u([0-9a-fA-F]{4})", text))
        text += "".join(
            chr(int(m, 16)) for m in re.findall(r"\\x([0-9a-fA-F]{2})", text))
    return text


def chars_of(*rel_paths):
    got = set()
    for rel in rel_paths:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            sys.exit(f"缺文件：{rel}")
        with open(p, encoding="utf-8") as f:
            got |= set(decode_escapes(rel, f.read()))
    # 丢掉空白和不可打印，其余全留
    return {c for c in got if c.isprintable() and not c.isspace()}


def is_cjk(c):
    o = ord(c)
    return (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
            or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F)


def write(name, chars):
    s = "".join(sorted(chars))
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    n_cjk = sum(1 for c in s if is_cjk(c))
    print(f"{name:<18} {len(s):>4} 字符（汉字 {n_cjk}，其余 {len(s) - n_cjk}）"
          f"  URL 编码后约 {len(s.encode('utf-8')) * 3 // 1024 + 1} KB")
    return s


def main():
    os.makedirs(OUT, exist_ok=True)
    perception = chars_of(*PERCEPTION)
    union = {c for c in perception | chars_of(*INDEX) if not is_cjk(c)}

    write("perception.txt", perception)
    write("hanken-union.txt", union)

    # 这条不变式是首页不回归的前提：并集必须真的包含感知页的非 CJK 字符
    assert {c for c in perception if not is_cjk(c)} <= union, "并集没盖住感知页字符"
    print("\n并集校验通过")


if __name__ == "__main__":
    main()
