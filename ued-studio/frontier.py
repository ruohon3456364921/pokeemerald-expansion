# -*- coding: utf-8 -*-
"""对战开拓区数据读写：gBattleFrontierMons / gBattleFrontierTrainers / FRONTIER_MONS_* 池。

设计原则：
  * 只做行级替换，绝不动相邻区块；
  * 解析不了的行一律视为「不属于我们」，原样保留；
  * 写回时保持原有的缩进、逗号与对齐风格。
"""
from __future__ import annotations

import re

MONS_FILE = "src/data/battle_frontier/battle_frontier_mons.h"
TRAINERS_FILE = "src/data/battle_frontier/battle_frontier_trainers.h"
POOLS_FILE = "src/data/battle_frontier/battle_frontier_trainer_mons.h"

MON_START = re.compile(r'^\s*\[(FRONTIER_MON_[A-Z0-9_]+)\]\s*=\s*\{\s*$')
TRAINER_START = re.compile(r'^\s*\[(FRONTIER_TRAINER_[A-Z0-9_]+)\]\s*=\s*\{\s*$')
BLOCK_END = re.compile(r'^\s*\},\s*$')
FIELD = re.compile(r'^(\s*)\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)(,?)\s*$')
POOL_DEF = re.compile(r'^#define\s+(FRONTIER_MONS_[A-Z0-9_]+)\s*\\\s*$')
FUNC_POOL_DEF = re.compile(r'^#define\s+(FRONTIER_MONS_[A-Z0-9_]+)\s*\(([^)]*)\)\s*\\\s*$')
POOL_LINE = re.compile(r'^\s*((?:-1)|(?:FRONTIER_MONS?_[A-Z0-9_]+))\s*,?\s*\\?\s*$')
EV_RE = re.compile(r'TRAINER_PARTY_EVS\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,'
                   r'\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
NAME_RE = re.compile(r'_\(\s*"([^"]*)"\s*\)')
BRACE_RE = re.compile(r'\{([^{}]*)\}')

MON_FIELDS = ("species", "moves", "heldItem", "ev", "nature", "ball")
MON_OPTIONAL = ("ability",)   # 可选字段：没有这一行时由设施逻辑随机合法特性
MONS_CONST_FILE = "include/constants/battle_frontier_mons.h"


def split_lines(text: str):
    return text.split("\n")


def _fields(lines, start, end):
    out = []
    for idx in range(start + 1, end):
        m = FIELD.match(lines[idx])
        if not m:
            continue
        indent, name, value, comma = m.groups()
        out.append({"name": name, "value": value.strip(), "comma": comma == ",",
                    "indent": indent, "line": idx})
    return out


# ------------------------------------------------------------------ mons

def read_mons(text: str):
    lines = split_lines(text)
    out = []
    i = 0
    while i < len(lines):
        m = MON_START.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not BLOCK_END.match(lines[j]):
            j += 1
        out.append({"symbol": m.group(1), "start": i, "end": j,
                    "fields": _fields(lines, i, j)})
        i = j + 1
    return out


def _field_map(block):
    return {f["name"]: f for f in block["fields"]}


def parse_moves(value: str):
    m = BRACE_RE.search(value)
    if not m:
        return []
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


def parse_ev(value: str):
    m = EV_RE.search(value)
    return [int(x) for x in m.groups()] if m else None


def mon_view(block):
    fm = _field_map(block)
    get = lambda k: (fm.get(k) or {}).get("value", "")
    return {
        "symbol": block["symbol"],
        "species": get("species"),
        "moves": parse_moves(get("moves")),
        "heldItem": get("heldItem"),
        "ev": parse_ev(get("ev")) or [0, 0, 0, 0, 0, 0],
        "nature": get("nature"),
        "ball": get("ball"),
        "ability": get("ability"),
        "hasAbility": "ability" in fm,
        "editable": all(k in fm for k in MON_FIELDS),
    }


def format_ev(evs):
    return "TRAINER_PARTY_EVS(%s)" % ", ".join(str(int(x)) for x in evs)


def apply_mon_changes(text: str, symbol: str, changes: dict) -> str:
    lines = split_lines(text)
    block = next((b for b in read_mons(text) if b["symbol"] == symbol), None)
    if block is None:
        raise KeyError("找不到开拓区宝可梦 %s" % symbol)
    fm = _field_map(block)
    ability = changes.get("ability")
    for key, value in changes.items():
        if key == "ability":
            continue
        field = fm.get(key)
        if field is None:
            raise KeyError("开拓区宝可梦 %s 没有字段 %s" % (symbol, key))
        lines[field["line"]] = "%s.%s = %s%s" % (
            field["indent"], key, value, "," if field["comma"] else "")
    if ability is not None:
        _set_ability(lines, fm, ability)
    return "\n".join(lines)


def _set_ability(lines, fm, value):
    value = (value or "").strip()
    unset = value in ("", "0", "ABILITY_NONE")
    field = fm.get("ability")
    if field is not None:
        if unset:
            del lines[field["line"]]
        else:
            lines[field["line"]] = "%s.ability = %s," % (field["indent"], value)
        return
    if unset:
        return
    anchor = fm.get("heldItem") or fm.get("species")
    if anchor is None:
        return
    lines.insert(anchor["line"] + 1,
                 "%s.ability = %s," % (anchor["indent"], value))


def format_mon_entry(symbol, view) -> str:
    """按文件既有风格生成一条新的开拓区宝可梦条目（含 4 空格缩进与尾逗号）。"""
    moves = list(view.get("moves") or [])
    while len(moves) < 4:
        moves.append("MOVE_NONE")
    fields = [
        ("species", view.get("species") or "SPECIES_NONE"),
        ("moves", "{%s}" % ", ".join(moves[:4])),
        ("heldItem", view.get("heldItem") or "ITEM_NONE"),
        ("ev", format_ev(view.get("ev") or [0, 0, 0, 0, 0, 0])),
        ("nature", view.get("nature") or "NATURE_HARDY"),
        ("ball", view.get("ball") or "BALL_POKE"),
    ]
    ability = (view.get("ability") or "").strip()
    if ability not in ("", "0", "ABILITY_NONE"):
        fields.append(("ability", ability))
    out = ["    [%s] = {" % symbol]
    for i, (k, v) in enumerate(fields):
        out.append("        .%s = %s%s" % (k, v, "," if i < len(fields) - 1 else ""))
    out.append("    },")
    return "\n".join(out)


def append_mon(text, entry: str) -> str:
    lines = split_lines(text)
    idx = max((i for i, l in enumerate(lines) if l.strip() == "};"), default=None)
    if idx is None:
        raise ValueError("找不到数组结尾 };")
    # 原最后一条条目通常没有尾逗号（它在 }; 之前），补上
    prev = idx - 1
    while prev >= 0 and not lines[prev].strip():
        prev -= 1
    if prev >= 0 and lines[prev].strip() == "}" :
        lines[prev] = lines[prev].rstrip() + ","
    lines[idx:idx] = entry.split("\n")
    return "\n".join(lines)


def add_mon_const(text, symbol, index=None):
    """在常量头文件里插入一条 FRONTIER_MON_ 定义并把 NUM_FRONTIER_MONS 加一。"""
    lines = split_lines(text)
    for i, line in enumerate(lines):
        if line.startswith("#define NUM_FRONTIER_MONS"):
            total = int(line.split()[-1])
            idx = total if index is None else index
            lines[i] = "#define NUM_FRONTIER_MONS           %d" % (total + 1)
            lines.insert(i, "#define %s %d" % (symbol.ljust(27)[:27] if len(symbol) < 27 else symbol, idx))
            return "\n".join(lines), idx
    raise ValueError("找不到 #define NUM_FRONTIER_MONS")


def validate_mon_change(key: str, value: str):
    """只做形状校验；成员是否合法由调用方用常量表核对。"""
    if key == "species":
        if not re.match(r'^SPECIES_[A-Z0-9_]+$', value):
            raise ValueError("物种必须是 SPECIES_XXX")
    elif key == "heldItem":
        if not re.match(r'^ITEM_[A-Z0-9_]+$', value):
            raise ValueError("道具必须是 ITEM_XXX")
    elif key == "nature":
        if not re.match(r'^NATURE_[A-Z0-9_]+$', value):
            raise ValueError("性格必须是 NATURE_XXX")
    elif key == "ball":
        if not re.match(r'^BALL_[A-Z0-9_]+$', value):
            raise ValueError("球种必须是 BALL_XXX")
    elif key == "moves":
        moves = parse_moves(value)
        if len(moves) != 4:
            raise ValueError("招式必须是 4 个 MOVE_XXX，缺位用 MOVE_NONE")
        for mv in moves:
            if not re.match(r'^MOVE_[A-Z0-9_]+$', mv):
                raise ValueError("招式名不合法: %s" % mv)
    elif key == "ability":
        if value not in ("", "0", "ABILITY_NONE") and \
                not re.match(r'^ABILITY_[A-Z0-9_]+$', value):
            raise ValueError("特性必须是 ABILITY_XXX 或留空")
    elif key == "ev":
        evs = parse_ev(value)
        if evs is None:
            raise ValueError("努力值必须是 TRAINER_PARTY_EVS(a, b, c, d, e, f)")
        for v in evs:
            if not 0 <= v <= 255:
                raise ValueError("单项努力值超出 0-255: %d" % v)
    else:
        raise ValueError("不支持的开拓区字段: %s" % key)


# --------------------------------------------------------------- trainers

def read_trainers(text: str):
    lines = split_lines(text)
    out = []
    i = 0
    while i < len(lines):
        m = TRAINER_START.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not BLOCK_END.match(lines[j]):
            j += 1
        fields = _fields(lines, i, j)
        fm = {f["name"]: f for f in fields}
        item = {"symbol": m.group(1), "start": i, "end": j,
                "facilityClass": (fm.get("facilityClass") or {}).get("value", ""),
                "name": "", "pool": None, "monSet": None,
                "monSetKind": None, "monSetLine": None,
                "monSetIndent": "        ", "members": []}
        if "trainerName" in fm:
            nm = NAME_RE.search(fm["trainerName"]["value"])
            item["name"] = nm.group(1) if nm else fm["trainerName"]["value"]
        if "monSet" in fm:
            f = fm["monSet"]
            item["monSetLine"] = f["line"]
            item["monSetIndent"] = f["indent"]
            inner = re.search(r'\)\s*\{(.*)\}\s*$', f["value"])
            body = inner.group(1).strip() if inner else ""
            item["monSet"] = body
            toks = [x.strip() for x in body.split(",") if x.strip()]
            if re.match(r'^[A-Z_][A-Z0-9_]*\s*\(', body):
                # 形如 FRONTIER_MONS_XXX(SPECIES) 的函数式宏，展开结果由宏参数决定
                item["monSetKind"] = "macro"
                item["pool"] = body
            elif len(toks) == 1 and re.match(r'^FRONTIER_MONS_[A-Z0-9_]+$', toks[0]):
                item["monSetKind"] = "pool"
                item["pool"] = toks[0]
            else:
                item["monSetKind"] = "inline"
                item["members"] = toks
        out.append(item)
        i = j + 1
    return out


def apply_trainer_inline(text: str, symbol: str, members) -> str:
    """把训练家的 monSet 换成内联列表（从共用池拆出来单独改）。"""
    lines = split_lines(text)
    t = next((x for x in read_trainers(text) if x["symbol"] == symbol), None)
    if t is None:
        raise KeyError("找不到开拓区训练家 %s" % symbol)
    if t["monSetLine"] is None:
        raise KeyError("%s 没有 monSet 字段" % symbol)
    for m in members:
        if not re.match(r'^FRONTIER_MON_[A-Z0-9_]+$', m):
            raise ValueError("池成员必须是 FRONTIER_MON_XXX: %r" % m)
    if not members:
        raise ValueError("至少要保留一只宝可梦")
    lines[t["monSetLine"]] = "%s.monSet = (const u16[]){%s}" % (
        t["monSetIndent"], ", ".join(members))
    return "\n".join(lines)


# ------------------------------------------------------------------ pools

def read_pools(text: str):
    lines = split_lines(text)
    out = []
    i = 0
    while i < len(lines):
        m = POOL_DEF.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        members, j = [], i + 1
        while j < len(lines):
            pm = POOL_LINE.match(lines[j])
            if not pm:
                break
            tok = pm.group(1)
            if tok == "-1":
                j += 1
                break
            members.append(tok)
            j += 1
        out.append({"name": name, "start": i, "end": j - 1, "members": members})
        i = j
    return out


def format_pool(text: str, name: str, members) -> str:
    lines = split_lines(text)
    pool = next((p for p in read_pools(text) if p["name"] == name), None)
    if pool is None:
        raise KeyError("找不到池 %s" % name)
    if not members:
        raise ValueError("池里至少要保留一只宝可梦")
    for m in members:
        # 允许保留原有的嵌套池宏（FRONTIER_MONS_*），新增成员由上层限制为 FRONTIER_MON_*
        if not re.match(r'^FRONTIER_MONS?_[A-Z0-9_]+$', m):
            raise ValueError("池成员必须是 FRONTIER_MON_XXX: %r" % m)
    # 对齐列沿用原文件（不同池的反斜杠列并不一致），没有可参照的就用 32
    cols = [ln.index("\\") for ln in lines[pool["start"] + 1:pool["end"] + 1]
            if "\\" in ln and ln.strip() != "-1"]
    target = 32
    if cols and len(set(cols)) == 1:
        target = cols[0]
    orig_body = lines[pool["start"] + 1:pool["end"] + 1]
    orig_last = orig_body[-1] if orig_body else ""
    body = []
    for m in members:
        line = ("    " + m + ",").ljust(target)
        if len(line) <= target:
            line += "\\"
        else:
            line += " \\"
        body.append(line)
    # 收尾成员若没变，原样沿用（嵌套池宏那行不带逗号/反斜杠，重排会破坏语意）
    if orig_last.strip() and not orig_last.strip().startswith("-1") \
            and members and orig_last.strip().split()[0].strip(",") == members[-1]:
        body[-1] = orig_last
    head = lines[pool["start"]]
    has_tail = lines[pool["end"]].strip() == "-1"
    lines[pool["start"]:pool["end"] + 1] = [head] + body + (["    -1"] if has_tail else [])
    return "\n".join(lines)


# ------------------------------------------------- 函数式宏（带物种参数）

def read_func_pools(text: str):
    """形如 #define FRONTIER_MONS_PSYCHIC_2(species1, species2) ... 的池。"""
    lines = split_lines(text)
    out = {}
    i = 0
    while i < len(lines):
        m = FUNC_POOL_DEF.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        params = [x.strip() for x in m.group(2).split(",") if x.strip()]
        toks, j = [], i + 1
        while j < len(lines) and lines[j].rstrip().endswith("\\"):
            toks.extend(x.strip() for x in lines[j].rstrip()[:-1].split(","))
            j += 1
        if j < len(lines):
            toks.extend(x.strip() for x in lines[j].split(","))
            j += 1
        out[name] = {"params": params,
                     "members": [t for t in toks if t and t != "-1"]}
        i = j
    return out


def parse_call(call: str):
    """FRONTIER_MONS_X(A, B) -> ("FRONTIER_MONS_X", ["A", "B"])"""
    m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*\(([^()]*)\)$', call.strip())
    if not m:
        return None, []
    args = [a.strip() for a in m.group(2).split(",") if a.strip()]
    return m.group(1), args


def expand_func_pool(call: str, func_pools: dict, obj_pools: dict, depth=0):
    """把函数式宏调用展开成 FRONTIER_MON_* 列表；展不开就返回 None。"""
    name, args = parse_call(call)
    spec = func_pools.get(name)
    if spec is None or len(args) != len(spec["params"]) or depth > 4:
        return None
    binding = dict(zip(spec["params"], args))
    mapper = {p["name"]: p["members"] for p in obj_pools}
    out = []
    for tok in spec["members"]:
        if "##" in tok:
            parts = [binding.get(x, x) for x in tok.split("##")]
            tok = "".join(parts)
        if tok.startswith("FRONTIER_MON_"):
            out.append(tok)
        elif tok.startswith("FRONTIER_MONS_"):
            sub = expand_func_pool(tok, func_pools, obj_pools, depth + 1)
            if sub is None:
                sub = [x for x in mapper.get(tok, [])]
            out.extend(sub)
    return out or None
