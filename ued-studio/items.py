"""道具表（src/data/items.h）的解析与定向改写。

不用原生库写道具：它写物种时就出过偏移 bug，道具这边我们只做
"定位成员 → 替换值文本"，其余字节一律不动，改完用快照校验兜底。
"""
from __future__ import annotations

import bisect
import os
import re
from typing import Dict, List, Tuple

ITEMS_FILE = "src/data/items.h"
CONST_ITEMS = "include/constants/items.h"
CONST_ITEM = "include/constants/item.h"
HOLD_EFFECTS = "include/constants/hold_effects.h"

BLOCK_START = re.compile(r"\[(ITEM_[A-Z0-9_]+)\]\s*=\s*\n?\s*\{")
MEMBER_START = re.compile(r"^(\s*)\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
PREPROC = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b\s*(.*)$")


def _brace_scan(text: str, open_idx: int) -> int:
    """从 '{' 处找配对的 '}'，跳过字符串与注释。"""
    depth = 0
    i = open_idx
    quote = None
    line_comment = block_comment = False
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if c == "\n":
                line_comment = False
        elif block_comment:
            if c == "*" and nxt == "/":
                block_comment = False
                i += 1
        elif quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        else:
            if c == "/" and nxt == "/":
                line_comment = True
                i += 1
            elif c == "/" and nxt == "*":
                block_comment = True
                i += 1
            elif c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def iter_items(text: str):
    """产出 (symbol, block_start, body_start, body_end, block_end)。"""
    pos = 0
    while True:
        m = BLOCK_START.search(text, pos)
        if not m:
            return
        open_idx = text.index("{", m.end() - 1)
        close = _brace_scan(text, open_idx)
        if close < 0:
            pos = m.end()
            continue
        yield (m.group(1), m.start(), open_idx + 1, close, close + 1)
        pos = close + 1


def _skip_value(text: str, i: int) -> int:
    """从值起点扫到该成员结尾逗号之后，返回结尾位置（不含逗号）。"""
    depth = 0
    quote = None
    line_comment = block_comment = False
    j = i
    while j < len(text):
        c = text[j]
        nxt = text[j + 1] if j + 1 < len(text) else ""
        if line_comment:
            if c == "\n":
                line_comment = False
        elif block_comment:
            if c == "*" and nxt == "/":
                block_comment = False
                j += 1
        elif quote:
            if c == "\\":
                j += 1
            elif c == quote:
                quote = None
        else:
            if c == "/" and nxt == "/":
                line_comment = True
                j += 1
            elif c == "/" and nxt == "*":
                block_comment = True
                j += 1
            elif c in "\"'":
                quote = c
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == "," and depth == 0:
                return j
        j += 1
    return len(text)


def parse_members(text: str, body_start: int, body_end: int,
                  newlines: List[int] | None = None) -> List[dict]:
    """块内全部 `.field = value,` 成员，带源码偏移与所在 #if 分支说明。"""
    if newlines is None:
        newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    body = text[body_start:body_end]
    # 逐行建立 (绝对行首, 行文本)，成员值可能跨行，用二分跳到成员结束后
    line_starts: List[int] = []
    pos = 0
    for line in body.splitlines(keepends=True):
        line_starts.append(body_start + pos)
        pos += len(line)
    if not line_starts:
        return []

    members: List[dict] = []
    stack: List[str] = []
    idx = 0
    total = len(line_starts)
    while idx < total:
        line_start = line_starts[idx]
        line_end = line_starts[idx + 1] if idx + 1 < total else body_end
        line = text[line_start:line_end]
        m = PREPROC.match(line)
        if m:
            kind, rest = m.group(1), m.group(2).strip()
            if kind in ("if", "ifdef", "ifndef"):
                stack.append(rest or kind)
            elif kind == "elif" and stack:
                stack[-1] = "elif " + rest
            elif kind == "else" and stack:
                stack[-1] = "else"
            elif kind == "endif" and stack:
                stack.pop()
            idx += 1
            continue
        mm = MEMBER_START.match(line.rstrip("\n"))
        if not mm:
            idx += 1
            continue
        value_start = line_start + mm.start(3)
        value_end = _skip_value(text, value_start)
        members.append({
            "name": mm.group(2),
            "value": text[value_start:value_end].strip(),
            "start": value_start,
            "end": value_end,
            "branch": stack[0] if stack else "",
            "line": bisect.bisect_left(newlines, value_start) + 1,
        })
        # 跳到该值结束的那一行之后
        idx = bisect.bisect_right(line_starts, value_end)
    return members


def read_items(text: str) -> List[dict]:
    out = []
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]
    for symbol, block_start, body_start, body_end, block_end in iter_items(text):
        out.append({
            "symbol": symbol,
            "block_start": block_start,
            "block_end": block_end,
            "members": parse_members(text, body_start, body_end, newlines),
        })
    return out


def _string_of(value: str):
    """从 ITEM_NAME("…") / COMPOUND_STRING(…) / 裸字符串里取出可显示文本。"""
    m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\((.*)\)$", value, re.S)
    inner = m.group(1) if m else value
    parts = []
    for chunk in re.findall(r'"((?:[^"\\]|\\.)*)"', inner):
        parts.append(chunk)
    if not parts:
        return None
    raw = "".join(parts)
    raw = raw.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _quote_string(text: str, indent: str = "\t\t\t", multiline: bool = False) -> str:
    """按 items.h 的既有排版还原字符串字面量。"""
    lines = text.split("\n")
    pieces = []
    for idx, line in enumerate(lines):
        esc = line.replace("\\", "\\\\").replace('"', '\\"')
        suffix = "\\n" if idx < len(lines) - 1 else ""
        pieces.append('"%s%s"' % (esc, suffix))
    if not multiline:
        return pieces[0]
    return "\n" + "\n".join(indent + p for p in pieces)


def field_view(member: dict) -> dict:
    name, value = member["name"], member["value"]
    if name in ("name", "description"):
        text = _string_of(value)
        if text is None:
            return {"kind": "raw", "text": value}
        return {"kind": "text" if name == "name" else "multiline", "text": text}
    if re.fullmatch(r"-?\d+", value):
        return {"kind": "number", "text": value}
    return {"kind": "raw", "text": value}


def apply_changes(text: str, symbol: str, changes: Dict[str, str],
                  blocks: List[dict] | None = None) -> str:
    """按成员名替换值，返回新文本。changes 若带 "@序号" 表示同名成员的第几处（0 起）。"""
    if blocks is None:
        blocks = read_items(text)
    block = {b["symbol"]: b for b in blocks}.get(symbol)
    if not block:
        raise KeyError("找不到道具条目: %s" % symbol)
    members = block["members"]
    occurrences: Dict[str, List[dict]] = {}
    for m in members:
        occurrences.setdefault(m["name"], []).append(m)

    edits: List[Tuple[int, int, str]] = []
    for key, value in changes.items():
        name, _, idx = key.partition("@")
        hits = occurrences.get(name) or []
        if not hits:
            raise KeyError("道具 %s 没有字段 %s" % (symbol, name))
        try:
            target = hits[int(idx)] if idx else hits[0]
        except (ValueError, IndexError):
            raise KeyError("字段 %s 的第 %s 处不存在" % (name, idx))
        new_value = build_value(name, value, target["value"])
        edits.append((target["start"], target["end"], new_value))

    for start, end, new_value in sorted(edits, reverse=True):
        text = text[:start] + new_value + text[end:]
    return text

# ---------------------------------------------------------------- 取值重建

def build_value(name: str, text: str, old_value: str = "") -> str:
    """把界面上的文本还原成 items.h 里的成员值字符串。"""
    value = (text or "").strip()
    if name == "name":
        if not value:
            raise ValueError("名称不能为空")
        return "ITEM_NAME(%s)" % _quote_string(value)
    if name == "description":
        if not value:
            raise ValueError("说明不能为空")
        return "COMPOUND_STRING(%s)" % _quote_string(value, multiline=True)
    if not value:
        raise ValueError("字段 %s 的值不能为空" % name)
    if "\n" in value or "\r" in value:
        raise ValueError("字段 %s 不支持多行" % name)
    if ";" in value or "/*" in value or "*/" in value:
        raise ValueError("字段 %s 的值含非法字符" % name)
    return value


ENUM_SOURCES = {
    "pocket": ("include/constants/item.h", "Pocket"),
    "itemType": ("include/constants/items.h", "ItemType"),
    "sortType": ("include/item.h", "ItemSortType"),
    "holdEffect": ("include/constants/hold_effects.h", "HoldEffect"),
    "effectItem": ("include/constants/items.h", "EffectItem"),
}

_LABELS = {
    "POCKET_ITEMS": "道具", "POCKET_POKE_BALLS": "精灵球", "POCKET_TM_HM": "招式学习器",
    "POCKET_BERRIES": "树果", "POCKET_KEY_ITEMS": "重要物品",
    "POCKETS_COUNT": "（占位）", "POCKET_DUMMY": "（占位）",
    "ITEM_USE_UNKNOWN": "（未知）", "ITEM_USE_LAUNCH_SCRIPT": "触发脚本",
    "ITEM_USE_PARTY_MENU": "队伍菜单使用", "ITEM_USE_IN_BATTLE": "战斗中直接使用",
    "ITEM_USE_FIELD": "野外使用", "ITEM_USE_CHECK_ONLY": "只能查看",
    "ITEM_USE_PARTY_MENU_FIELD": "队伍/野外两用",
    "HOLD_EFFECT_NONE": "无", "HOLD_EFFECT_RESTORE_HP": "战斗中回复 HP",
    "HOLD_EFFECT_RESTORE_PP": "回复 PP", "HOLD_EFFECT_LEFTOVERS": "吃剩的东西（每回合回血）",
    "HOLD_EFFECT_CHOICE_BAND": "讲究类（锁招加攻）", "HOLD_EFFECT_MACHO_BRACE": "力量护腕类",
    "HOLD_EFFECT_EXP_SHARE": "学习装置", "HOLD_EFFECT_SOUL_DEW": "心之水滴",
    "EFFECT_ITEM_NONE": "无",
}


def read_enums(project: str) -> Dict[str, List[dict]]:
    """从源码里读出枚举成员，供下拉框使用。"""
    out: Dict[str, List[dict]] = {}
    for key, (rel, enum_name) in ENUM_SOURCES.items():
        path = os.path.join(project, rel)
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            out[key] = []
            continue
        items = []
        pattern = re.compile(r"enum\s+(?:PACKED\s+)?%s\s*\{([^}]*)\}" % enum_name)
        m = pattern.search(text)
        if m:
            for line in m.group(1).splitlines():
                mm = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*(?:=[^,]*)?,?", line)
                if not mm:
                    continue
                ident = mm.group(1)
                if ident.endswith("_COUNT"):
                    continue
                items.append({"value": ident, "label": _LABELS.get(ident, "")})
        out[key] = items
    return out

def item_summary(block: dict) -> dict:
    """列表里用的一行摘要。"""
    info = {"symbol": block["symbol"], "name": "", "price": "", "pocket": ""}
    for m in block["members"]:
        if m["name"] == "name" and not info["name"]:
            text = _string_of(m["value"])
            info["name"] = text if text is not None else ""
        elif m["name"] == "price" and not info["price"]:
            info["price"] = m["value"].strip()
        elif m["name"] == "pocket" and not info["pocket"]:
            info["pocket"] = m["value"].strip()
    info["label"] = info["name"] or block["symbol"]
    return info
