from __future__ import annotations

import ctypes
import locale
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

APP_NAME = "校园网守护"
APP_DESC = "校园网断线自动重连"
CREATE_NO_WINDOW = 0x08000000
WIN_W, WIN_H = 424, 720
WINDOW_TITLE = APP_NAME
ICON_NAME = "app.ico"
ICON_DIR = "ShouWang"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def res_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_dir())
    return os.path.dirname(os.path.abspath(__file__))

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _stop_child(p) -> None:
    try:
        p.kill()
        p.wait(timeout=5)
    except Exception:
        pass

def run(args, timeout: float = 30, stop_evt=None) -> tuple[int, str]:
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=CREATE_NO_WINDOW)
    except FileNotFoundError as exc:
        return -2, "找不到命令: %s" % exc
    except Exception as exc:
        return -3, "命令失败: %s" % exc
    deadline = time.monotonic() + timeout
    while True:
        try:
            raw, _ = p.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if stop_evt is not None and stop_evt.is_set():
                _stop_child(p)
                return -4, "已被停止"
            if time.monotonic() >= deadline:
                _stop_child(p)
                return -1, "命令超时(%.0fs)" % timeout
    raw = raw or b""
    for enc in ("utf-8", locale.getpreferredencoding(False), "cp936"):
        try:
            return p.returncode, raw.decode(enc).strip()
        except Exception:
            continue
    return p.returncode, raw.decode("utf-8", "replace").strip()

class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

_ENTROPY = b"shouwang-v1"
_UI_FORBIDDEN = 0x01

def _blob(data: bytes):
    buf = ctypes.create_string_buffer(bytes(data), max(len(data), 1))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

def _dpapi(protect: bool, data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    src, _keep1 = _blob(data)
    ent, _keep2 = _blob(_ENTROPY)
    out = _BLOB()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(src), APP_NAME, ctypes.byref(ent),
                                      None, None, _UI_FORBIDDEN, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent),
                                        None, None, _UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI %s 失败：%d" % ("加密" if protect else "解密", ctypes.get_last_error()))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _k32().LocalFree(out.pbData)

def save_secret(path: str, secret: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(_dpapi(True, secret.encode("utf-8")))
    os.replace(tmp, path)

def load_secret(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as fh:
            return _dpapi(False, fh.read()).decode("utf-8")
    except Exception:
        return ""

_SEE_MASK = 0x00000040 | 0x00000100 | 0x00000400

class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

def run_elevated(script: str, timeout: float = 120, stop_evt=None) -> tuple[int, str]:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = _k32()
    sei = _SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = _SEE_MASK
    sei.lpVerb = "runas"
    sei.lpFile = "powershell.exe"
    sei.lpParameters = "-NoProfile -ExecutionPolicy Bypass -Command " + script
    sei.lpDirectory = app_dir()
    sei.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        return -1, "提权被拒绝或失败(错误码 %d)" % ctypes.get_last_error()
    if not sei.hProcess:
        return -2, "提权进程未启动"
    try:
        deadline = time.monotonic() + timeout
        while True:
            r = kernel32.WaitForSingleObject(sei.hProcess, 200)
            if r == 0:
                break
            if r == 0xFFFFFFFF:
                return -4, "等待提权进程失败(错误码 %d)" % ctypes.get_last_error()
            if stop_evt is not None and stop_evt.is_set():
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID",
                                    str(kernel32.GetProcessId(sei.hProcess))],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW, timeout=5)
                except Exception:
                    pass
                return -4, "已被停止"
            if time.monotonic() >= deadline:
                return -3, "提权命令超时"
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        return int(code.value), "已以管理员身份执行"
    finally:
        kernel32.CloseHandle(sei.hProcess)

def _parse_netsh(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            out.setdefault(key.strip(), val.strip())
    return out

def wlan_state(interface: str = "") -> dict:
    rc, out = run(["netsh", "wlan", "show", "interfaces"], timeout=15)
    if rc != 0:
        return {"connected": False, "ssid": "", "state": "无法读取无线网卡", "name": ""}
    d = _parse_netsh(out)
    ssid = d.get("SSID", "")
    state = d.get("State") or d.get("状态", "")
    name = d.get("Name") or d.get("名称", "")
    connected = bool(ssid) and ("connected" in state.lower() or "已连接" in state)
    return {"connected": connected or bool(ssid), "ssid": ssid, "state": state, "name": name}

def wlan_profiles(timeout: float = 15) -> list:
    rc, out = run(["netsh", "wlan", "show", "profiles"], timeout=timeout)
    if rc != 0:
        return []
    names = []
    for line in out.splitlines():
        key, sep, val = line.partition(":")
        if not sep:
            continue
        low = key.strip().lower()
        if "profile" not in low and "配置文件" not in key:
            continue
        name = val.strip()
        if name and name not in names:
            names.append(name)
    return names

def wlan_connect(profile: str, interface: str = "", timeout: float = 25,
                stop_evt=None) -> tuple[int, str]:
    args = ["netsh", "wlan", "connect", "name=%s" % profile]
    if interface:
        args.append("interface=%s" % interface)
    return run(args, timeout=timeout, stop_evt=stop_evt)

def renew_ip(timeout: float = 60, stop_evt=None) -> tuple[int, str]:
    return run(["ipconfig", "/renew"], timeout=timeout, stop_evt=stop_evt)

def restart_adapter(name: str, timeout: float = 120, stop_evt=None) -> tuple[int, str]:
    script = "Restart-NetAdapter -Name '%s' -Confirm:$false" % name.replace("'", "''")
    if is_admin():
        return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   timeout=timeout, stop_evt=stop_evt)
    return run_elevated(script, timeout=timeout, stop_evt=stop_evt)

def startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

def autostart_path() -> str:
    return os.path.join(startup_dir(), APP_NAME + ".vbs")

_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"

def _approved_disabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as key:
            data, _kind = winreg.QueryValueEx(key, APP_NAME + ".vbs")
        return bool(data) and int(data[0]) == 3
    except Exception:
        return False

def autostart_enabled() -> bool:
    return os.path.exists(autostart_path()) and not _approved_disabled()

def pythonw() -> str:
    exe = sys.executable or "python.exe"
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe

def launch_target(hidden: bool) -> tuple:
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, []
    else:
        exe, args = pythonw(), [os.path.join(app_dir(), "app.py")]
    return exe, (args + ["--hidden"] if hidden else args)

def set_autostart(enable: bool) -> tuple[bool, str]:
    path = autostart_path()
    if not enable:
        try:
            if os.path.exists(path):
                os.remove(path)
            return True, "已关闭开机自启"
        except Exception as exc:
            return False, "关闭开机自启失败：%s" % exc
    try:
        os.makedirs(startup_dir(), exist_ok=True)
        exe, args = launch_target(True)
        cmd_line = " ".join('"%s"' % x for x in [exe] + args)
        body = ("' 由 %s 生成：开机静默启动，不弹黑框\n"
                "Set sh = CreateObject(\"WScript.Shell\")\n"
                "sh.CurrentDirectory = \"%s\"\n"
                "sh.Run \"%s\", 0, False\n"
                % (APP_NAME, app_dir(), cmd_line.replace('"', '""')))
        with open(path, "w", encoding="utf-16") as fh:
            fh.write(body)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_NAME + ".vbs")
        except Exception:
            pass
        return True, "已开启开机自启"
    except Exception as exc:
        return False, "开启开机自启失败：%s" % exc

_MUTEX = None

def acquire_single_instance(name: str = "CampusGuardSingleInstance") -> bool:
    global _MUTEX
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        h = kernel32.CreateMutexW(None, False, "Local\\" + name)
        if not h:
            return True
        _MUTEX = h
        return kernel32.GetLastError() != 183
    except Exception:
        return True

def icon_path() -> str:
    return os.path.join(res_dir(), ICON_NAME)

def desktop_dir() -> str:
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")

def shortcut_path() -> str:
    return os.path.join(desktop_dir(), APP_NAME + ".lnk")

def installed_icon() -> str:
    src = icon_path()
    if not os.path.exists(src):
        return ""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    dest = os.path.join(base, ICON_DIR, ICON_NAME)
    try:
        if (not os.path.exists(dest)
                or os.path.getsize(dest) != os.path.getsize(src)
                or os.path.getmtime(dest) < os.path.getmtime(src)):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
        return dest if os.path.exists(dest) else src
    except Exception:
        return src

def create_desktop_shortcut() -> tuple[bool, str]:
    lnk = shortcut_path()
    ico = installed_icon() or pythonw()

    def q(text: str) -> str:
        return text.replace("'", "''")

    exe, args = launch_target(False)
    script = ("$ws = New-Object -ComObject WScript.Shell;"
              "$s = $ws.CreateShortcut('%s');"
              "$s.TargetPath = '%s';"
              "$s.Arguments = '%s';"
              "$s.WorkingDirectory = '%s';"
              "$s.Description = '%s';"
              "$s.IconLocation = '%s,0';"
              "$s.Save();"
              "if (Test-Path '%s') { 'ok' } else { 'missing' }"
              % (q(lnk), q(exe), q(" ".join('"%s"' % a for a in args)),
                 q(app_dir()), q(APP_DESC), q(ico), q(lnk)))
    rc, out = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                  timeout=60)
    if rc == 0 and "ok" in out:
        return True, "已在桌面创建快捷方式"
    return False, "创建快捷方式失败：%s" % (out.strip()[:200] or ("rc=%s" % rc))

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_BROWSERS = ("msedge.exe", "chrome.exe")
_U32_READY = False
_PANEL_LOCK = threading.Lock()
_PANEL_HWNDS: set = set()

def _u32():
    global _U32_READY
    user32 = ctypes.windll.user32
    if _U32_READY:
        return user32
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    _U32_READY = True
    return user32

_K32 = None

def _k32():
    global _K32
    if _K32 is not None:
        return _K32
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.LocalFree.argtypes = [ctypes.c_void_p]
    k.LocalFree.restype = ctypes.c_void_p
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.GetProcessId.argtypes = [wintypes.HANDLE]
    k.GetProcessId.restype = wintypes.DWORD
    _K32 = k
    return k

def _exe_name(pid: int) -> str:
    name = ""
    try:
        kernel32 = _k32()
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value).lower()
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        name = ""
    return name

def _windows(title: str = WINDOW_TITLE) -> list:
    user32 = _u32()
    found = []

    def _cb(hwnd, _lp):
        try:
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value == title:
                    cls = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls, 256)
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    name = _exe_name(pid.value)
                    if cls.value == "Chrome_WidgetWin_1" and name in _BROWSERS:
                        found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return found

def _track_panel(hwnds) -> None:
    with _PANEL_LOCK:
        _PANEL_HWNDS.update(int(h) for h in hwnds)

def _mine(title: str = WINDOW_TITLE) -> set:
    live = set(_windows(title))
    with _PANEL_LOCK:
        _PANEL_HWNDS.intersection_update(live)
        return set(_PANEL_HWNDS)

def _default_pos(w: int = WIN_W, h: int = WIN_H) -> tuple[int, int]:
    try:
        user32 = _u32()
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return max(0, sw - w - 24), max(0, (sh - h) // 2 - 20)
    except Exception:
        return 60, 60

def fit_window(title: str = WINDOW_TITLE, w: int = WIN_W, h: int = WIN_H, base=None) -> bool:
    base = set() if base is None else {int(h) for h in base}
    x, y = _default_pos(w, h)
    user32 = _u32()
    for i in range(300):
        fresh = [hw for hw in _windows(title) if hw not in base]
        if fresh:
            _track_panel(fresh)
            for hw in fresh:
                user32.SetWindowPos(hw, None, x, y, w, h, 0x0004 | 0x0010)
            for _ in range(6):
                time.sleep(0.2)
                for hw in _mine(title):
                    user32.SetWindowPos(hw, None, x, y, w, h, 0x0004 | 0x0010)
            return True
        time.sleep(0.01 if i < 200 else 0.1)
    return False

def close_app_windows(title: str = WINDOW_TITLE) -> int:
    targets = _mine(title)
    with _PANEL_LOCK:
        _PANEL_HWNDS.difference_update(targets)
    for hwnd in targets:
        _u32().PostMessageW(hwnd, 0x0010, 0, 0)
    return len(targets)

def window_count(title: str = WINDOW_TITLE) -> int:
    return len(_mine(title))

def activate_existing(title: str = WINDOW_TITLE) -> bool:
    user32 = _u32()
    for hwnd in _mine(title):
        try:
            if not user32.IsWindowVisible(hwnd):
                continue
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:
            continue
    return False

def open_edge_app(url: str) -> bool:
    if activate_existing():
        return True
    try:
        base = set(_windows())
    except Exception:
        base = set()
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                os.path.join(os.environ.get("LOCALAPPDATA", ""),
                             r"Microsoft\Edge\Application\msedge.exe")):
        if not os.path.exists(exe):
            continue
        try:
            subprocess.Popen([exe, "--app=" + url,
                              "--window-size=%d,%d" % (WIN_W, WIN_H),
                              "--window-position=%d,%d" % _default_pos(),
                              "--no-first-run", "--no-default-browser-check",
                              "--disable-features=Translate,msEdgeSplitScreen"],
                             creationflags=CREATE_NO_WINDOW)
            threading.Thread(target=fit_window, kwargs={"base": base}).start()
            return True
        except Exception:
            continue
    try:
        os.startfile(url)
        return True
    except Exception:
        return False
