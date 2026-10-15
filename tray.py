from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

import winutil as wu

_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_kernel32 = ctypes.windll.kernel32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_TRAYICON = 0x0400 + 20

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01
IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x0010, 0x0040
MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x0002, 0x0080, 0x0100
IDI_APPLICATION = 32512

MENU_OPEN, MENU_PAUSE, MENU_CHECK, MENU_QUIT = 1, 2, 3, 9
TIMER_ID, TRAY_UID = 1, 1
POLL_MS = 2000

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON),
    ]

class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def _setup() -> None:
    u, s, k = _user32, _shell32, _kernel32
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.PostQuitMessage.argtypes = [ctypes.c_int]
    u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    u.SetTimer.restype = ctypes.c_size_t
    u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    u.LoadIconW.restype = wintypes.HANDLE
    u.DestroyIcon.argtypes = [wintypes.HICON]
    u.DestroyIcon.restype = wintypes.BOOL
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    u.TrackPopupMenu.restype = wintypes.UINT
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    u.AttachThreadInput.restype = wintypes.BOOL
    k.GetCurrentThreadId.restype = wintypes.DWORD
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.RegisterWindowMessageW.restype = wintypes.UINT
    s.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    s.Shell_NotifyIconW.restype = wintypes.BOOL
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetModuleHandleW.restype = wintypes.HMODULE

_setup()

def _load_icon() -> int:
    for path in (wu.installed_icon(), wu.icon_path()):
        if path and os.path.exists(path):
            h = _user32.LoadImageW(None, path, IMAGE_ICON, 0, 0,
                                   LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return int(h)
    return int(_user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION)) or 0)

class Tray:

    def __init__(self, on_open, on_toggle_pause, on_check, on_quit,
                 paused=None, status=None, logger=None):
        self._open = on_open
        self._toggle = on_toggle_pause
        self._check = on_check
        self._quit = on_quit
        self._paused = paused or (lambda: False)
        self._status = status or (lambda: "")
        self._log = logger
        self._hwnd = 0
        self._icon = 0
        self._proc = None
        self._thread = None
        self._ballooned = False
        self._seen_panel = False
        self._in_menu = False
        self._taskbar_msg = int(_user32.RegisterWindowMessageW("TaskbarCreated"))
        self._cls = "ShouWangTrayClass%d" % os.getpid()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def remove_icon(self) -> None:
        self._del_icon()

    def _say(self, level: str, msg: str) -> None:
        if self._log:
            try:
                getattr(self._log, level, self._log.info)(msg)
            except Exception:
                pass

    def _call(self, fn) -> None:
        try:
            fn()
        except Exception as exc:
            self._say("warning", "托盘操作失败：%s" % exc)

    def _tip(self) -> str:
        try:
            text = str(self._status() or "").strip()
        except Exception:
            text = ""
        if self._paused():
            text = "已暂停自动监控"
        tail = (" · " + text) if text else ""
        return (wu.APP_NAME + tail)[:127]

    def _fill(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = TRAY_UID
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._icon
        nid.szTip = self._tip()
        return nid

    def _add_icon(self) -> bool:
        if not self._icon:
            self._icon = _load_icon()
        ok = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._fill(
            NIF_MESSAGE | NIF_ICON | NIF_TIP))))
        if not ok:
            for _ in range(10):
                threading.Event().wait(0.5)
                if _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._fill(
                        NIF_MESSAGE | NIF_ICON | NIF_TIP))):
                    ok = True
                    break
        if ok:
            self._say("info", "托盘图标已就绪（左键打开面板，右键出菜单）")
        else:
            self._say("warning", "托盘图标添加失败，关闭窗口后请重新启动程序")
        return ok

    def _del_icon(self) -> None:
        if self._hwnd:
            try:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._fill(0)))
            except Exception:
                pass

    def _balloon(self, title: str, text: str) -> None:
        nid = self._fill(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        try:
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def _tick(self) -> None:
        if self._in_menu:
            return
        try:
            alive = wu.window_count() > 0
        except Exception:
            alive = True
        if alive:
            self._seen_panel = True
            self._ballooned = False
        elif self._seen_panel and not self._ballooned:
            self._ballooned = True
            self._balloon("%s 还在运行" % wu.APP_NAME,
                          "界面已收起到托盘，网络仍在守护；点托盘图标就能重新打开。")
        try:
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._fill(
                NIF_MESSAGE | NIF_ICON | NIF_TIP)))
        except Exception:
            pass

    def _menu(self) -> None:
        u = _user32
        menu = u.CreatePopupMenu()
        if not menu:
            return
        cmd = 0
        try:
            paused = bool(self._paused())
            u.AppendMenuW(menu, MF_STRING, MENU_OPEN, "打开面板")
            u.AppendMenuW(menu, MF_STRING, MENU_PAUSE,
                          "恢复自动监控" if paused else "暂停自动监控")
            u.AppendMenuW(menu, MF_STRING, MENU_CHECK, "立即检测")
            u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            u.AppendMenuW(menu, MF_STRING, MENU_QUIT, "退出程序")
            pt = POINT()
            u.GetCursorPos(ctypes.byref(pt))
            fg = u.GetForegroundWindow()
            tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
            tid_me = _kernel32.GetCurrentThreadId()
            attached = False
            if tid_fg and tid_fg != tid_me:
                attached = bool(u.AttachThreadInput(tid_me, tid_fg, True))
            self._in_menu = True
            try:
                u.SetForegroundWindow(self._hwnd)
                cmd = int(u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                           pt.x, pt.y, 0, self._hwnd, None))
            finally:
                self._in_menu = False
                if attached:
                    u.AttachThreadInput(tid_me, tid_fg, False)
            u.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            u.DestroyMenu(menu)
        if cmd == MENU_OPEN:
            self._call(self._open)
        elif cmd == MENU_PAUSE:
            self._call(self._toggle)
            self._tick()
        elif cmd == MENU_CHECK:
            self._call(self._check)
        elif cmd == MENU_QUIT:
            self._call(self._quit)

    def _on_message(self, hwnd, msg, wparam, lparam):
        u = _user32
        if msg == WM_TRAYICON:
            if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._call(self._open)
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_TIMER:
            self._tick()
            return 0
        if self._taskbar_msg and msg == self._taskbar_msg:
            if self._icon:
                u.DestroyIcon(self._icon)
            self._icon = 0
            self._add_icon()
            return 0
        if msg in (WM_CLOSE, WM_DESTROY):
            u.KillTimer(hwnd, TIMER_ID)
            self._del_icon()
            if msg == WM_CLOSE:
                u.DestroyWindow(hwnd)
            else:
                u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        u, k = _user32, _kernel32
        hinst = k.GetModuleHandleW(None)
        self._proc = WNDPROC(self._on_message)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = self._cls
        u.RegisterClassW(ctypes.byref(wc))
        self._hwnd = int(u.CreateWindowExW(0, self._cls, "ShouWangTrayWindow", 0, 0, 0, 0, 0,
                                           None, None, hinst, None) or 0)
        if not self._hwnd:
            self._say("warning", "托盘窗口创建失败，关闭面板后请重新启动程序")
            return
        self._add_icon()
        u.SetTimer(self._hwnd, TIMER_ID, POLL_MS, None)
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        self._del_icon()
