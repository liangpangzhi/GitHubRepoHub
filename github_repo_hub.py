# -*- coding: utf-8 -*-
"""
GitHub Repo Hub v2.0.0
Win11 毛玻璃风格的个人 GitHub 仓库管家（Star + 自有仓库）
- Win11 Acrylic/Mica 毛玻璃半透明背景 + DWM 圆角 + 无系统边框
- 自定义下载加速前缀（多源管理 / 测试可用性 / 全局开关 / 双地址复制打开）
- 纯 Python + PySide6，打包为单文件 exe，无需另装运行环境
"""
import os
import sys
import json
import csv
import time
import ssl
import ctypes
from ctypes import wintypes
import webbrowser
import urllib.request
import urllib.error
import urllib.parse
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import (Qt, QThread, Signal, QTimer, QPoint, QSize, QRect,
                            QRectF, QEvent, QObject)
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen, QBrush,
                           QFont, QAction, QLinearGradient, QPixmap, QCursor,
                           QGuiApplication)
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QFrame, QLabel,
                               QPushButton, QLineEdit, QCheckBox, QComboBox,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QVBoxLayout, QHBoxLayout, QGridLayout, QMenu,
                               QMessageBox, QFileDialog, QSizeGrip, QAbstractItemView,
                               QProgressBar, QToolButton, QButtonGroup, QSplitter,
                               QInputDialog, QSpinBox, QStyle, QScrollArea)

APP_NAME = "GitHub Repo Hub"
APP_VERSION = "2.0.0"
API_ROOT = "https://api.github.com"
UA = "GitHubRepoHub/" + APP_VERSION

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".github_repo_hub")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "app.log")

TYPE_STAR = "Star"
TYPE_MINE = "我的仓库"

COLUMNS = ["项目名称", "类型", "仓库描述", "我的备注", "拉取地址", "下载地址"]
COL_KEY, COL_TYPE, COL_DESC, COL_NOTE, COL_CLONE, COL_DL = range(6)

ASSET_PRIORITY = [".exe", ".msi", ".zip", ".7z", ".tar.gz", ".dmg", ".deb",
                  ".apk", ".AppImage", ".pkg"]
ASSET_IGNORE = (".sha256", ".sha512", ".md5", ".sig", ".asc", ".txt", ".json",
                ".blockmap", ".sbom")

DEFAULT_ACCELERATORS = [
    {"prefix": "https://ghproxy.net/", "enabled": True, "note": "公共代理，稳定"},
    {"prefix": "https://gh-proxy.com/", "enabled": True, "note": "公共代理"},
    {"prefix": "https://ghfast.top/", "enabled": False, "note": "备用（可能限速）"},
]

# 加速可用性测试使用的原始地址（GitHub 官方示例仓库的 zip 归档）
TEST_ORIGIN_URL = "https://github.com/octocat/Hello-World/archive/refs/heads/master.zip"

ASSUME_LIGHT_TINT = 0xCCF2F4F8      # ABGR
ASSUME_DARK_TINT = 0xCC1B1B20

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
def log(msg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, name)
    return p if os.path.exists(p) else ""


# ----------------------------------------------------------------------------
# Windows 原生玻璃 / 圆角
# ----------------------------------------------------------------------------
class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ACCENTPOLICY)),
                ("SizeOfData", ctypes.c_size_t)]


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def is_win11():
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


class WinFx(object):
    """DWM 玻璃与圆角控制"""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.dwmapi = ctypes.windll.dwmapi
        self.ok = False

    def _accent(self, hwnd, state, flags, color):
        a = ACCENTPOLICY(state, flags, color, 0)
        d = WINCOMPATTRDATA(19, ctypes.pointer(a), ctypes.sizeof(a))
        return self.user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd),
                                                         ctypes.byref(d))

    def _extend(self, hwnd):
        m = MARGINS(-1, -1, -1, -1)
        return self.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd),
                                                        ctypes.byref(m))

    def _attr(self, hwnd, attrib, value):
        v = ctypes.c_int(value)
        return self.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attrib,
                                                 ctypes.byref(v), ctypes.sizeof(v))

    def apply_glass(self, hwnd, dark=False):
        """应用亚克力毛玻璃 + 圆角 + 无边框"""
        tint = ASSUME_DARK_TINT if dark else ASSUME_LIGHT_TINT
        res = False
        try:
            self._accent(hwnd, 3, 2, tint)          # ACCENT_ENABLE_BLURBEHIND
            self._extend(hwnd)
            self._attr(hwnd, 20, 1 if dark else 0)  # 深色标题栏
            if is_win11():
                self._attr(hwnd, 33, 2)             # 圆角偏好 ROUND
                self._attr(hwnd, 34, 0xFFFFFFFE)    # 边框颜色 NONE
                self._attr(hwnd, 38, 4)             # SYSTEMBACKDROP Tabbed
            res = True
        except Exception as e:
            log("apply_glass failed: %s" % e)
        self.ok = res
        return res

    def set_tint(self, hwnd, dark=False):
        tint = ASSUME_DARK_TINT if dark else ASSUME_LIGHT_TINT
        try:
            self._accent(hwnd, 3, 2, tint)
            self._attr(hwnd, 20, 1 if dark else 0)
        except Exception as e:
            log("set_tint failed: %s" % e)


def system_is_dark():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k)
        return v == 0
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
class Config(object):
    def __init__(self):
        self.username = ""
        self.token = ""
        self.show_token = False
        self.notes = {}
        self.sort_col = COL_TYPE
        self.sort_desc = False
        self.geometry = "1340x800"
        self.theme = "auto"            # auto / light / dark
        self.accelerators = [dict(x) for x in DEFAULT_ACCELERATORS]
        self.accel_global = True       # 全局是否对下载地址启用加速
        self.accel_active = ""         # 当前生效的加速前缀（空 = 自动选第一个启用的）
        self.load()

    def load(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                d = json.load(f)
        except Exception as e:
            log("config load failed: %s" % e)
            return
        self.username = d.get("username", "") or ""
        self.token = d.get("token", "") or ""
        self.show_token = bool(d.get("show_token", False))
        notes = d.get("notes", {})
        self.notes = notes if isinstance(notes, dict) else {}
        try:
            self.sort_col = int(d.get("sort_col", COL_TYPE) or 0)
        except (TypeError, ValueError):
            self.sort_col = COL_TYPE
        if not (0 <= self.sort_col < len(COLUMNS)):
            self.sort_col = COL_TYPE
        self.sort_desc = bool(d.get("sort_desc", False))
        self.geometry = d.get("geometry", "1340x800") or "1340x800"
        self.theme = d.get("theme", "auto")
        accs = d.get("accelerators", None)
        if isinstance(accs, list) and accs:
            out = []
            for a in accs:
                if isinstance(a, dict) and a.get("prefix"):
                    out.append({"prefix": str(a.get("prefix")).strip(),
                                "enabled": bool(a.get("enabled", True)),
                                "note": str(a.get("note", "") or "")})
            self.accelerators = out if out else [dict(x) for x in DEFAULT_ACCELERATORS]
        self.accel_global = bool(d.get("accel_global", True))
        self.accel_active = d.get("accel_active", "") or ""

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            d = {
                "username": self.username,
                "token": self.token,
                "show_token": self.show_token,
                "notes": self.notes,
                "sort_col": self.sort_col,
                "sort_desc": self.sort_desc,
                "geometry": self.geometry,
                "theme": self.theme,
                "accelerators": self.accelerators,
                "accel_global": self.accel_global,
                "accel_active": self.accel_active,
            }
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            os.rename(tmp, CONFIG_FILE)
        except Exception as e:
            log("config save failed: %s" % e)

    # --- 加速源相关 ---
    def active_prefix(self):
        """返回当前生效的加速前缀（无则空串）"""
        enabled = [a for a in self.accelerators if a.get("enabled")]
        if not enabled:
            return ""
        if self.accel_active:
            for a in enabled:
                if a["prefix"] == self.accel_active:
                    return a["prefix"]
        return enabled[0]["prefix"]

    def active_prefix_name(self):
        p = self.active_prefix()
        if not p:
            return "未启用"
        return urllib.parse.urlparse(p).netloc or p


def normalize_prefix(prefix):
    p = (prefix or "").strip()
    if not p:
        return ""
    if not p.endswith("/"):
        p += "/"
    return p


def is_accelerable(url):
    """仅对 github 下载类 https 地址拼接加速前缀"""
    if not url or not url.startswith("https://"):
        return False
    host = urllib.parse.urlparse(url).netloc.lower()
    return host.endswith("github.com") or host.endswith("githubusercontent.com") \
        or host.endswith("github-releases.githubusercontent.com") or "codeload" in host


def build_accel_url(prefix, url):
    p = normalize_prefix(prefix)
    if not p or not is_accelerable(url):
        return url
    return p + url


# ----------------------------------------------------------------------------
# GitHub API
# ----------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, kind, message):
        Exception.__init__(self, message)
        self.kind = kind
        self.message = message


def api_get(path, token=None, timeout=25):
    url = path if path.startswith("http") else API_ROOT + path
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", UA)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            body = r.read()
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ApiError("token", "Token 无效或已过期，请重新填写（也可以清空后按公开访问拉取）")
        if e.code == 404:
            raise ApiError("notfound", "用户或资源不存在（404）")
        if e.code in (403, 429):
            raise ApiError("limit", "GitHub API 访问受限（403/429）：未登录时每小时仅 60 次请求，建议填写 Token")
        raise ApiError("http", "服务器返回错误：HTTP %d" % e.code)
    except urllib.error.URLError as e:
        raise ApiError("net", "网络连接失败，请检查网络或代理设置（%s）" % getattr(e, "reason", e))
    except ssl.SSLError as e:
        raise ApiError("net", "SSL 连接失败：%s" % e)
    except json.JSONDecodeError:
        raise ApiError("parse", "返回内容无法解析，可能被网络代理拦截")
    except Exception as e:
        raise ApiError("unknown", "未知错误：%s" % e)


def pick_asset(assets):
    """从 release 资产中挑选最合适的下载文件"""
    best = None
    best_score = 999
    for a in assets or []:
        name = (a.get("name") or "").lower()
        if not name:
            continue
        if name.endswith(ASSET_IGNORE):
            continue
        score = 998
        for idx, ext in enumerate(ASSET_PRIORITY):
            if name.endswith(ext.lower()):
                score = idx
                break
        if score < best_score:
            best_score = score
            best = a
    if best:
        return best.get("browser_download_url", ""), best.get("name", ""), best.get("size", 0)
    return "", "", 0


def fetch_one_repo_download(repo, token):
    """返回 (下载地址, 来源说明)"""
    full = repo.get("full_name", "")
    branch = repo.get("default_branch", "main") or "main"
    archive = "https://github.com/%s/archive/refs/heads/%s.zip" % (full, branch)
    try:
        rel = api_get("/repos/%s/releases/latest" % full, token, timeout=15)
    except ApiError as e:
        return archive, "zip 归档" if e.kind in ("notfound", "limit", "net", "http") else "zip 归档"
    assets = rel.get("assets") or []
    url, name, size = pick_asset(assets)
    if url:
        return url, "Release 资产"
    # release 存在但无资产，尝试源码包
    return archive, "zip 归档"


def build_repo_item(repo, rtype, notes):
    full = repo.get("full_name", "")
    return {
        "key": full,
        "name": full,
        "type": rtype,
        "desc": (repo.get("description") or "").strip(),
        "note": notes.get(full, ""),
        "clone": "https://github.com/%s.git" % full,
        "download": "",
        "download_src": "",
        "stars": repo.get("stargazers_count", 0),
        "lang": repo.get("language") or "",
        "updated": (repo.get("pushed_at") or repo.get("updated_at") or "")[:10],
        "html": repo.get("html_url", ""),
    }


class FetchWorker(QThread):
    sig_progress = Signal(str)
    sig_stage = Signal(int, int)
    sig_done = Signal(list)
    sig_fail = Signal(str)

    def __init__(self, username, token, notes):
        QThread.__init__(self)
        self.username = username
        self.token = token
        self.notes = dict(notes)

    def run(self):
        try:
            self.sig_progress.emit("正在读取用户信息…")
            user = api_get("/users/%s" % self.username, self.token)
            public_repos = user.get("public_repos", 0)
            total = 0
            items = []

            self.sig_progress.emit("正在拉取 Star 列表…")
            page = 1
            stars = []
            while True:
                batch = api_get("/users/%s/starred?per_page=100&page=%d" % (self.username, page), self.token)
                if not batch:
                    break
                stars.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            self.sig_progress.emit("Star 仓库 %d 个" % len(stars))
            total += len(stars)

            self.sig_progress.emit("正在拉取自有仓库…")
            page = 1
            mine = []
            while True:
                batch = api_get("/users/%s/repos?per_page=100&page=%d&sort=pushed" % (self.username, page),
                                self.token)
                if not batch:
                    break
                mine.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            total += len(mine)

            for r in stars:
                items.append(build_repo_item(r, TYPE_STAR, self.notes))
            for r in mine:
                items.append(build_repo_item(r, TYPE_MINE, self.notes))

            self.sig_progress.emit("正在解析下载地址（0/%d）…" % total)
            done = [0]
            lock = threading.Lock()

            def work(it):
                url, src = fetch_one_repo_download(
                    {"full_name": it["key"], "default_branch": "main"}, self.token)
                # 更精确：使用仓库真实默认分支
                br = it.get("_branch") or "main"
                if src == "zip 归档" and br:
                    url = "https://github.com/%s/archive/refs/heads/%s.zip" % (it["key"], br)
                with lock:
                    it["download"] = url
                    it["download_src"] = src
                    done[0] += 1
                    if done[0] % 3 == 0 or done[0] == total:
                        self.sig_progress.emit("正在解析下载地址（%d/%d）…" % (done[0], total))
                        self.sig_stage.emit(done[0], total)

            # 记录默认分支
            br_map = {}
            for r in stars + mine:
                br_map[r.get("full_name", "")] = r.get("default_branch", "main") or "main"
            for it in items:
                it["_branch"] = br_map.get(it["key"], "main")

            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(work, items))

            for it in items:
                it.pop("_branch", None)

            rel_cnt = sum(1 for it in items if it["download_src"] == "Release 资产")
            self.sig_progress.emit("完成：共 %d 个仓库（Star %d / 自有 %d），其中 %d 个取到 Release 资产"
                                   % (len(items), len(stars), len(mine), rel_cnt))
            self.sig_done.emit(items)
        except ApiError as e:
            self.sig_fail.emit(e.message)
        except Exception as e:
            log("fetch error: %r" % e)
            self.sig_fail.emit("拉取失败：%s" % e)


class AccelTestWorker(QThread):
    """批量测试加速前缀可用性"""
    sig_one = Signal(int, bool, str)
    sig_all = Signal()

    def __init__(self, tasks):
        QThread.__init__(self)
        self.tasks = tasks  # [(row_index, prefix)]

    def _test_one(self, prefix):
        url = build_accel_url(prefix, TEST_ORIGIN_URL)
        t0 = time.time()
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Range", "bytes=0-511")
        req.add_header("Accept", "*/*")
        try:
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as r:
                status = r.getcode()
                ctype = (r.headers.get("Content-Type") or "").lower()
                body = r.read(512)
            ms = int((time.time() - t0) * 1000)
            if status not in (200, 206):
                return False, "HTTP %d（%d ms）" % (status, ms)
            if b"PK" in body[:64] or "zip" in ctype or "octet-stream" in ctype:
                return True, "可用（%d ms）" % ms
            if b"<html" in body[:200].lower() or b"<!doctype" in body[:200].lower():
                return False, "返回网页而非文件（可能被拦截）"
            if len(body) == 0:
                return False, "返回内容为空"
            return True, "可用（%d ms）" % ms
        except urllib.error.HTTPError as e:
            return False, "HTTP %d" % e.code
        except urllib.error.URLError as e:
            return False, "连接失败：%s" % getattr(e, "reason", e)
        except Exception as e:
            return False, "超时或异常：%s" % e

    def run(self):
        for row, prefix in self.tasks:
            ok, msg = self._test_one(prefix)
            self.sig_one.emit(row, ok, msg)
        self.sig_all.emit()


# ----------------------------------------------------------------------------
# 主题
# ----------------------------------------------------------------------------
def palette(dark):
    if dark:
        return {
            "dark": True,
            "card": "rgba(32,32,38,205)",
            "card_border": "rgba(255,255,255,34)",
            "text": "#F2F2F6",
            "sub": "#A2A2AD",
            "title": "#FFFFFF",
            "accent": "#4CC2FF",
            "accent_hover": "#63CCFF",
            "accent_press": "#3AA6DE",
            "on_accent": "#06243A",
            "field": "rgba(255,255,255,22)",
            "field_border": "rgba(255,255,255,40)",
            "field_focus": "#4CC2FF",
            "table_bg": "rgba(255,255,255,14)",
            "table_alt": "rgba(255,255,255,8)",
            "head": "rgba(255,255,255,26)",
            "line": "rgba(255,255,255,30)",
            "hover": "rgba(76,194,255,45)",
            "sel": "rgba(76,194,255,80)",
            "winbtn_hover": "rgba(255,255,255,34)",
            "close_hover": "#C42B1C",
            "chip": "rgba(255,255,255,18)",
            "chip_on": "rgba(76,194,255,80)",
            "shadow": "rgba(0,0,0,120)",
            "link": "#6FD0FF",
            "warn": "#FFB86C",
            "ok": "#7BE3A4",
        }
    return {
        "dark": False,
        "card": "rgba(255,255,255,198)",
        "card_border": "rgba(255,255,255,235)",
        "text": "#1B1B1F",
        "sub": "#5C5C66",
        "title": "#141418",
        "accent": "#0067C0",
        "accent_hover": "#1877CE",
        "accent_press": "#00529B",
        "on_accent": "#FFFFFF",
        "field": "rgba(255,255,255,225)",
        "field_border": "rgba(0,0,0,38)",
        "field_focus": "#0067C0",
        "table_bg": "rgba(255,255,255,170)",
        "table_alt": "rgba(246,247,251,150)",
        "head": "rgba(255,255,255,205)",
        "line": "rgba(0,0,0,26)",
        "hover": "rgba(0,103,192,30)",
        "sel": "rgba(0,103,192,62)",
        "winbtn_hover": "rgba(0,0,0,26)",
        "close_hover": "#C42B1C",
        "chip": "rgba(0,0,0,16)",
        "chip_on": "rgba(0,103,192,52)",
        "shadow": "rgba(0,0,0,80)",
        "link": "#0B62B8",
        "warn": "#B25E00",
        "ok": "#1A7F45",
    }


def build_qss(p, radius):
    return """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }
QWidget { color: %(text)s; font-size: 10pt; }
QLabel { background: transparent; }
QLabel#AppTitle { color: %(title)s; font-size: 11.5pt; font-weight: 600; }
QLabel#AppSub { color: %(sub)s; font-size: 9pt; }
QLabel#FieldLabel { color: %(sub)s; font-size: 9pt; }
QLabel#Status { color: %(sub)s; font-size: 9pt; }
QLabel#Hint { color: %(sub)s; font-size: 9pt; }
QFrame#Card { background: %(card)s; border: 1px solid %(card_border)s; border-radius: %(radius)dpx; }
QFrame#Block { background: %(chip)s; border: 1px solid %(line)s; border-radius: 10px; }
QFrame#Divider { background: %(line)s; max-height: 1px; border: none; }
QLineEdit, QSpinBox {
    background: %(field)s; border: 1px solid %(field_border)s; border-radius: 7px;
    padding: 6px 10px; selection-background-color: %(accent)s; selection-color: %(on_accent)s;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid %(field_focus)s; }
QLineEdit:disabled { color: %(sub)s; }
QPushButton {
    background: %(chip)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 7px; padding: 6px 14px; font-size: 9.5pt;
}
QPushButton:hover { background: %(hover)s; }
QPushButton:pressed { background: %(sel)s; }
QPushButton:disabled { color: %(sub)s; background: transparent; border: 1px solid %(line)s; }
QPushButton#Primary {
    background: %(accent)s; color: %(on_accent)s; border: none; font-weight: 600; padding: 7px 18px;
}
QPushButton#Primary:hover { background: %(accent_hover)s; }
QPushButton#Primary:pressed { background: %(accent_press)s; }
QPushButton#Ghost { background: transparent; border: 1px solid transparent; padding: 5px 10px; }
QPushButton#Ghost:hover { background: %(hover)s; }
QPushButton#Chip { background: transparent; border: 1px solid %(line)s; border-radius: 14px; padding: 4px 14px; color: %(sub)s; }
QPushButton#Chip:hover { background: %(hover)s; }
QPushButton#Chip:checked { background: %(chip_on)s; color: %(text)s; border: 1px solid %(accent)s; font-weight: 600; }
QPushButton#WinBtn { background: transparent; border: none; border-radius: 6px; padding: 0px; color: %(text)s; }
QPushButton#WinBtn:hover { background: %(winbtn_hover)s; }
QPushButton#CloseBtn { background: transparent; border: none; border-radius: 6px; padding: 0px; color: %(text)s; }
QPushButton#CloseBtn:hover { background: %(close_hover)s; color: #FFFFFF; }
QPushButton#Danger { background: transparent; border: 1px solid %(line)s; color: #D9534F; }
QPushButton#Danger:hover { background: rgba(217,83,79,60); }
QCheckBox { color: %(text)s; spacing: 7px; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid %(field_border)s; background: %(field)s;
}
QCheckBox::indicator:checked { background: %(accent)s; border: 1px solid %(accent)s; }
QComboBox {
    background: %(field)s; border: 1px solid %(field_border)s; border-radius: 7px; padding: 5px 10px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: %(card)s; border: 1px solid %(line)s; selection-background-color: %(accent)s;
    selection-color: %(on_accent)s; outline: none;
}
QTableWidget {
    background: %(table_bg)s; border: none; border-radius: 10px;
    alternate-background-color: %(table_alt)s; gridline-color: transparent;
    selection-background-color: %(sel)s; selection-color: %(text)s;
    outline: none;
}
QTableWidget::item { padding: 4px 6px; border: none; }
QTableWidget::item:hover { background: %(hover)s; }
QTableWidget::item:selected { background: %(sel)s; color: %(text)s; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: %(head)s; color: %(sub)s; border: none; border-right: 1px solid %(line)s;
    border-bottom: 1px solid %(line)s; padding: 7px 8px; font-size: 9pt; font-weight: 600;
}
QHeaderView::section:hover { background: %(hover)s; }
QHeaderView::section:last { border-right: none; }
QTableCornerButton::section { background: %(head)s; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(field_border)s; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(field_border)s; border-radius: 5px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QProgressBar {
    background: %(chip)s; border: none; border-radius: 3px; height: 6px; text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 3px; }
QMenu {
    background: %(card)s; border: 1px solid %(line)s; border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: %(hover)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 5px 8px; }
QToolTip {
    background: %(card)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 6px 8px;
}
QDialog { background: transparent; }
QMessageBox { background: %(card)s; }
QMessageBox QLabel { color: %(text)s; }
QSplitter::handle { background: transparent; }
""" % dict(p, radius=radius)


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
class GlassBase(object):
    """无边框毛玻璃窗口 mixin：DWM 玻璃 + 圆角 + 自绘高光卡片"""

    def init_glass(self, cfg):
        self.cfg = cfg
        self.fx = WinFx()
        self._dark = system_is_dark() if cfg.theme == "auto" else (cfg.theme == "dark")
        self.p = palette(self._dark)
        self.card_radius = 16
        self._drag_offset = None
        self._resizing = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(1180, 640)
        self.setWindowTitle(APP_NAME)
        ic = resource_path("app.ico")
        if ic:
            self.setWindowIcon(QIcon(ic))
        self.glass_enabled = True

    # --- 玻璃 ---
    def apply_glass(self):
        # 系统级模糊（Windows 11 亚克力拟态）：成功则窗口背后内容被模糊，
        # 失败也保留自绘半透明卡片，视觉上依然是毛玻璃风格
        try:
            self.glass_enabled = bool(self.fx.apply_glass(int(self.winId()), self._dark))
        except Exception as e:
            log("apply_glass wrapper failed: %s" % e)
            self.glass_enabled = False

    def repaint_glass(self):
        self.p = palette(self._dark)
        try:
            self.fx.set_tint(int(self.winId()), self._dark)
        except Exception as e:
            log("set_tint wrapper failed: %s" % e)
        self.update()

    def paintEvent(self, e):
        pnt = QPainter(self)
        pnt.setRenderHint(QPainter.Antialiasing)
        r = 0 if self.isMaximized() else self.card_radius
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        # 半透明底色：浅色模式为乳白雾面，深色模式为炭黑雾面
        base = QColor(248, 249, 252, 172) if not self._dark else QColor(24, 24, 28, 158)
        pnt.setPen(Qt.NoPen)
        pnt.setBrush(QBrush(base))
        pnt.drawPath(path)
        # 顶部高光 + 底部微暗，营造玻璃质感
        grad = QLinearGradient(0, 0, 0, self.height())
        if self._dark:
            grad.setColorAt(0.0, QColor(255, 255, 255, 34))
            grad.setColorAt(0.35, QColor(255, 255, 255, 10))
            grad.setColorAt(1.0, QColor(0, 0, 0, 46))
            edge = QColor(255, 255, 255, 40)
        else:
            grad.setColorAt(0.0, QColor(255, 255, 255, 150))
            grad.setColorAt(0.35, QColor(255, 255, 255, 60))
            grad.setColorAt(1.0, QColor(214, 224, 240, 70))
            edge = QColor(255, 255, 255, 210)
        pnt.setBrush(QBrush(grad))
        pnt.drawPath(path)
        # 1px 描边，圆角处更柔和
        pnt.setBrush(Qt.NoBrush)
        pnt.setPen(QPen(edge, 1))
        pnt.drawPath(path)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_glass_applied", False):
            self._glass_applied = True
            self.apply_glass()
            self.repaint_glass()

    # --- 拖动 / 尺寸 ---
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and not self.isMaximized():
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self.update()

    def closeEvent(self, e):
        geo = self.geometry()
        if geo.width() >= 1000 and geo.height() >= 600:
            self.cfg.geometry = "%dx%d" % (geo.width(), geo.height())
        self.cfg.save()
        super().closeEvent(e)


class TitleBar(QWidget):
    def __init__(self, win):
        QWidget.__init__(self)
        self.win = win
        self.setFixedHeight(46)
        self.setObjectName("TitleBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(8)

        ic = resource_path("app.ico")
        self.logo = QLabel()
        if ic:
            pm = QPixmap(ic).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo.setPixmap(pm)
        lay.addWidget(self.logo)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("AppTitle")
        lay.addWidget(self.title)
        ver = QLabel("v" + APP_VERSION)
        ver.setObjectName("AppSub")
        lay.addWidget(ver)
        lay.addStretch(1)

        self.btn_menu = QPushButton("⋮")
        self.btn_menu.setObjectName("WinBtn")
        self.btn_menu.setFixedSize(34, 26)
        self.btn_menu.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.btn_menu)

        self.btn_theme = QPushButton("◐")
        self.btn_theme.setObjectName("WinBtn")
        self.btn_theme.setFixedSize(34, 26)
        self.btn_theme.setToolTip("切换深色/浅色外观")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.btn_theme)

        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("WinBtn")
        self.btn_min.setFixedSize(38, 26)
        self.btn_min.setCursor(Qt.PointingHandCursor)
        self.btn_min.setToolTip("最小化")
        lay.addWidget(self.btn_min)

        self.btn_max = QPushButton("□")
        self.btn_max.setObjectName("WinBtn")
        self.btn_max.setFixedSize(38, 26)
        self.btn_max.setCursor(Qt.PointingHandCursor)
        self.btn_max.setToolTip("最大化/还原")
        lay.addWidget(self.btn_max)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setFixedSize(38, 26)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip("关闭")
        lay.addWidget(self.btn_close)

    def mousePressEvent(self, e):
        self.win.mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self.win.mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self.win.mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_max()


# ----------------------------------------------------------------------------
# 下载加速设置对话框
# ----------------------------------------------------------------------------
class AccelEditDialog(GlassBase, QDialog):
    """单个加速源的编辑对话框"""

    def __init__(self, cfg, parent=None, prefix="", note=""):
        QDialog.__init__(self, parent)
        self.init_glass(cfg)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setMinimumWidth(620)
        self.resize(660, 340)
        self.setWindowTitle("加速源")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        t = QLabel("加速源设置")
        t.setObjectName("AppTitle")
        lay.addWidget(t)

        hint = QLabel("填写加速前缀，程序会把前缀直接拼在原始 GitHub 下载地址前面（自动补全结尾的 /）。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addWidget(self._label("加速前缀"))
        self.ed_prefix = QLineEdit()
        self.ed_prefix.setPlaceholderText("例如 https://ghproxy.net/")
        self.ed_prefix.setText(prefix)
        lay.addWidget(self.ed_prefix)

        lay.addWidget(self._label("备注（可选）"))
        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("例如：公共代理，速度较快")
        self.ed_note.setText(note)
        lay.addWidget(self.ed_note)

        self.lb_preview = QLabel()
        self.lb_preview.setObjectName("Hint")
        self.lb_preview.setWordWrap(True)
        self.lb_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lb_preview)
        lay.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_cancel)
        b_ok = QPushButton("确定")
        b_ok.setObjectName("Primary")
        b_ok.clicked.connect(self.on_ok)
        row.addWidget(b_ok)
        lay.addLayout(row)

        self.ed_prefix.textChanged.connect(self.update_preview)
        self.update_preview()
        self.apply_theme_qss()

    def _label(self, text):
        lb = QLabel(text)
        lb.setObjectName("FieldLabel")
        return lb

    def apply_theme_qss(self):
        self.setStyleSheet(build_qss(palette(self._dark), 14))

    def update_preview(self):
        p = normalize_prefix(self.ed_prefix.text())
        sample = "https://github.com/owner/repo/releases/download/v1/app.exe"
        if not p:
            self.lb_preview.setText("拼接预览：请输入加速前缀")
            return
        self.lb_preview.setText("拼接预览：\n%s\n  +\n%s\n  →\n%s"
                                % (p, sample, build_accel_url(p, sample)))

    def on_ok(self):
        p = normalize_prefix(self.ed_prefix.text())
        if not p:
            QMessageBox.warning(self, "提示", "加速前缀不能为空。")
            return
        if not (p.startswith("http://") or p.startswith("https://")):
            QMessageBox.warning(self, "提示", "加速前缀需要以 http:// 或 https:// 开头。")
            return
        self.result_prefix = p
        self.result_note = self.ed_note.text().strip()
        self.accept()


class AccelDialog(GlassBase, QDialog):
    """下载加速设置面板"""

    def __init__(self, cfg, parent=None):
        QDialog.__init__(self, parent)
        self.init_glass(cfg)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setMinimumSize(880, 560)
        self.resize(920, 620)
        self.setWindowTitle("下载加速设置")
        self.test_worker = None
        self.rows = []
        self.build_ui()
        self.load_rows()
        self.setStyleSheet(build_qss(palette(self._dark), 14))

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(0)

        head = QWidget()
        head.setFixedHeight(48)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 0, 8, 0)
        t = QLabel("下载加速设置")
        t.setObjectName("AppTitle")
        hl.addWidget(t)
        hl.addStretch(1)
        b_close = QPushButton("✕")
        b_close.setObjectName("CloseBtn")
        b_close.setFixedSize(38, 26)
        b_close.setCursor(Qt.PointingHandCursor)
        b_close.clicked.connect(self.reject)
        hl.addWidget(b_close)
        root.addWidget(head)

        body = QWidget()
        root.addWidget(body, 1)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 4, 22, 16)
        lay.setSpacing(10)

        desc = QLabel(
            "加速原理：加速地址 = 加速前缀 + 原始 GitHub 下载地址（前缀直接拼接在原始地址前面）。\n"
            "例：前缀 https://ghproxy.net/ 与原始地址 https://github.com/owner/repo/releases/download/v1/app.exe "
            "拼接后为 https://ghproxy.net/https://github.com/owner/repo/releases/download/v1/app.exe\n"
            "仅对 https://github.com/... 与 https://objects.githubusercontent.com/... 等 GitHub 下载地址生效，"
            "加速失败时可随时回退原始地址。")
        desc.setObjectName("Hint")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        line = QHBoxLayout()
        line.setSpacing(10)
        self.ck_global = QCheckBox("对列表中全部下载地址启用加速")
        line.addWidget(self.ck_global)
        line.addSpacing(14)
        lb = QLabel("当前生效源：")
        lb.setObjectName("FieldLabel")
        line.addWidget(lb)
        self.cb_active = QComboBox()
        self.cb_active.setMinimumWidth(280)
        line.addWidget(self.cb_active)
        line.addStretch(1)
        lay.addLayout(line)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["启用", "加速前缀", "备注", "测试状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setDefaultSectionSize(32)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 60)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 200)
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 210)
        self.table.itemDoubleClicked.connect(lambda _i: self.on_edit())
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        b_add = QPushButton("添加")
        b_add.clicked.connect(self.on_add)
        b_edit = QPushButton("编辑")
        b_edit.clicked.connect(self.on_edit)
        b_del = QPushButton("删除")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self.on_delete)
        b_up = QPushButton("上移")
        b_up.clicked.connect(lambda: self.on_move(-1))
        b_dn = QPushButton("下移")
        b_dn.clicked.connect(lambda: self.on_move(1))
        self.btn_test = QPushButton("测试可用性")
        self.btn_test.setObjectName("Primary")
        self.btn_test.clicked.connect(self.on_test)
        for b in (b_add, b_edit, b_del, b_up, b_dn):
            btns.addWidget(b)
        btns.addWidget(self.btn_test)
        btns.addStretch(1)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        b_save = QPushButton("保存")
        b_save.setObjectName("Primary")
        b_save.setMinimumWidth(90)
        b_save.clicked.connect(self.on_save)
        btns.addWidget(b_cancel)
        btns.addWidget(b_save)
        lay.addLayout(btns)

        tip = QLabel("提示：可点击「测试可用性」对选中的加速源（不选则测试全部）真实发起一次下载请求，"
                     "测试目标是 GitHub 官方示例仓库的 zip 包。测试结果为「可用」才建议启用。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

    # --- 数据 ---
    def load_rows(self):
        self.table.setRowCount(0)
        self.rows = [dict(a) for a in self.cfg.accelerators]
        self.table.setRowCount(len(self.rows))
        for r, a in enumerate(self.rows):
            self._write_row(r, a)
        self.ck_global.setChecked(self.cfg.accel_global)
        self.refresh_active_combo()

    def _write_row(self, r, a, status=""):
        ci = QTableWidgetItem("")
        ci.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        ci.setCheckState(Qt.Checked if a.get("enabled") else Qt.Unchecked)
        self.table.setItem(r, 0, ci)
        self.table.setItem(r, 1, QTableWidgetItem(a.get("prefix", "")))
        self.table.setItem(r, 2, QTableWidgetItem(a.get("note", "")))
        st = QTableWidgetItem(status)
        st.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 3, st)

    def collect(self):
        out = []
        for r in range(self.table.rowCount()):
            ci = self.table.item(r, 0)
            pi = self.table.item(r, 1)
            ni = self.table.item(r, 2)
            p = normalize_prefix(pi.text() if pi else "")
            if not p:
                continue
            out.append({"prefix": p,
                        "enabled": bool(ci and ci.checkState() == Qt.Checked),
                        "note": (ni.text() if ni else "").strip()})
        return out

    def refresh_active_combo(self):
        cur = self.cb_active.currentText()
        self.cb_active.clear()
        items = self.collect()
        self._combo_prefix = []
        for a in items:
            if a["enabled"]:
                self.cb_active.addItem(a["prefix"] + ("  ·  " + a["note"] if a["note"] else ""))
                self._combo_prefix.append(a["prefix"])
        if self.cfg.accel_active in self._combo_prefix:
            self.cb_active.setCurrentIndex(self._combo_prefix.index(self.cfg.accel_active))
        elif self.cb_active.count() and cur:
            idx = self.cb_active.findText(cur)
            if idx >= 0:
                self.cb_active.setCurrentIndex(idx)
        if not self.cb_active.count():
            self.cb_active.addItem("（没有启用的加速源）")
            self._combo_prefix = [""]

    def _sel_rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    # --- 操作 ---
    def on_add(self):
        dlg = AccelEditDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.rows.append({"prefix": dlg.result_prefix, "enabled": True,
                              "note": dlg.result_note})
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._write_row(r, self.rows[-1])
            self.refresh_active_combo()

    def on_edit(self):
        rows = self._sel_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要编辑的加速源。")
            return
        r = rows[0]
        pi = self.table.item(r, 1)
        ni = self.table.item(r, 2)
        dlg = AccelEditDialog(self.cfg, self, pi.text() if pi else "", ni.text() if ni else "")
        if dlg.exec() == QDialog.Accepted:
            d = {"prefix": dlg.result_prefix, "enabled": True, "note": dlg.result_note}
            ci = self.table.item(r, 0)
            d["enabled"] = bool(ci and ci.checkState() == Qt.Checked)
            self.rows[r] = d
            self._write_row(r, d, "")
            self.refresh_active_combo()

    def on_delete(self):
        rows = self._sel_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要删除的加速源。")
            return
        if QMessageBox.question(self, "确认删除",
                                "确定删除选中的 %d 个加速源配置吗？（不会删除任何本地文件）" % len(rows),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        for r in sorted(rows, reverse=True):
            self.table.removeRow(r)
        self.refresh_active_combo()

    def on_move(self, delta):
        rows = self._sel_rows()
        if len(rows) != 1:
            return
        r = rows[0]
        t = r + delta
        if t < 0 or t >= self.table.rowCount():
            return
        a = self._row_data(r)
        b = self._row_data(t)
        self._write_row(r, b)
        self._write_row(t, a)
        self.table.selectRow(t)

    def _row_data(self, r):
        ci = self.table.item(r, 0)
        pi = self.table.item(r, 1)
        ni = self.table.item(r, 2)
        return {"prefix": pi.text() if pi else "",
                "enabled": bool(ci and ci.checkState() == Qt.Checked),
                "note": ni.text() if ni else ""}

    def on_test(self):
        rows = self._sel_rows() or list(range(self.table.rowCount()))
        tasks = []
        for r in rows:
            pi = self.table.item(r, 1)
            p = normalize_prefix(pi.text() if pi else "")
            if p:
                tasks.append((r, p))
                st = self.table.item(r, 3)
                if st:
                    st.setText("测试中…")
                    st.setForeground(QBrush(QColor("#8A8A94")))
        if not tasks:
            QMessageBox.information(self, "提示", "没有可测试的加速源。")
            return
        self.btn_test.setEnabled(False)
        self.btn_test.setText("测试中…")
        self.test_worker = AccelTestWorker(tasks)
        self.test_worker.sig_one.connect(self.on_test_one)
        self.test_worker.sig_all.connect(self.on_test_all)
        self.test_worker.start()

    def on_test_one(self, row, ok, msg):
        if row >= self.table.rowCount():
            return
        st = self.table.item(row, 3)
        if not st:
            return
        pal = palette(self._dark)
        if ok:
            st.setText("可用 · " + msg.replace("可用", "").strip("（） "))
            st.setForeground(QBrush(QColor(pal["ok"])))
        else:
            st.setText("不可用 · " + msg)
            st.setForeground(QBrush(QColor("#E0605C")))
        st.setToolTip(msg)

    def on_test_all(self):
        self.btn_test.setEnabled(True)
        self.btn_test.setText("测试可用性")

    def on_save(self):
        items = self.collect()
        if not items:
            QMessageBox.warning(self, "提示", "至少需要保留一个加速源（也可以直接取消，保持原有配置）。")
            return
        self.cfg.accelerators = items
        self.cfg.accel_global = self.ck_global.isChecked()
        idx = self.cb_active.currentIndex()
        if 0 <= idx < len(getattr(self, "_combo_prefix", [])):
            self.cfg.accel_active = self._combo_prefix[idx]
        else:
            self.cfg.accel_active = ""
        self.cfg.save()
        self.accept()


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
class MainWindow(GlassBase, QWidget):
    def __init__(self, cfg):
        QWidget.__init__(self)
        self.init_glass(cfg)
        self.items = []
        self.by_key = {}
        self.fetch_worker = None
        self.accel_dialog = None
        self._filter_mode = "all"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.cfg.save)

        self.build_ui()
        self.apply_theme()
        self.restore_geometry()
        self.load_config_into_ui()

    # ------------------------------------------------------------------ UI
    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)
        div = QFrame()
        div.setObjectName("Divider")
        div.setFixedHeight(1)
        root.addWidget(div)

        body = QWidget()
        root.addWidget(body, 1)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 10, 18, 8)
        bl.setSpacing(9)

        # 第一行：账号
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(self._field_label("用户名"))
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText("GitHub 用户名")
        self.ed_user.setFixedWidth(170)
        self.ed_user.returnPressed.connect(self.start_fetch)
        r1.addWidget(self.ed_user)
        r1.addSpacing(6)
        r1.addWidget(self._field_label("Token"))
        self.ed_token = QLineEdit()
        self.ed_token.setPlaceholderText("可选，填写后 API 限额更高")
        self.ed_token.setEchoMode(QLineEdit.Password)
        self.ed_token.setFixedWidth(220)
        r1.addWidget(self.ed_token)
        self.ck_show_token = QCheckBox("显示")
        r1.addWidget(self.ck_show_token)
        r1.addStretch(1)
        self.btn_fetch = QPushButton("拉取仓库")
        self.btn_fetch.setObjectName("Primary")
        self.btn_fetch.setMinimumWidth(112)
        self.btn_fetch.setCursor(Qt.PointingHandCursor)
        self.btn_fetch.setToolTip("从 GitHub 拉取 Star 列表与自有仓库（快捷键 F5）")
        r1.addWidget(self.btn_fetch)
        bl.addLayout(r1)

        # 第二行：筛选 / 搜索 / 加速 / 导出
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.seg = QButtonGroup(self)
        self.seg.setExclusive(True)
        self._seg_buttons = {}
        for key, text in (("all", "全部"), ("star", "Star"), ("mine", "我的仓库")):
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.on_filter(k))
            self.seg.addButton(b)
            self._seg_buttons[key] = b
            r2.addWidget(b)
        self._seg_buttons["all"].setChecked(True)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索项目名称 / 描述 / 备注")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setFixedWidth(250)
        self.ed_search.textChanged.connect(self.apply_filters)
        r2.addWidget(self.ed_search)

        self.ck_accel = QCheckBox("下载地址加速")
        self.ck_accel.setToolTip("开启后，列表中所有下载地址都使用当前加速源前缀拼接")
        r2.addWidget(self.ck_accel)

        self.btn_accel = QPushButton("加速设置")
        self.btn_accel.setCursor(Qt.PointingHandCursor)
        r2.addWidget(self.btn_accel)

        r2.addStretch(1)
        self.btn_export = QPushButton("导出 CSV")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        r2.addWidget(self.btn_export)
        bl.addLayout(r2)

        # 表格
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(31)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_DL, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_KEY, 220)
        self.table.setColumnWidth(COL_TYPE, 84)
        self.table.setColumnWidth(COL_NOTE, 130)
        self.table.setColumnWidth(COL_CLONE, 240)
        bl.addWidget(self.table, 1)

        # 状态行
        sr = QHBoxLayout()
        sr.setSpacing(10)
        self.lb_status = QLabel("就绪：填写用户名后点击「拉取仓库」，或按 F5")
        self.lb_status.setObjectName("Status")
        sr.addWidget(self.lb_status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        sr.addWidget(self.progress)
        self.lb_accel = QLabel()
        self.lb_accel.setObjectName("Status")
        sr.addWidget(self.lb_accel)
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        sr.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)
        bl.addLayout(sr)

        # 信号
        self.btn_fetch.clicked.connect(self.start_fetch)
        self.btn_accel.clicked.connect(self.open_accel_dialog)
        self.btn_export.clicked.connect(self.export_csv)
        self.ck_accel.toggled.connect(self.on_accel_toggle)
        self.ck_show_token.toggled.connect(self.on_show_token)
        self.table.customContextMenuRequested.connect(self.on_table_menu)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.titlebar.btn_close.clicked.connect(self.close)
        self.titlebar.btn_min.clicked.connect(self.showMinimized)
        self.titlebar.btn_max.clicked.connect(self.toggle_max)
        self.titlebar.btn_theme.clicked.connect(self.cycle_theme)
        self.titlebar.btn_menu.clicked.connect(self.show_main_menu)

    def _field_label(self, text):
        lb = QLabel(text)
        lb.setObjectName("FieldLabel")
        return lb

    # -------------------------------------------------------------- 主题
    def apply_theme(self):
        self._dark = system_is_dark() if self.cfg.theme == "auto" else (self.cfg.theme == "dark")
        self.p = palette(self._dark)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_qss(self.p, self.card_radius))
        self.repaint_glass()
        t = {"auto": "跟随系统（点击切换）", "light": "浅色模式", "dark": "深色模式"}[self.cfg.theme]
        self.titlebar.btn_theme.setToolTip("外观：" + t)
        self.titlebar.title.setStyleSheet("color: %s;" % self.p["title"])
        pal = palette(self._dark)
        self.lb_status.setStyleSheet("color: %s; font-size: 9pt;" % pal["sub"])
        self.lb_accel.setStyleSheet("color: %s; font-size: 9pt;" % pal["sub"])
        self.refresh_accel_label()
        self.refresh_download_column()

    def cycle_theme(self):
        order = ["auto", "light", "dark"]
        i = order.index(self.cfg.theme) if self.cfg.theme in order else 0
        self.cfg.theme = order[(i + 1) % 3]
        self.cfg.save()
        self.apply_theme()
        self.set_status("外观已切换为：%s" % {"auto": "跟随系统", "light": "浅色", "dark": "深色"}[self.cfg.theme])

    # -------------------------------------------------------------- 几何
    def restore_geometry(self):
        g = (self.cfg.geometry or "1340x800").lower().replace("*", "x").split("x")
        try:
            w, h = int(g[0]), int(g[1])
        except Exception:
            w, h = 1340, 800
        if w < 1000 or h < 600:
            w, h = 1360, 820
        self.resize(w, h)
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - w // 2, max(geo.top() + 20, geo.center().y() - h // 2))

    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ---------------------------------------------------------- 配置回填
    def load_config_into_ui(self):
        self.ed_user.setText(self.cfg.username)
        self.ed_token.setText(self.cfg.token)
        self.ck_show_token.setChecked(self.cfg.show_token)
        self.ed_token.setEchoMode(QLineEdit.Normal if self.cfg.show_token else QLineEdit.Password)
        self.ck_accel.setChecked(self.cfg.accel_global)
        self.refresh_accel_label()

    def refresh_accel_label(self):
        if not self.cfg.accel_global:
            self.lb_accel.setText("加速：已关闭（使用原始地址）")
            return
        pre = self.cfg.active_prefix()
        if pre:
            self.lb_accel.setText("加速源：%s" % self.cfg.active_prefix_name())
        else:
            self.lb_accel.setText("加速：未配置可用加速源")

    def on_show_token(self, checked):
        self.cfg.show_token = checked
        self.ed_token.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._save_timer.start(600)

    def on_accel_toggle(self, checked):
        self.cfg.accel_global = checked
        self.cfg.save()
        self.refresh_accel_label()
        self.refresh_download_column()
        self.set_status("下载地址加速已%s" % ("开启" if checked else "关闭"))

    # ------------------------------------------------------------ 拉取
    def start_fetch(self):
        user = self.ed_user.text().strip()
        if not user:
            QMessageBox.information(self, "提示", "请先填写 GitHub 用户名。")
            self.ed_user.setFocus()
            return
        if self.fetch_worker and self.fetch_worker.isRunning():
            self.set_status("正在拉取中，请稍候…")
            return
        token = self.ed_token.text().strip()
        self.cfg.username = user
        self.cfg.token = token
        self.cfg.save()
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("拉取中…")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.set_status("正在连接 GitHub…")
        self.fetch_worker = FetchWorker(user, token, self.cfg.notes)
        self.fetch_worker.sig_progress.connect(self.set_status)
        self.fetch_worker.sig_done.connect(self.on_fetch_done)
        self.fetch_worker.sig_fail.connect(self.on_fetch_fail)
        self.fetch_worker.start()

    def on_fetch_done(self, items):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("拉取仓库")
        self.progress.setVisible(False)
        self.items = items
        self.by_key = {it["key"]: it for it in items}
        self.fill_table()
        self.apply_filters()
        star = sum(1 for it in items if it["type"] == TYPE_STAR)
        rel = sum(1 for it in items if it["download_src"] == "Release 资产")
        self.set_status("已拉取 %d 个仓库（Star %d / 自有 %d），%d 个含 Release 资产"
                        % (len(items), star, len(items) - star, rel))

    def on_fetch_fail(self, msg):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("拉取仓库")
        self.progress.setVisible(False)
        self.set_status(msg)
        QMessageBox.warning(self, "拉取失败", msg)

    # ------------------------------------------------------------ 表格
    def fill_table(self):
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            i0 = QTableWidgetItem(it["name"])
            i0.setData(Qt.UserRole, it["key"])
            i0.setToolTip(it.get("html") or it["name"])
            f = i0.font()
            f.setBold(True)
            i0.setFont(f)
            i0.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, COL_KEY, i0)

            i1 = QTableWidgetItem(it["type"])
            i1.setTextAlignment(Qt.AlignCenter)
            i1.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            i1.setToolTip("Star：我标星的仓库 / 我的仓库：自己创建的仓库")
            self.table.setItem(r, COL_TYPE, i1)

            i2 = QTableWidgetItem(it["desc"])
            i2.setToolTip(it["desc"] or "（无描述）")
            i2.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, COL_DESC, i2)

            i3 = QTableWidgetItem(it["note"])
            i3.setToolTip("双击可编辑备注")
            self.table.setItem(r, COL_NOTE, i3)

            i4 = QTableWidgetItem(it["clone"])
            i4.setToolTip(it["clone"])
            i4.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, COL_CLONE, i4)

            i5 = QTableWidgetItem("")
            i5.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, COL_DL, i5)

        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        self.refresh_download_column()
        self.refresh_type_colors()
        col = max(0, min(COL_TYPE, len(COLUMNS) - 1))
        self.table.sortItems(col, Qt.AscendingOrder if not self.cfg.sort_desc else Qt.DescendingOrder)

    def refresh_type_colors(self):
        pal = palette(self._dark)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_TYPE)
            if not it:
                continue
            if it.text() == TYPE_STAR:
                it.setForeground(QBrush(QColor(pal["accent"])))
            else:
                it.setForeground(QBrush(QColor(pal["ok"] if self._dark else "#0E7A4A")))

    def _accel_pair(self, it):
        """返回 (展示地址, 是否加速)"""
        url = it.get("download") or ""
        if self.cfg.accel_global and url:
            pre = self.cfg.active_prefix()
            if pre and is_accelerable(url):
                return build_accel_url(pre, url), True
        return url, False

    def refresh_download_column(self):
        pal = palette(self._dark)
        for r in range(self.table.rowCount()):
            key = self._row_key(r)
            it = self.by_key.get(key)
            cell = self.table.item(r, COL_DL)
            if not it or not cell:
                continue
            shown, accel = self._accel_pair(it)
            cell.setText(shown)
            if accel:
                cell.setForeground(QBrush(QColor(pal["link"])))
                cell.setToolTip("加速地址（%s）：\n%s\n\n原始地址：\n%s\n\n右键可复制/打开原始或加速地址"
                                % (self.cfg.active_prefix_name(), shown, it.get("download") or ""))
            else:
                cell.setForeground(QBrush(QColor(pal["text"] if not self._dark else "#D8D8DE")))
                cell.setToolTip("原始地址：\n%s\n\n来源：%s\n右键可复制/打开"
                                % (it.get("download") or "", it.get("download_src") or "zip 归档"))

    def _row_key(self, r):
        it = self.table.item(r, COL_KEY)
        return it.data(Qt.UserRole) if it else None

    def current_item(self):
        r = self.table.currentRow()
        if r < 0:
            rows = sorted({i.row() for i in self.table.selectedIndexes()})
            r = rows[0] if rows else -1
        if r < 0:
            return None
        return self.by_key.get(self._row_key(r))

    def selected_items(self):
        out = []
        for r in sorted({i.row() for i in self.table.selectedIndexes()}):
            it = self.by_key.get(self._row_key(r))
            if it:
                out.append(it)
        return out

    def on_item_changed(self, item):
        if item.column() != COL_NOTE:
            return
        key = self._row_key(item.row())
        if not key:
            return
        txt = item.text().strip()
        if txt:
            self.cfg.notes[key] = txt
        else:
            self.cfg.notes.pop(key, None)
        if key in self.by_key:
            self.by_key[key]["note"] = txt
        self._save_timer.start(700)

    def on_item_double_clicked(self, item):
        if item.column() == COL_NOTE:
            self.edit_note()
        elif item.column() == COL_DL:
            self.open_download(True)
        else:
            self.open_home()

    def on_filter(self, key):
        self._filter_mode = key
        self.apply_filters()

    def apply_filters(self):
        kw = self.ed_search.text().strip().lower()
        for r in range(self.table.rowCount()):
            it = self.by_key.get(self._row_key(r))
            show = True
            if it:
                if self._filter_mode == "star" and it["type"] != TYPE_STAR:
                    show = False
                if self._filter_mode == "mine" and it["type"] != TYPE_MINE:
                    show = False
                if kw:
                    blob = "%s %s %s" % (it["name"], it["desc"], it["note"])
                    if kw not in blob.lower():
                        show = False
            self.table.setRowHidden(r, not show)
        vis = sum(1 for r in range(self.table.rowCount()) if not self.table.isRowHidden(r))
        if self.items:
            self.set_status("显示 %d / %d 个仓库" % (vis, len(self.items)))

    # -------------------------------------------------------- 加速设置
    def open_accel_dialog(self):
        dlg = AccelDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.ck_accel.setChecked(self.cfg.accel_global)
            self.refresh_accel_label()
            self.refresh_download_column()
            pre = self.cfg.active_prefix()
            self.set_status("加速设置已保存，当前加速源：%s" % (pre or "未启用"))
        else:
            self.refresh_accel_label()

    # ------------------------------------------------------------ 操作
    def set_status(self, text):
        self.lb_status.setText(text)

    def _clipboard(self, text):
        if not text:
            QMessageBox.information(self, "提示", "没有可复制的内容。")
            return
        QApplication.clipboard().setText(text)
        self.set_status("已复制到剪贴板：%s" % text)

    def copy_clone(self):
        it = self.current_item()
        if it:
            self._clipboard(it["clone"])

    def copy_download(self, use_accel=None):
        it = self.current_item()
        if not it:
            QMessageBox.information(self, "提示", "请先在列表中选择一个仓库。")
            return
        url = it.get("download") or ""
        if not url:
            QMessageBox.information(self, "提示", "该仓库暂时没有可用的下载地址。")
            return
        if use_accel is None:
            shown, accel = self._accel_pair(it)
            self._clipboard(shown)
            return
        if use_accel:
            pre = self.cfg.active_prefix()
            if not pre:
                QMessageBox.information(self, "提示",
                                        "还没有启用任何加速源。请先打开「加速设置」添加并启用一个加速前缀。")
                return
            if not is_accelerable(url):
                QMessageBox.information(self, "提示", "该地址不是 GitHub 下载地址，无法使用加速前缀。")
                return
            self._clipboard(build_accel_url(pre, url))
        else:
            self._clipboard(url)

    def open_download(self, use_accel=True):
        it = self.current_item()
        if not it:
            QMessageBox.information(self, "提示", "请先在列表中选择一个仓库。")
            return
        url = it.get("download") or ""
        if not url:
            QMessageBox.information(self, "提示", "该仓库暂时没有可用的下载地址。")
            return
        target = url
        if use_accel:
            pre = self.cfg.active_prefix()
            if pre and is_accelerable(url):
                target = build_accel_url(pre, url)
        ok = False
        try:
            ok = webbrowser.open(target)
        except Exception as e:
            log("webbrowser.open failed: %r" % e)
        if not ok and target != url:
            webbrowser.open(url)
            QMessageBox.information(self, "加速地址打开失败",
                                    "浏览器未能打开加速地址，已改用原始地址打开。\n\n加速地址：\n%s\n\n原始地址：\n%s"
                                    % (target, url))
        elif not ok:
            QMessageBox.warning(self, "打开失败", "未能启动浏览器，请手动复制地址后打开。\n\n%s" % target)

    def open_home(self):
        it = self.current_item()
        if not it:
            QMessageBox.information(self, "提示", "请先在列表中选择一个仓库。")
            return
        url = it.get("html") or ("https://github.com/%s" % it["key"])
        try:
            webbrowser.open(url)
        except Exception:
            QMessageBox.warning(self, "打开失败", "未能启动浏览器。")

    def edit_note(self):
        it = self.current_item()
        if not it:
            QMessageBox.information(self, "提示", "请先在列表中选择一个仓库。")
            return
        text, ok = QInputDialog.getMultiLineText(self, "编辑备注 - %s" % it["name"],
                                                "备注内容（留空表示清除）：", it.get("note") or "")
        if not ok:
            return
        it["note"] = text.strip()
        if it["note"]:
            self.cfg.notes[it["key"]] = it["note"]
        else:
            self.cfg.notes.pop(it["key"], None)
        self.cfg.save()
        for r in range(self.table.rowCount()):
            if self._row_key(r) == it["key"]:
                cell = self.table.item(r, COL_NOTE)
                if cell:
                    self.table.blockSignals(True)
                    cell.setText(it["note"])
                    self.table.blockSignals(False)
                break
        self.set_status("备注已保存：%s" % it["name"])

    def export_csv(self):
        rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            it = self.by_key.get(self._row_key(r))
            if not it:
                continue
            shown, accel = self._accel_pair(it)
            rows.append([it["name"], it["type"], it["desc"], it["note"], it["clone"],
                         it.get("download") or "", shown if accel else ""])
        if not rows:
            QMessageBox.information(self, "提示", "当前没有可导出的数据，请先拉取仓库。")
            return
        default = os.path.join(os.path.expanduser("~"), "Desktop",
                               "github_repos_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M"))
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", default, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["项目名称", "类型", "仓库描述", "我的备注", "拉取地址(git clone)",
                            "下载地址(原始)", "下载地址(加速)"])
                w.writerows(rows)
            self.set_status("已导出 %d 条记录到 %s" % (len(rows), path))
            if QMessageBox.question(self, "导出完成",
                                    "已导出 %d 条记录：\n%s\n\n是否打开所在文件夹？" % (len(rows), path),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                os.startfile(os.path.dirname(path))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ------------------------------------------------------------ 菜单
    def on_table_menu(self, pos):
        it = self.current_item()
        if not it:
            return
        pal = palette(self._dark)
        m = QMenu(self)
        pre = self.cfg.active_prefix()
        accel_ok = bool(pre) and is_accelerable(it.get("download") or "")

        a1 = QAction("复制加速下载地址", self)
        a1.setEnabled(accel_ok)
        a1.triggered.connect(lambda: self.copy_download(True))
        m.addAction(a1)
        a2 = QAction("用加速地址在浏览器打开", self)
        a2.setEnabled(accel_ok)
        a2.triggered.connect(lambda: self.open_download(True))
        m.addAction(a2)
        if not pre:
            a1.setToolTip("尚未启用加速源")
        m.addSeparator()
        a3 = QAction("复制原始下载地址", self)
        a3.triggered.connect(lambda: self.copy_download(False))
        m.addAction(a3)
        a4 = QAction("用原始地址在浏览器打开", self)
        a4.triggered.connect(lambda: self.open_download(False))
        m.addAction(a4)
        m.addSeparator()
        a5 = QAction("复制拉取地址（git clone）", self)
        a5.triggered.connect(self.copy_clone)
        m.addAction(a5)
        a6 = QAction("打开仓库主页", self)
        a6.triggered.connect(self.open_home)
        m.addAction(a6)
        a7 = QAction("编辑我的备注", self)
        a7.triggered.connect(self.edit_note)
        m.addAction(a7)
        m.addSeparator()
        a8 = QAction("加速设置…", self)
        a8.triggered.connect(self.open_accel_dialog)
        m.addAction(a8)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def show_main_menu(self):
        m = QMenu(self)
        a1 = QAction("拉取仓库（F5）", self)
        a1.triggered.connect(self.start_fetch)
        m.addAction(a1)
        a2 = QAction("加速设置…", self)
        a2.triggered.connect(self.open_accel_dialog)
        m.addAction(a2)
        a3 = QAction("导出 CSV…", self)
        a3.triggered.connect(self.export_csv)
        m.addAction(a3)
        m.addSeparator()
        a4 = QAction("打开配置文件所在文件夹", self)
        a4.triggered.connect(lambda: os.startfile(CONFIG_DIR))
        m.addAction(a4)
        a5 = QAction("关于", self)
        a5.triggered.connect(self.show_about)
        m.addAction(a5)
        m.exec(self.titlebar.btn_menu.mapToGlobal(QPoint(0, self.titlebar.btn_menu.height() + 4)))

    def show_about(self):
        QMessageBox.information(
            self, "关于 " + APP_NAME,
            "%s v%s\n\n"
            "个人 GitHub 仓库管家：一键拉取 Star 与自有仓库，生成 git clone 地址与下载地址，"
            "支持备注、搜索筛选、CSV 导出与自定义下载加速。\n\n"
            "界面：Windows 11 毛玻璃（亚克力模糊）+ 圆角无边框\n"
            "配置目录：%s" % (APP_NAME, APP_VERSION, CONFIG_DIR))

    # ---------------------------------------------------------- 快捷键
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F5:
            self.start_fetch()
            return
        if e.key() == Qt.Key_F and (e.modifiers() & Qt.ControlModifier):
            self.ed_search.setFocus()
            self.ed_search.selectAll()
            return
        if e.key() == Qt.Key_C and (e.modifiers() & Qt.ControlModifier):
            it = self.current_item()
            if it:
                self._clipboard(it["clone"])
                return
        super().keyPressEvent(e)


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
def main():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        log("---- app start v%s ----" % APP_VERSION)
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setQuitOnLastWindowClosed(True)
        cfg = Config()
        win = MainWindow(cfg)
        win.show()
        return app.exec()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log("FATAL: %s" % tb)
        try:
            from PySide6.QtWidgets import QApplication as QA
            app = QA.instance() or QA(sys.argv)
            QMessageBox.critical(None, "启动失败", "程序启动时发生错误：\n%s\n\n日志：%s" % (e, LOG_FILE))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

