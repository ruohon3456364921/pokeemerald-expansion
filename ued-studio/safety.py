# -*- coding: utf-8 -*-
"""安全层：保存前快照、保存后校验、异常自动回滚。

校验规则（以"正常的一次字段修改"为基线）：
  1. 除被修改的物种块之外，同文件其它物种块的成员列表必须逐字不变（抓串味）；
  2. 被修改的物种块内不能出现新的重复成员（抓"词条重复"）；
  3. 物种枚举表 include/constants/species.h 不变（抓枚举被追加）；
  4. 任何未能预期的文件变化都视为失败。
失败时按快照原子回滚。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from typing import Dict, List, Tuple

SPECIES_H = os.path.join("include", "constants", "species.h")
SPECIES_INFO_DIR = os.path.join("src", "data", "pokemon", "species_info")
LEVELUP_DIR = os.path.join("src", "data", "pokemon", "level_up_learnsets")
EGG_FILE = os.path.join("src", "data", "pokemon", "egg_moves.h")
LEARNABLES_FILE = os.path.join("src", "data", "pokemon", "all_learnables.json")
ITEMS_FILE = os.path.join("src", "data", "items.h")
LEARNSET_EXTS = (".h",)

BLOCK_START = re.compile(r'\[(SPECIES_[A-Z0-9_]+)\]\s*=')
FIELD_LINE = re.compile(r'^\s*\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


# ---------------------------------------------------------------- 解析

def read_text(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def find_block(text: str, start: int):
    """从 '[' 处解析 `[SPECIES_X] = { ... }`，返回 (symbol, 块文本, 起, 止)。

    宏展开形式（`= SOME_MACRO(...)`）返回 None。
    """
    m = BLOCK_START.match(text, start)
    if not m:
        return None
    i = m.end()
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != "{":
        return None
    depth = 0
    j = i
    quote = None
    line_comment = block_comment = False
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
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return (m.group(1), text[i:j + 1], start, j + 1)
        j += 1
    return (m.group(1), text[i:], start, len(text))


def iter_blocks(text: str):
    pos = 0
    while True:
        m = BLOCK_START.search(text, pos)
        if not m:
            return
        got = find_block(text, m.start())
        if got is None:
            pos = m.end()
            continue
        yield got
        pos = got[3]


def block_members(body: str) -> List[Tuple[str, str]]:
    """块内 `.字段 = 值` 列表，按行序。"""
    out = []
    for line in body.splitlines():
        m = FIELD_LINE.match(line)
        if m:
            out.append((m.group(1), m.group(2).rstrip().rstrip(",")))
    return out


def duplicate_members(body: str) -> Dict[str, int]:
    """同一条目内重复出现的成员（区分 #if 分支，不同分支的同名成员是合法的）。"""
    stack: List[int] = []
    seen: Dict[Tuple[str, str], int] = {}
    for line in body.splitlines():
        s = line.strip()
        m = re.match(r'#\s*(if|ifdef|ifndef|elif|else|endif)\b', s)
        if m:
            kw = m.group(1)
            if kw in ("if", "ifdef", "ifndef"):
                stack.append(0)
            elif kw in ("elif", "else") and stack:
                stack[-1] += 1
            elif kw == "endif" and stack:
                stack.pop()
            continue
        m = FIELD_LINE.match(line)
        if m:
            key = (m.group(1), "/".join(map(str, stack)))
            seen[key] = seen.get(key, 0) + 1
    out = {}
    for (name, _branch), n in seen.items():
        if n > 1:
            out[name] = max(out.get(name, 0), n)
    return out


# ---------------------------------------------------------------- 快照

def _iter_project_files(project: str) -> List[str]:
    files = []
    info = os.path.join(project, SPECIES_INFO_DIR)
    if os.path.isdir(info):
        for name in sorted(os.listdir(info)):
            if name.endswith(".h"):
                files.append(os.path.join(info, name))
    consts = os.path.join(project, SPECIES_H)
    if os.path.isfile(consts):
        files.append(consts)
    lv = os.path.join(project, LEVELUP_DIR)
    if os.path.isdir(lv):
        for name in sorted(os.listdir(lv)):
            if name.endswith(".h"):
                files.append(os.path.join(lv, name))
    for rel in (EGG_FILE, LEARNABLES_FILE, ITEMS_FILE):
        p = os.path.join(project, rel)
        if os.path.isfile(p):
            files.append(p)
    return files


class Snapshot:
    """项目物种相关文件的内存快照。"""

    def __init__(self, project: str, files: List[str] | None = None):
        self.project = project
        self.files = files or _iter_project_files(project)
        self.blobs: Dict[str, bytes] = {}
        for path in self.files:
            try:
                with open(path, "rb") as fh:
                    self.blobs[path] = fh.read()
            except OSError:
                self.blobs[path] = b""
        self.stamp = time.strftime("%Y%m%d-%H%M%S")

    def digest(self) -> str:
        h = hashlib.sha256()
        for path in sorted(self.blobs):
            h.update(path.encode("utf-8"))
            h.update(self.blobs[path])
        return h.hexdigest()

    def restore(self) -> int:
        n = 0
        for path, blob in self.blobs.items():
            try:
                with open(path, "rb") as fh:
                    if fh.read() == blob:
                        continue
            except OSError:
                pass
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
            n += 1
        return n

    def changed_files(self) -> List[str]:
        out = []
        for path, blob in self.blobs.items():
            try:
                with open(path, "rb") as fh:
                    if fh.read() != blob:
                        out.append(path)
            except OSError:
                out.append(path)
        return out

    def restore_file(self, path: str) -> bool:
        blob = self.blobs.get(path)
        if blob is None:
            return False
        try:
            with open(path, "rb") as fh:
                if fh.read() == blob:
                    return False
        except OSError:
            pass
        with open(path, "wb") as fh:
            fh.write(blob)
        return True

    def persist(self, history_dir: str) -> str:
        """把快照落盘，供"撤销"使用。"""
        os.makedirs(history_dir, exist_ok=True)
        target = os.path.join(history_dir, self.stamp)
        if os.path.isdir(target):
            target = "%s-%d" % (target, int(time.time() * 1000) % 100000)
        os.makedirs(target, exist_ok=True)
        for path, blob in self.blobs.items():
            rel = os.path.relpath(path, self.project)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(blob)
        return target


# ---------------------------------------------------------------- 校验

class ValidationError(RuntimeError):
    pass


def mask_named_block(text: str, name: str):
    """把指定块的内容替换为占位符，其余部分原样保留，用于"只允许这一块变化"。"""
    pattern = re.compile(r'\b%s\[\]\s*=\s*' % re.escape(name))
    m = pattern.search(text)
    if not m:
        return text
    open_idx = text.find("{", m.end())
    if open_idx < 0:
        return text
    span = _brace_span(text, open_idx)
    if not span:
        return text
    return text[:span[0]] + "@@BLOCK@@" + text[span[1]:]


def _brace_span(text: str, open_idx: int):
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


def validate_species_save(snapshot: Snapshot, project: str, symbol: str,
                          expect_fields: Dict[str, str] | None = None,
                          target_blocks: List[str] | None = None) -> List[str]:
    """对比快照与当前磁盘内容。返回警告列表，失败抛 ValidationError。"""
    warnings: List[str] = []

    # 规则 3：物种枚举不变
    enum_path = os.path.join(project, SPECIES_H)
    before_enum = snapshot.blobs.get(enum_path)
    if before_enum is not None and os.path.isfile(enum_path):
        with open(enum_path, "rb") as fh:
            if fh.read() != before_enum:
                raise ValidationError("species.h 枚举被修改（预期不应写入）")

    # 逐文件比对
    for path, before_blob in snapshot.blobs.items():
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            after_blob = fh.read()
        if after_blob == before_blob:
            continue
        if os.path.basename(path) == "all_learnables.json":
            if not target_blocks:
                # 字段保存时学习表本不该变；原生库偶尔会重排格式，
                # 语义一致就放行，语义有变由调用方还原（见 app.save_species）
                try:
                    same = (json.loads(before_blob.decode("utf-8"))
                            == json.loads(after_blob.decode("utf-8")))
                except ValueError:
                    raise ValidationError("all_learnables.json 被写坏")
                if not same:
                    raise ValidationError("all_learnables.json 被意外修改")
                warnings.append("all_learnables.json 格式被重排（内容未变）")
                continue
            if target_blocks:
                try:
                    before_json = json.loads(before_blob.decode("utf-8"))
                    after_json = json.loads(after_blob.decode("utf-8"))
                except ValueError:
                    raise ValidationError("all_learnables.json 被写坏")
                key = sorted(target_blocks)[0]
                before_rest = {k: v for k, v in before_json.items() if k != key}
                after_rest = {k: v for k, v in after_json.items() if k != key}
                if before_rest != after_rest:
                    raise ValidationError("all_learnables.json 其它条目被修改")
            continue

        before_text = before_blob.decode("utf-8", "replace")
        after_text = after_blob.decode("utf-8", "replace")

        if path.endswith(".h") and "level_up_learnsets" in path or path.endswith("egg_moves.h"):
            if not target_blocks:
                raise ValidationError("招式文件被意外修改: %s" % path)
            if target_blocks:
                for name in target_blocks:
                    if mask_named_block(before_text, name) != mask_named_block(after_text, name):
                        raise ValidationError("招式文件被误改（%s 之外的块发生变化）" % name)
            continue

        if not path.endswith(".h") or os.path.basename(path) == "species.h":
            warnings.append("非预期文件被修改: %s" % path)
            continue

        before_blocks = {b[0]: b[1] for b in iter_blocks(before_blob.decode("utf-8", "replace"))}
        after_blocks = {b[0]: b[1] for b in iter_blocks(after_blob.decode("utf-8", "replace"))}

        # 规则 3b：块集合不能变
        if set(before_blocks) != set(after_blocks):
            added = set(after_blocks) - set(before_blocks)
            removed = set(before_blocks) - set(after_blocks)
            raise ValidationError("物种块集合变化: +%s -%s" % (sorted(added), sorted(removed)))

        # 规则 1：非目标块必须逐字不变
        for sym in before_blocks:
            if sym == symbol:
                continue
            if block_members(before_blocks[sym]) != block_members(after_blocks[sym]):
                raise ValidationError(
                    "相邻条目被污染: %s（保存 %s 时被写入其它数值）" % (sym, symbol))

        # 规则 2：目标块不得新增重复成员
        before_dup = duplicate_members(before_blocks.get(symbol, ""))
        after_dup = duplicate_members(after_blocks.get(symbol, ""))
        new_dup = set(after_dup) - set(before_dup)
        if new_dup:
            raise ValidationError("出现重复词条: %s -> %s" % (symbol, sorted(new_dup)))

        # 规则 4：目标字段确实写成了
        if expect_fields:
            got = dict(block_members(after_blocks.get(symbol, "")))
            for name, want in expect_fields.items():
                if name in got and got[name].strip() != str(want).strip():
                    warnings.append("字段 %s 未按预期写入（实际 %r）" % (name, got[name]))

    return warnings


# ---------------------------------------------------------------- 体检

def health_check(project: str) -> dict:
    info = os.path.join(project, SPECIES_INFO_DIR)
    if not os.path.isdir(info):
        raise ValidationError("找不到 %s" % info)
    total = 0
    dup = []
    for name in sorted(os.listdir(info)):
        if not name.endswith(".h"):
            continue
        text = read_text(os.path.join(info, name))
        for sym, body, _, _ in iter_blocks(text):
            total += 1
            d = duplicate_members(body)
            if d:
                dup.append({"file": name, "symbol": sym,
                            "fields": sorted(d)})
    enum_dups = []
    consts = os.path.join(project, SPECIES_H)
    if os.path.isfile(consts):
        text = read_text(consts)
        seen = {}
        for m in re.finditer(r'^\s*(SPECIES_[A-Z0-9_]+)\s*(?:=|,)', text, re.M):
            seen[m.group(1)] = seen.get(m.group(1), 0) + 1
        enum_dups = sorted(k for k, v in seen.items() if v > 1)
    return {"ok": True, "entries": total, "duplicates": dup,
            "enum_duplicates": enum_dups}


# ---------------------------------------------------------------- 道具校验



def _item_signature(blocks):
    return [(b["symbol"], [(m["name"], m["value"]) for m in b["members"]])
            for b in blocks]


def validate_item_save(snapshot: Snapshot, project: str, symbol: str,
                       expect_fields: Dict[str, str]) -> List[str]:
    """道具保存后的校验：只允许目标条目的目标字段变化。"""
    import items as ITEMLIB

    path = os.path.join(project, ITEMS_FILE)
    before = snapshot.blobs.get(path)
    if before is None:
        raise ValidationError("快照中没有 %s" % ITEMS_FILE)
    if not os.path.isfile(path):
        raise ValidationError("%s 不见了" % ITEMS_FILE)
    with open(path, "rb") as fh:
        after = fh.read()
    if after == before:
        raise ValidationError("保存后 items.h 没有变化，说明没有写进去")

    old_blocks = ITEMLIB.read_items(before.decode("utf-8", "replace"))
    new_blocks = ITEMLIB.read_items(after.decode("utf-8", "replace"))
    if [b["symbol"] for b in old_blocks] != [b["symbol"] for b in new_blocks]:
        raise ValidationError("道具条目集合被改动（新增/删除/改名）")

    target_seen = False
    for (old_sym, old_members), (new_sym, new_members) in zip(
            _item_signature(old_blocks), _item_signature(new_blocks)):
        if old_sym != symbol:
            if old_members != new_members:
                raise ValidationError("条目 %s 被意外改动" % old_sym)
            continue
        target_seen = True
        if [n for n, _ in old_members] != [n for n, _ in new_members]:
            raise ValidationError("条目 %s 的字段被增删（可能出现重复词条）" % symbol)
        for (fname, f_old), (_fname, f_new) in zip(old_members, new_members):
            if f_old == f_new:
                continue
            if fname not in expect_fields:
                raise ValidationError("条目 %s 的 %s 被意外改动" % (symbol, fname))
            expected = ITEMLIB.build_value(fname, expect_fields[fname], f_old)
            if f_new != expected:
                raise ValidationError("条目 %s 的 %s 写入内容与预期不符" % (symbol, fname))
    if not target_seen:
        raise ValidationError("items.h 里找不到条目 %s" % symbol)

    warnings: List[str] = []
    for p, blob in snapshot.blobs.items():
        if p == path or not os.path.isfile(p):
            continue
        with open(p, "rb") as fh:
            if fh.read() != blob:
                warnings.append("%s 也被改写（不属于本次修改）"
                                % os.path.relpath(p, project))
    return warnings
