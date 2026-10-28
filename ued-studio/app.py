# -*- coding: utf-8 -*-
"""UED Studio —— pokeemerald-expansion 可视化编辑器（本地 Web 界面）。

设计要点（相对原 UniversalEditor 的修正）：
  * 每次保存都在全新会话中完成，保存后立即关闭 —— 绕开原生库"偏移缓存不更新"
    导致的词条重复 / 相邻条目串味；
  * 只提交用户真正改动过的字段，其余字段原样不动；
  * 保存前内存快照，保存后逐块校验，异常自动原子回滚；
  * 每次成功保存留一份历史快照，支持一键撤销。

启动： python app.py [项目路径]
"""
from __future__ import annotations

import glob
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import re

import safety
from ued_core import NativeLib, Session, NativeError

HERE = os.path.dirname(os.path.abspath(__file__))
DLL_PATH = os.path.join(HERE, "lib", "UniversalEditor.Native.dll")
WEB_DIR = os.path.join(HERE, "web")
HISTORY_LIMIT = 30
APP_VERSION = "2.5"

with open(os.path.join(HERE, "field_groups.json"), encoding="utf-8") as _fh:
    FIELD_GROUPS = json.load(_fh)

with open(os.path.join(HERE, "field_labels.json"), encoding="utf-8") as _fh:
    FIELD_LABELS = json.load(_fh)

EGG_GROUPS = [
    ("EGG_GROUP_MONSTER", "怪兽"), ("EGG_GROUP_WATER_1", "水中1"),
    ("EGG_GROUP_BUG", "虫"), ("EGG_GROUP_FLYING", "飞行"),
    ("EGG_GROUP_FIELD", "陆上"), ("EGG_GROUP_FAIRY", "妖精"),
    ("EGG_GROUP_GRASS", "植物"), ("EGG_GROUP_HUMAN_LIKE", "人形"),
    ("EGG_GROUP_WATER_3", "水中3"), ("EGG_GROUP_MINERAL", "矿物"),
    ("EGG_GROUP_AMORPHOUS", "不定形"), ("EGG_GROUP_WATER_2", "水中2"),
    ("EGG_GROUP_DITTO", "百变怪"), ("EGG_GROUP_DRAGON", "龙"),
    ("EGG_GROUP_NO_EGGS_DISCOVERED", "未发现"),
]

GROWTH_RATES = [
    ("GROWTH_MEDIUM_FAST", "较快"), ("GROWTH_ERRATIC", "极慢"),
    ("GROWTH_FLUCTUATING", "极快"), ("GROWTH_MEDIUM_SLOW", "较慢"),
    ("GROWTH_FAST", "快"), ("GROWTH_SLOW", "慢"),
]

BODY_COLORS = [
    ("BODY_COLOR_RED", "红"), ("BODY_COLOR_BLUE", "蓝"),
    ("BODY_COLOR_YELLOW", "黄"), ("BODY_COLOR_GREEN", "绿"),
    ("BODY_COLOR_BLACK", "黑"), ("BODY_COLOR_BROWN", "棕"),
    ("BODY_COLOR_PURPLE", "紫"), ("BODY_COLOR_GRAY", "灰"),
    ("BODY_COLOR_WHITE", "白"), ("BODY_COLOR_PINK", "粉"),
]

GROUP_TITLES = {
    "battle": "战斗",
    "breeding": "培育",
    "dex": "图鉴",
    "graphics": "图形",
    "forms": "形态与进化",
    "moves": "招式",
    "other": "其它",
}


SETTINGS_PATH = os.path.join(HERE, "settings.json")


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass

STATE_LOCK = threading.RLock()

STRUCT_CHARS = set("{};#,\n\r")

# 这些字段本来就带括号/花括号，走结构校验而不是字符黑名单
STRUCT_FIELD_RE = {
    "abilities": re.compile(r'^\{\s*[A-Z0-9_]+(\s*,\s*[A-Z0-9_]+){2}\s*\}$'),
    "types": re.compile(r'^MON_TYPES\(\s*[A-Z0-9_]+(\s*,\s*[A-Z0-9_]+)?\s*\)$'),
    "eggGroups": re.compile(r'^MON_EGG_GROUPS\(\s*[A-Z0-9_]+(\s*,\s*[A-Z0-9_]+)?\s*\)$'),
    "genderRatio": re.compile(r'^(MON_MALE|MON_FEMALE|MON_GENDERLESS|PERCENT_FEMALE\(\s*[\d.]+\s*\))$'),
}


def _validate_value(key: str, old: str, new: str) -> None:
    """轻量值校验，挡住会把 C 源码写坏的输入。"""
    new_s = new.strip()
    pattern = STRUCT_FIELD_RE.get(key)
    if pattern is not None:
        if not pattern.match(new_s):
            raise NativeError("字段 %s 的格式不正确: %r" % (key, new))
        return
    if any(ch in new for ch in STRUCT_CHARS):
        raise NativeError("字段 %s 的值含非法字符（换行/分号/花括号/#/逗号）" % key)
    old_s = str(old).strip()
    if re.fullmatch(r"-?\d+", old_s) and not re.fullmatch(r"-?\d+", new_s):
        raise NativeError("字段 %s 原本是整数，新值 %r 不是整数" % (key, new_s))


class AppState:
    def __init__(self, project: str):
        self.project = os.path.abspath(project)
        self.lib = NativeLib.get(DLL_PATH)
        self._catalog = None
        self._refs = None
        self._raw_catalog = None
        self._forms = None
        self.history_dir = os.path.join(self.project, ".ued-studio", "history")

    # -- 会话 ---------------------------------------------------------
    def session(self) -> Session:
        return Session(self.lib, self.project)

    # -- 目录（缓存） -------------------------------------------------
    # -- 目录缓存 -------------------------------------------------------
    def _cache_path(self):
        return os.path.join(HERE, "cache.json")

    def _cache_stamp(self):
        stamp = 0.0
        for rel in (safety.SPECIES_H, safety.SPECIES_INFO_DIR):
            path = os.path.join(self.project, rel)
            try:
                stamp = max(stamp, os.path.getmtime(path))
            except OSError:
                pass
        return stamp

    CACHE_VERSION = 3

    def _load_cache(self):
        try:
            with open(self._cache_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") != self.CACHE_VERSION:
                return None
            if data.get("project") != self.project:
                return None
            if abs(float(data.get("stamp", 0)) - self._cache_stamp()) > 1:
                return None
            return data
        except (OSError, ValueError):
            return None

    def _save_cache(self):
        try:
            with open(self._cache_path(), "w", encoding="utf-8") as fh:
                json.dump({"version": self.CACHE_VERSION,
                           "project": self.project, "stamp": self._cache_stamp(),
                           "catalog": self._catalog, "refs": self._refs,
                           "forms": self._forms},
                          fh, ensure_ascii=False)
        except OSError:
            pass

    def catalog(self):
        with STATE_LOCK:
            if self._catalog is None:
                cached = self._load_cache()
                if cached:
                    self._catalog = cached.get("catalog") or []
                    self._refs = cached.get("refs")
                    self._forms = cached.get("forms") or {}
                    return self._catalog
                s = self.session()
                try:
                    data = s.species_catalog()
                finally:
                    s.close()
                self._raw_catalog = data
                items = []
                for item in data.get("species", []):
                    items.append({
                        "symbol": item.get("symbol"),
                        "id": item.get("id"),
                        "displayName": item.get("displayName") or item.get("speciesName") or "",
                        "speciesName": item.get("speciesName") or "",
                        "types": item.get("types") or "",
                        "abilities": item.get("abilities") or "",
                        "sourceFile": item.get("sourceFile") or "",
                        "frontPicPath": item.get("frontPicPath") or "",
                    })
                self._catalog = items
                if self._forms is None:
                    self._forms = self._build_forms()
            return self._catalog

    def _build_forms(self):
        """按 natDexNum 归并形态族：同号条目互为形态，基形排第一。

        只用 species_info 的源文件，和原生库的目录扫描同源，不额外开销。
        """
        pattern = os.path.join(self.project, "src", "data", "pokemon",
                               "species_info", "*.h")
        dex_of = {}
        for path in glob.glob(pattern):
            if os.path.basename(path).startswith("old_"):
                continue
            try:
                text = safety.read_text(path)
            except OSError:
                continue
            for symbol, body, _start, _end in safety.iter_blocks(text):
                members = dict(safety.block_members(body))
                dex = members.get("natDexNum", "")
                if dex:
                    dex_of[symbol] = dex
        groups = {}
        for symbol, dex in dex_of.items():
            groups.setdefault(dex, []).append(symbol)
        forms = {}
        for dex, members in groups.items():
            if len(members) < 2:
                continue
            base = "SPECIES_" + dex.split("NATIONAL_DEX_", 1)[1] if dex.startswith("NATIONAL_DEX_") else ""
            if base not in members:
                base = sorted(members, key=len)[0]
            ordered = [base] + sorted(m for m in members if m != base)
            for symbol in ordered:
                forms[symbol] = ordered
        return forms

    def forms(self):
        self.catalog()
        return self._forms or {}

    def refs(self):
        with STATE_LOCK:
            if self._refs is None:
                self.catalog()          # 复用同一次扫描结果
                cat = getattr(self, "_raw_catalog", {}) or {}
                refs = {}
                for key in ("types", "abilities", "items", "moves"):
                    refs[key] = [{"s": x.get("symbol"), "n": x.get("name") or ""}
                                 for x in cat.get(key, [])]
                refs["eggGroups"] = [{"s": a, "n": b} for a, b in EGG_GROUPS]
                refs["growthRates"] = [{"s": a, "n": b} for a, b in GROWTH_RATES]
                refs["bodyColors"] = [{"s": a, "n": b} for a, b in BODY_COLORS]
                self._refs = refs
                self._save_cache()
            return self._refs

    def sprite(self, symbol: str, kind: str = "front"):
        item = next((x for x in self.catalog() if x.get("symbol") == symbol), None)
        if not item:
            raise NativeError("未知物种: %s" % symbol)
        rel = (item.get("frontPicPath") or "").replace("\\", "/")
        base = os.path.dirname(rel) if rel else ""
        names = {"front": "anim_front.png", "back": "back.png", "icon": "icon.png"}
        order = [names.get(kind, "anim_front.png"), "anim_front.png", "front.png"]
        tried = []
        for name in order:
            path = os.path.join(self.project, base, name)
            tried.append(os.path.join(base, name))
            if os.path.isfile(path):
                return path
        raise NativeError("找不到图片，尝试过: %s（frontPicPath=%r）"
                          % (", ".join(tried), rel))

    def summary(self):
        s = self.session()
        try:
            return s.summary()
        finally:
            s.close()

    # -- 读 -----------------------------------------------------------
    def species(self, symbol: str):
        s = self.session()
        try:
            return s.species(symbol)
        finally:
            s.close()

    def learnsets(self, doc: dict):
        import learnsets as LS
        fields = doc.get("fields") or {}
        out = []
        try:
            lu = LS.read_levelup(self.project, fields.get("levelUpLearnset", ""))
            if lu:
                out.append({"kind": "levelup", "title": "升级招式", **lu})
        except Exception as exc:
            out.append({"kind": "levelup", "title": "升级招式", "editable": False,
                        "error": str(exc), "moves": []})
        try:
            eg = LS.read_egg(self.project, fields.get("eggMoveLearnset", ""))
            if eg:
                out.append({"kind": "egg", "title": "蛋招式", **eg})
            else:
                out.append({"kind": "egg", "title": "蛋招式", "editable": False,
                            "moves": [], "note": "这个形态没有独立蛋招表（通常继承家族基础形态）"})
        except Exception as exc:
            out.append({"kind": "egg", "title": "蛋招式", "editable": False,
                        "error": str(exc), "moves": []})
        try:
            tc = LS.read_teachable(self.project, doc.get("id", ""))
            if tc:
                out.append({"kind": "teachable", "title": "教学招式", **tc})
        except Exception as exc:
            out.append({"kind": "teachable", "title": "教学招式", "editable": False,
                        "error": str(exc), "moves": []})
        return out

    def save_learnset(self, symbol: str, kind: str, moves: list) -> dict:
        import learnsets as LS
        with STATE_LOCK:
            s = self.session()
            try:
                doc = s.species(symbol)
            finally:
                s.close()
            fields = doc.get("fields") or {}
            snap = safety.Snapshot(self.project)
            try:
                if kind == "levelup":
                    block = fields.get("levelUpLearnset", "")
                    if not block:
                        raise NativeError("这只宝可梦没有独立的升级招式表")
                    changed = LS.write_levelup(self.project, block, moves)
                    target = [block]
                elif kind == "egg":
                    block = fields.get("eggMoveLearnset", "")
                    if not block:
                        raise NativeError("这个形态没有独立蛋招表（通常继承家族基础形态），无法单独编辑")
                    changed = LS.write_egg(self.project, block, moves)
                    target = [block]
                elif kind == "teachable":
                    species_id = doc.get("id", "")
                    changed = LS.write_teachable(self.project, species_id, moves)
                    target = [str(species_id).upper()]
                else:
                    raise NativeError("未知的招式类型: %s" % kind)
                warnings = safety.validate_species_save(
                    snap, self.project, symbol, target_blocks=target)
            except Exception as exc:
                restored = snap.restore()
                if restored:
                    raise NativeError("%s（已回滚 %d 个文件）" % (exc, restored))
                raise NativeError(str(exc))
            backup = snap.persist(self.history_dir)
            self._prune_history()
            return {"ok": True, "kind": kind, "file": changed,
                    "count": len(moves), "warnings": warnings,
                    "backup": os.path.basename(backup)}

    # -- 写（安全流程） -----------------------------------------------
    def save_species(self, symbol: str, changes: dict) -> dict:
        if not changes:
            return {"ok": True, "skipped": True, "message": "没有改动"}
        clean = {}
        for k, v in changes.items():
            if not isinstance(k, str) or not k:
                raise NativeError("字段名非法")
            if v is None:
                continue
            text = str(v)
            if "\n" in text:
                raise NativeError("字段 %s 不支持多行编辑，请在源码中修改" % k)
            if not text.strip():
                raise NativeError("字段 %s 的值不能为空" % k)
            clean[k] = text
        if not clean:
            return {"ok": True, "skipped": True, "message": "没有有效改动"}

        with STATE_LOCK:
            snap = safety.Snapshot(self.project)
            try:
                s = self.session()
                try:
                    doc = s.species(symbol)
                    known = doc.get("fields") or {}
                    unknown = [k for k in clean if k not in known]
                    if unknown:
                        raise NativeError("未知字段: %s（不允许凭空新增字段）"
                                          % ", ".join(sorted(unknown)))
                    for k, v in clean.items():
                        _validate_value(k, known.get(k, ""), v)
                    payload = {
                        "symbol": doc.get("symbol", symbol),
                        "id": doc.get("id"),
                        "fields": clean,
                    }
                    s.update_species(payload)
                    s.save()
                finally:
                    s.close()

                learn_note = self._guard_learnables(snap, symbol)
                warnings = safety.validate_species_save(
                    snap, self.project, symbol, expect_fields=clean)
                if learn_note:
                    warnings.append(learn_note)
            except Exception as exc:
                restored = snap.restore()
                if restored:
                    raise NativeError("%s（已回滚 %d 个文件）" % (exc, restored))
                raise NativeError(str(exc))

            changed = [os.path.relpath(p, self.project) for p in snap.changed_files()]
            backup = snap.persist(self.history_dir)
            self._prune_history()
            return {"ok": True, "symbol": symbol, "fields": clean,
                    "changedFiles": changed,
                    "backup": os.path.basename(backup),
                    "warnings": warnings}

    def _guard_learnables(self, snap, symbol: str):
        """字段保存不该动 all_learnables.json。

        原生库偶尔会顺带重写它：语义一致（只是重排）就接受，
        否则还原成保存前的版本，避免把学习表写坏。
        """
        path = os.path.join(self.project, "src", "data", "pokemon",
                            "all_learnables.json")
        before = snap.blobs.get(path)
        if before is None or not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as fh:
                after = fh.read()
        except OSError:
            return None
        if after == before:
            return None
        try:
            same = (json.loads(before.decode("utf-8"))
                    == json.loads(after.decode("utf-8")))
        except ValueError:
            same = False
        if same:
            return None
        snap.restore_file(path)
        return ("原生库保存时顺带改写了 all_learnables.json，已还原"
                "（该文件不属于本次修改范围）")

    def _prune_history(self):
        try:
            entries = sorted(os.listdir(self.history_dir))
        except OSError:
            return
        for name in entries[:-HISTORY_LIMIT]:
            path = os.path.join(self.history_dir, name)
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path, topdown=False):
                    for f in files:
                        os.remove(os.path.join(root, f))
                    for d in dirs:
                        os.rmdir(os.path.join(root, d))
                os.rmdir(path)

    def undo(self) -> dict:
        with STATE_LOCK:
            if not os.path.isdir(self.history_dir):
                raise NativeError("没有可撤销的保存记录")
            entries = sorted(os.listdir(self.history_dir))
            if not entries:
                raise NativeError("没有可撤销的保存记录")
            latest = os.path.join(self.history_dir, entries[-1])
            restored = 0
            for root, _dirs, files in os.walk(latest):
                for name in files:
                    src = os.path.join(root, name)
                    rel = os.path.relpath(src, latest)
                    dst = os.path.join(self.project, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(src, "rb") as fh:
                        blob = fh.read()
                    with open(dst, "wb") as fh:
                        fh.write(blob)
                    restored += 1
            for root, dirs, files in os.walk(latest, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            os.rmdir(latest)
            return {"ok": True, "restored": restored, "backup": entries[-1]}

    # -- 道具 ----------------------------------------------------------
    def _items_file(self) -> str:
        return os.path.join(self.project, safety.ITEMS_FILE)

    def _item_blocks(self):
        import items as ITEMLIB
        path = self._items_file()
        stat = os.stat(path)
        key = (stat.st_mtime_ns, stat.st_size)
        if getattr(self, "_items_key", None) != key:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8")
            self._items_key = key
            self._items_text = text
            self._items_blocks = ITEMLIB.read_items(text)
        return self._items_blocks, self._items_text

    def items_catalog(self) -> list:
        import items as ITEMLIB
        blocks, _ = self._item_blocks()
        return [ITEMLIB.item_summary(b) for b in blocks]

    def item(self, symbol: str) -> dict:
        import items as ITEMLIB
        blocks, _ = self._item_blocks()
        block = next((b for b in blocks if b["symbol"] == symbol), None)
        if block is None:
            raise NativeError("找不到道具 %s" % symbol)
        counts = {}
        for m in block["members"]:
            counts[m["name"]] = counts.get(m["name"], 0) + 1
        fields = []
        for m in block["members"]:
            view = ITEMLIB.field_view(m)
            fields.append({
                "name": m["name"],
                "branch": m.get("branch") or "",
                "duplicate": counts[m["name"]] > 1,
                "kind": view["kind"],
                "text": view["text"],
            })
        return {"symbol": symbol, "fields": fields,
                "summary": ITEMLIB.item_summary(block)}

    def save_item(self, symbol: str, changes: dict) -> dict:
        import items as ITEMLIB
        clean = {}
        for name, value in (changes or {}).items():
            if not isinstance(name, str) or not name:
                raise NativeError("字段名非法")
            clean[name] = "" if value is None else str(value)
        if not clean:
            return {"ok": True, "skipped": True, "message": "没有改动"}

        with STATE_LOCK:
            path = self._items_file()
            with open(path, "rb") as fh:
                old_text = fh.read().decode("utf-8")
            blocks = ITEMLIB.read_items(old_text)
            block = next((b for b in blocks if b["symbol"] == symbol), None)
            if block is None:
                raise NativeError("找不到道具 %s" % symbol)
            counts = {}
            for m in block["members"]:
                counts[m["name"]] = counts.get(m["name"], 0) + 1
            for name in clean:
                if name not in counts:
                    raise NativeError("道具 %s 没有字段 %s（不允许凭空新增）"
                                      % (symbol, name))
                if counts[name] > 1:
                    raise NativeError(
                        "字段 %s 在 %s 里有 %d 处（按版本分支定义），"
                        "请在 src/data/items.h 里改"
                        % (name, symbol, counts[name]))

            snap = safety.Snapshot(self.project)
            try:
                new_text = ITEMLIB.apply_changes(old_text, symbol, clean, blocks)
                if new_text == old_text:
                    return {"ok": True, "skipped": True, "message": "内容没有变化"}
                tmp = path + ".ued.tmp"
                with open(tmp, "wb") as fh:
                    fh.write(new_text.encode("utf-8"))
                os.replace(tmp, path)
                warnings = safety.validate_item_save(snap, self.project,
                                                     symbol, clean)
            except Exception as exc:
                restored = snap.restore()
                if restored:
                    raise NativeError("%s（已回滚 %d 个文件）" % (exc, restored))
                raise NativeError(str(exc))

            self._items_key = None
            changed = [os.path.relpath(p, self.project) for p in snap.changed_files()]
            backup = snap.persist(self.history_dir)
            self._prune_history()
            return {"ok": True, "symbol": symbol, "fields": clean,
                    "changedFiles": changed,
                    "backup": os.path.basename(backup),
                    "warnings": warnings}

    def check(self) -> dict:
        with STATE_LOCK:
            return safety.health_check(self.project)

    def item_refs(self):
        import items as ITEMLIB
        return ITEMLIB.read_enums(self.project)

    def backups(self):
        try:
            return sorted(os.listdir(self.history_dir))
        except OSError:
            return []


STATE: AppState | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "UEDStudio/2.0"

    # -- 工具 ---------------------------------------------------------
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc, status=400):
        self._json({"ok": False, "error": str(exc)}, status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # -- 路由 ---------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path.startswith("/api/"):
                return self._api_get(path, parse_qs(parsed.query))
            return self._static(path.lstrip("/"))
        except Exception as exc:
            traceback.print_exc()
            self._error(exc, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._body()
            return self._api_post(parsed.path, body)
        except Exception as exc:
            self._error(exc, 400)

    def _static(self, rel: str):
        safe = os.path.normpath(rel).lstrip("\\/")
        full = os.path.join(WEB_DIR, safe)
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            blob = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def _api_get(self, path: str, query: dict):
        if path == "/api/sprite":
            symbol = (query.get("symbol") or [""])[0]
            kind = (query.get("kind") or ["front"])[0]
            if not symbol:
                return self._error("缺少 symbol")
            try:
                full = STATE.sprite(symbol, kind)
            except Exception as exc:
                return self._error(exc, 404)
            with open(full, "rb") as fh:
                blob = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(blob)
            return
        if path == "/api/health":
            return self._json({"ok": True, "version": APP_VERSION,
                               "project": STATE.project,
                               "cached": os.path.isfile(STATE._cache_path())})
        if path == "/api/state":
            return self._json({
                "ok": True,
                "project": STATE.project,
                "catalog": STATE.catalog(),
                "forms": STATE.forms(),
                "groups": FIELD_GROUPS,
                "groupTitles": GROUP_TITLES,
                "labels": FIELD_LABELS,
                "refs": STATE.refs(),
                "itemRefs": STATE.item_refs(),
            })
        if path == "/api/species":
            symbol = (query.get("symbol") or [""])[0]
            if not symbol:
                return self._error("缺少 symbol")
            doc = STATE.species(symbol)
            return self._json({"ok": True, "species": doc,
                               "learnsets": STATE.learnsets(doc)})
        if path == "/api/items":
            return self._json({"ok": True, "items": STATE.items_catalog()})
        if path == "/api/item":
            symbol = (query.get("symbol") or [""])[0]
            if not symbol:
                return self._error("缺少 symbol")
            return self._json({"ok": True, "item": STATE.item(symbol)})
        if path == "/api/backups":
            return self._json({"ok": True, "backups": STATE.backups()})
        return self._error("未知接口 %s" % path, 404)

    def _api_post(self, path: str, body: dict):
        if path == "/api/save":
            symbol = body.get("symbol") or ""
            changes = body.get("changes") or {}
            if not symbol:
                return self._error("缺少 symbol")
            return self._json(STATE.save_species(symbol, changes))
        if path == "/api/learnsets/save":
            symbol = body.get("symbol") or ""
            kind = body.get("kind") or ""
            moves = body.get("moves") or []
            if not symbol or not kind:
                return self._error("缺少 symbol 或 kind")
            return self._json(STATE.save_learnset(symbol, kind, moves))
        if path == "/api/item/save":
            symbol = body.get("symbol") or ""
            changes = body.get("changes") or {}
            if not symbol:
                return self._error("缺少 symbol")
            return self._json(STATE.save_item(symbol, changes))
        if path == "/api/check":
            return self._json(STATE.check())
        if path == "/api/undo":
            return self._json(STATE.undo())
        return self._error("未知接口 %s" % path, 404)


def main():
    def is_project(path: str) -> bool:
        return bool(path) and os.path.isdir(
            os.path.join(path, "src", "data", "pokemon", "species_info"))

    if len(sys.argv) > 1:
        project = os.path.abspath(sys.argv[1])
    else:
        remembered = load_settings().get("project") or ""
        # 记住的路径可能失效（例如 pushd 映射的临时盘符 Z:），逐级回退
        candidates = [remembered, os.path.dirname(HERE)]
        project = next((p for p in candidates if is_project(p)), candidates[-1])

    if not is_project(project):
        print("这不是一个 pokeemerald-expansion 项目: %s" % project)
        print("用法: python app.py <项目根目录>")
        print("例如: python app.py //wsl.localhost/Ubuntu/home/ruo/pokeemerald-expansion")
        sys.exit(1)

    save_settings({"project": project})

    global STATE
    STATE = AppState(project)
    t0 = time.time()
    count = len(STATE.catalog())
    print("项目: %s" % project)
    print("物种: %d 个（加载 %d ms）" % (count, int((time.time() - t0) * 1000)))

    port = int(os.environ.get("UED_PORT", "8765"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d" % port
    print("编辑器已启动: %s" % url)
    if not os.environ.get("UED_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("按 Ctrl+C 退出")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
