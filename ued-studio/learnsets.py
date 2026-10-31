# -*- coding: utf-8 -*-
"""招式表的读取与写回（纯文本/JSON 操作，不经过原生库）。

数据源分三处：
  * 升级招式：src/data/pokemon/level_up_learnsets/gen_*.h   （手写）
  * 蛋招：    src/data/pokemon/egg_moves.h                    （手写）
  * 教学招式：src/data/pokemon/all_learnables.json            （生成 teachable_learnsets.h 的源）

原生库在 GEN_LATEST 配置下把升级招式当作生成物、不给编辑，所以这里自己解析。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Dict, List, Optional

LEVELUP_DIR = os.path.join("src", "data", "pokemon", "level_up_learnsets")
EGG_FILE = os.path.join("src", "data", "pokemon", "egg_moves.h")
LEARNABLES_FILE = os.path.join("src", "data", "pokemon", "all_learnables.json")

LEVELUP_RE = re.compile(r'\b(static\s+const\s+struct\s+LevelUpMove\s+)?(s[A-Za-z0-9_]+\[\])\s*=\s*\{')
LEVEL_MOVE_RE = re.compile(r'LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*(MOVE_[A-Z0-9_]+)\s*\)')
EGG_RE = re.compile(r'\b(s[A-Za-z0-9_]+\[\])\s*=\s*\{')
EGG_MOVE_RE = re.compile(r'^\s*(MOVE_[A-Z0-9_]+)\s*,?\s*$')


def _read(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def _write(path: str, text: str) -> None:
    data = text.encode("utf-8")
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _brace_body(text: str, open_idx: int):
    """从 '{' 开始找到匹配的 '}'，返回 (body_start, body_end)。"""
    depth = 0
    i = open_idx
    quote = None
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        else:
            if c == "/" and nxt == "/":
                j = text.find("\n", i)
                i = j if j > 0 else len(text)
                continue
            if c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
                if depth == 1:
                    start = i + 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return start, i
        i += 1
    return None


BLOCK_NAME_RE = re.compile(r'^s[A-Za-z0-9_]{3,80}$')


def valid_block_name(name) -> bool:
    return isinstance(name, str) and bool(BLOCK_NAME_RE.match(name)) \
        and name.endswith("Learnset")


def find_block(text: str, name: str):
    """按 `sXxxLevelUpLearnset[] = {` 定位块，返回 (body_start, body_end) 或 None。"""
    if not valid_block_name(name):
        return None
    pattern = re.compile(r'\b%s\[\]\s*=\s*' % re.escape(name))
    m = pattern.search(text)
    if not m:
        return None
    open_idx = text.find("{", m.end())
    if open_idx < 0:
        return None
    return _brace_body(text, open_idx)


# ---------------------------------------------------------------- 升级招式

GEN_VALUE_RE = re.compile(r"^#define\s+(GEN_(?:LATEST|\d+))\s+(\S+)", re.M)
CFG_POKEMON = os.path.join("include", "config", "pokemon.h")
CFG_GENERAL = os.path.join("include", "config", "general.h")


def _gen_constants(project: str) -> Dict[str, str]:
    """读 include/config/general.h 的 GEN_x 数值表（GEN_9 8、GEN_LATEST GEN_9 ...）。"""
    table: Dict[str, str] = {}
    path = os.path.join(project, CFG_GENERAL)
    if not os.path.isfile(path):
        return table
    for key, val in GEN_VALUE_RE.findall(_read(path)):
        table[key] = val
    return table


def resolve_gen(project: str, expr: str) -> Optional[int]:
    """把配置项的值（GEN_LATEST / GEN_9 / 9）解析成代数字。"""
    table = _gen_constants(project)
    name = (expr or "").strip()
    for _ in range(8):
        m = re.fullmatch(r"GEN_(\d+)", name)
        if m:
            return int(m.group(1))
        if name.isdigit():
            return int(name)
        nxt = table.get(name)
        if nxt is None:
            return None
        name = nxt.strip()
    return None


def active_gen(project: str) -> Optional[int]:
    """当前工程实际参与编译的升级学习表代数（P_LVL_UP_LEARNSETS）。"""
    path = os.path.join(project, CFG_POKEMON)
    if not os.path.isfile(path):
        return None
    m = re.search(r"^#define\s+P_LVL_UP_LEARNSETS\s+(\S+)", _read(path), re.M)
    if not m:
        return None
    return resolve_gen(project, m.group(1))


def active_levelup_file(project: str) -> Optional[str]:
    gen = active_gen(project)
    if gen is None:
        return None
    path = os.path.join(project, LEVELUP_DIR, "gen_%d.h" % gen)
    return path if os.path.isfile(path) else None


def _levelup_files(project: str) -> List[str]:
    """当前代文件排最前，其余按代数倒序兜底（只用于读取）。"""
    d = os.path.join(project, LEVELUP_DIR)
    if not os.path.isdir(d):
        return []
    names = [n for n in os.listdir(d) if n.endswith(".h")]
    act = active_levelup_file(project)
    act_name = os.path.basename(act) if act else None
    def key(n):
        if n == act_name:
            return (0, 0)
        mm = re.match(r"gen_(\d+)\.h$", n)
        return (1, -int(mm.group(1)) if mm else -99)
    return [os.path.join(d, n) for n in sorted(names, key=key)]


def read_levelup(project: str, block_name: str) -> Optional[dict]:
    if not block_name or not block_name.startswith("s"):
        return None
    for path in _levelup_files(project):
        text = _read(path)
        span = find_block(text, block_name)
        if not span:
            continue
        body = text[span[0]:span[1]]
        moves = [{"level": int(lv), "move": mv} for lv, mv in LEVEL_MOVE_RE.findall(body)]
        act = active_levelup_file(project)
        return {"block": block_name, "file": os.path.relpath(path, project),
                "active": bool(act) and os.path.abspath(path) == os.path.abspath(act),
                "moves": moves, "editable": True}
    return None


def _as_level_move(item) -> Dict[str, object]:
    if isinstance(item, str):
        return {"level": 1, "move": item}
    if isinstance(item, dict):
        return {"level": item.get("level", 1), "move": item.get("move") or item.get("name") or ""}
    return {"level": 1, "move": ""}


def _as_move(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("move") or item.get("name") or ""
    return ""


def _level_value(item: Dict[str, object]) -> int:
    """0 是升级学习表的合法等级（进化/形态专用），只有缺失或空才算 1。"""
    lv = item.get("level", 1)
    if lv is None or lv == "":
        lv = 1
    return int(lv)


def _format_levelup(moves: List[dict]) -> str:
    lines = []
    normalized = [_as_level_move(m) for m in moves]
    ordered = sorted(enumerate(normalized), key=lambda pair: (_level_value(pair[1]), pair[0]))
    for _idx, item in ordered:
        lv = _level_value(item)
        mv = str(item["move"]).strip()
        if not mv.startswith("MOVE_"):
            raise ValueError("招式名不合法: %s" % mv)
        lines.append("    LEVEL_UP_MOVE(%2d, %s)," % (lv, mv))
    lines.append("    LEVEL_UP_END")
    return "\n" + "\n".join(lines) + "\n"


def write_levelup(project: str, block_name: str, moves: List[dict]) -> str:
    if not valid_block_name(block_name):
        raise ValueError("无效的招式块名: %r（该宝可梦可能没有独立的升级招式表）" % block_name)
    if not moves:
        raise ValueError("升级招式不能为空")
    moves = [_as_level_move(m) for m in moves]
    levels = [_level_value(m) for m in moves]
    if min(levels) < 0 or max(levels) > 100:
        raise ValueError("等级必须在 0..100 之间（0 表示进化/形态专用）")
    # 只允许写当前代文件：其余 gen_*.h 被预处理器排除，写进去游戏里不会生效
    target = active_levelup_file(project)
    if target is None:
        raise ValueError("读不到 P_LVL_UP_LEARNSETS 或缺少对应的 level_up_learnsets/gen_*.h，拒绝盲写")
    text = _read(target)
    span = find_block(text, block_name)
    if not span:
        raise ValueError("%s 里没有 %s（当前 P_LVL_UP_LEARNSETS 指向 gen_%s.h，"
                         "写进别的代文件不会生效）"
                         % (os.path.relpath(target, project), block_name,
                            (active_gen(project) if active_gen(project) is not None else "?")))
    new_text = text[:span[0]] + _format_levelup(moves) + text[span[1]:]
    # 自检：写回结果必须与提交的 (等级, 招式) 多重集完全一致
    want = sorted((_level_value(m), str(m["move"]).strip()) for m in moves)
    got = sorted((int(lv), mv) for lv, mv in LEVEL_MOVE_RE.findall(_format_levelup(moves)))
    if want != got:
        raise ValueError("升级招式自检失败：写入结果与提交内容不一致，已放弃写入")
    _write(target, new_text)
    return os.path.relpath(target, project)


# ---------------------------------------------------------------- 蛋招

def read_egg(project: str, block_name: str) -> Optional[dict]:
    if not block_name or not block_name.startswith("s"):
        return None
    path = os.path.join(project, EGG_FILE)
    if not os.path.isfile(path):
        return None
    text = _read(path)
    span = find_block(text, block_name)
    if not span:
        return None
    body = text[span[0]:span[1]]
    moves = []
    for line in body.splitlines():
        m = EGG_MOVE_RE.match(line)
        if m and m.group(1) != "MOVE_UNAVAILABLE":
            moves.append(m.group(1))
    return {"block": block_name, "file": EGG_FILE, "moves": moves, "editable": True}


def write_egg(project: str, block_name: str, moves: List[str]) -> str:
    if not valid_block_name(block_name):
        raise ValueError("无效的蛋招块名: %r（该形态通常没有独立蛋招表）" % block_name)
    path = os.path.join(project, EGG_FILE)
    text = _read(path)
    span = find_block(text, block_name)
    if not span:
        raise ValueError("找不到蛋招块 %s" % block_name)
    clean = [m for m in (str(_as_move(x)).strip() for x in moves) if m]
    for m in clean:
        if not m.startswith("MOVE_"):
            raise ValueError("招式名不合法: %s" % m)
    lines = ["    %s," % m for m in clean]
    lines.append("    MOVE_UNAVAILABLE,")
    body = "\n" + "\n".join(lines) + "\n"
    _write(path, text[:span[0]] + body + text[span[1]:])
    return EGG_FILE


# ---------------------------------------------------------------- 教学招式

def _load_learnables(project: str) -> dict:
    path = os.path.join(project, LEARNABLES_FILE)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_teachable(project: str, species_id: str) -> Optional[dict]:
    try:
        data = _load_learnables(project)
    except (OSError, ValueError) as exc:
        return {"editable": False, "error": "all_learnables.json 无法解析: %s" % exc}
    key = (species_id or "").upper()
    if key not in data:
        return {"block": key, "file": LEARNABLES_FILE, "moves": [],
                "editable": True, "note": "该宝可梦还没有教学招式条目"}
    return {"block": key, "file": LEARNABLES_FILE,
            "moves": list(data[key]), "editable": True}


def write_teachable(project: str, species_id: str, moves: List[str]) -> str:
    path = os.path.join(project, LEARNABLES_FILE)
    data = _load_learnables(project)
    key = (species_id or "").upper()
    clean = sorted({str(_as_move(m)).strip() for m in moves if str(_as_move(m)).strip()})
    for m in clean:
        if not m.startswith("MOVE_"):
            raise ValueError("招式名不合法: %s" % m)
    if clean:
        data[key] = clean
    else:
        data.pop(key, None)
    # 保留原有键顺序，避免整份文件重排
    _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return LEARNABLES_FILE
