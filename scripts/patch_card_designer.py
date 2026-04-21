# -*- coding: utf-8 -*-
"""Bytes-level patch for card_designer.py to fix the '23살이 → 3살이' bug."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "src", "agents", "card_designer.py")

with open(path, "rb") as f:
    content = f.read()

# ── Patch 1: _strip_prefix operator precedence ─────────────────────────────
old1 = (
    b'        if cat.startswith("L") or cat.startswith("N") and i > 0:\n'
    b'            result = line[i:].strip()\n'
    b'            break\n'
    b'        if "\\uAC00" <= ch <= "\\uD7A3" or "\\u3131" <= ch <= "\\u3163":\n'
    b'            result = line[i:].strip()\n'
    b'            break\n'
    b'        i += 1\n'
)
new1 = (
    b'        if cat.startswith("L") or "\\uAC00" <= ch <= "\\uD7A3" or "\\u3131" <= ch <= "\\u3163":\n'
    b'            result = line[i:].strip()\n'
    b'            break\n'
    b'        if cat.startswith("N"):\n'
    b'            j = i\n'
    b'            while j < len(line) and _ud.category(line[j]).startswith("N"):\n'
    b'                j += 1\n'
    b'            if j < len(line) and line[j] in ".\\u3002)\\uff09 \\t":\n'
    b'                i = j\n'
    b'                continue\n'
    b'            result = line[i:].strip()\n'
    b'            break\n'
    b'        i += 1\n'
)

assert old1 in content, "PATCH1 target not found"
content = content.replace(old1, new1, 1)
print("OK patch1 _strip_prefix")

# ── Patch 2: _BULLET_START require punctuation after digits ────────────────
# Original bytes: r"^[\d①-⑩\-\*•]|..."
# ① = \xe2\x91\xa0  ⑩ = \xe2\x91\xa9  • = \xe2\x80\xa2
# ❌ = \xe2\x9d\x8c  ✅ = \xe2\x9c\x85  📌 = \xf0\x9f\x93\x8c
# 🔥 = \xf0\x9f\x94\xa5  💡 = \xf0\x9f\x92\xa1
old2 = (
    b'        r"^[\\d'
    b'\xe2\x91\xa0-\xe2\x91\xa9'
    b'\\-\\*'
    b'\xe2\x80\xa2'
    b']|[\\U0001F51F-\\U0001F525]|['
    b'\xe2\x9d\x8c'
    b'\xe2\x9c\x85'
    b'\xf0\x9f\x93\x8c'
    b'\xf0\x9f\x94\xa5'
    b'\xf0\x9f\x92\xa1'
    b']",'
)
new2 = (
    b'        r"^\\d+(?=[.\\u3002)\\uff09\\]\\s])|^['
    b'\xe2\x91\xa0-\xe2\x91\xa9'
    b'\\-\\*'
    b'\xe2\x80\xa2'
    b']|[\\U0001F51F-\\U0001F525]|['
    b'\xe2\x9d\x8c'
    b'\xe2\x9c\x85'
    b'\xf0\x9f\x93\x8c'
    b'\xf0\x9f\x94\xa5'
    b'\xf0\x9f\x92\xa1'
    b']",'
)

assert old2 in content, "PATCH2 target not found"
content = content.replace(old2, new2, 1)
print("OK patch2 _BULLET_START")

with open(path, "wb") as f:
    f.write(content)
print("DONE file written")
