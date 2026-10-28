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

def _levelup_files(project: str) -> List[str]:
    d = os.path.join(project, LEVELUP_DIR)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".h")]


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
        return {"block": block_name, "file": os.path.relpath(path, project),
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


def _format_levelup(moves: List[dict]) -> str:
    lines = []
    normalized = [_as_level_move(m) for m in moves]
    ordered = sorted(enumerate(normalized), key=lambda pair: (int(pair[1]["level"] or 1), pair[0]))
    for _idx, item in ordered:
        lv = int(item["level"] or 1)
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
    levels = [int(m["level"] or 1) for m in moves]
    if min(levels) < 1 or max(levels) > 100:
        raise ValueError("等级必须在 1..100 之间")
    for path in _levelup_files(project):
        text = _read(path)
        span = find_block(text, block_name)
        if not span:
            continue
        new_text = text[:span[0]] + _format_levelup(moves) + text[span[1]:]
        _write(path, new_text)
        return os.path.relpath(path, project)
    raise ValueError("找不到招式块 %s" % block_name)


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
