"""Native notification-area icon. All lifecycle work is queued off the UI thread."""
import ctypes as c
from ctypes import wintypes as w

from .windows import api

user = c.WinDLL("user32", use_last_error=True)
shell = c.WinDLL("shell32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
CALLBACK, UPDATE, EXIT = 0x8001, 0x8002, 0x8003


class WindowClass(c.Structure):
    _fields_ = [("style", w.UINT), ("proc", WNDPROC), ("clsExtra", c.c_int),
                ("wndExtra", c.c_int), ("instance", w.HINSTANCE), ("icon", w.HICON),
                ("cursor", w.HANDLE), ("background", w.HANDLE),
                ("menu", w.LPCWSTR), ("name", w.LPCWSTR)]


class NotifyIcon(c.Structure):
    _fields_ = [("size", w.DWORD), ("hwnd", w.HWND), ("id", w.UINT),
                ("flags", w.UINT), ("callback", w.UINT), ("icon", w.HICON),
                ("tip", w.WCHAR * 128), ("state", w.DWORD), ("stateMask", w.DWORD),
                ("info", w.WCHAR * 256), ("timeout", w.UINT),
                ("title", w.WCHAR * 64), ("infoFlags", w.DWORD),
                ("guid", c.c_byte * 16), ("balloonIcon", w.HICON)]


post = api(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
notify = api(shell, "Shell_NotifyIconW", w.BOOL, w.DWORD, c.POINTER(NotifyIcon))
default_proc = api(user, "DefWindowProcW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class TrayIcon:
    def __init__(self, path, snapshot, command):
        self.snapshot, self.command = snapshot, command
        self.hwnd = None
        self.notice = None
        self.taskbar_created = api(user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)("TaskbarCreated")
        self.callback = WNDPROC(self._window_proc)
        self.instance = api(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)(None)
        self.icon = api(user, "LoadImageW", w.HANDLE, w.HINSTANCE, w.LPCWSTR,
                        w.UINT, c.c_int, c.c_int, w.UINT)(None, str(path), 1, 32, 32, 0x10)
        if not self.icon:
            raise c.WinError(c.get_last_error())

    def refresh(self, notice=None):
        if notice:
            self.notice = notice
        if self.hwnd:
            post(self.hwnd, UPDATE, 0, 0)

    def stop(self):
        if self.hwnd:
            post(self.hwnd, EXIT, 0, 0)

    def _data(self):
        data = NotifyIcon()
        data.size, data.hwnd, data.id = c.sizeof(data), self.hwnd, 1
        data.flags, data.callback, data.icon = 1 | 2 | 4, CALLBACK, self.icon
        data.tip = "SKAZ — " + self.snapshot()["state"]
        return data

    def _menu(self):
        state = self.snapshot()
        menu = api(user, "CreatePopupMenu", w.HMENU)()
        append = api(user, "AppendMenuW", w.BOOL, w.HMENU, w.UINT, c.c_size_t, w.LPCWSTR)
        idle = not state["busy"]
        items = [
            (state["state"], None, False, False),
            ("Запустить сервер", "start", idle and state["state"] != "Работает", False),
            ("Остановить сервер", "stop", idle and state["state"] == "Работает", False),
            ("Перезапустить сервер", "restart", idle, False),
            ("Связать с браузером", "setup", idle, False),
            ("Открыть журнал", "log", True, False),
            ("Проверить обновления", "update", idle, False),
            ("Запускать при входе в Windows", "autostart", idle, state["autostart"]),
            ("Выйти из SKAZ", "quit", True, False),
        ]
        try:
            for index, (title, _, enabled, checked) in enumerate(items, 1):
                append(menu, (0 if enabled else 1) | (8 if checked else 0), index, title)
            point = w.POINT()
            api(user, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))(c.byref(point))
            api(user, "SetForegroundWindow", w.BOOL, w.HWND)(self.hwnd)
            chosen = api(user, "TrackPopupMenu", w.UINT, w.HMENU, w.UINT, c.c_int,
                         c.c_int, c.c_int, w.HWND, c.c_void_p)(
                             menu, 0x100 | 2, point.x, point.y, 0, self.hwnd, None)
            if chosen and items[chosen - 1][1]:
                self.command(items[chosen - 1][1])
            post(self.hwnd, 0, 0, 0)
        finally:
            api(user, "DestroyMenu", w.BOOL, w.HMENU)(menu)

    def _window_proc(self, hwnd, msg, wp, lp):
        if msg == CALLBACK:
            if lp == 0x205:  # right-button up
                self._menu()
            elif lp == 0x203:  # double click
                self.command("setup")
            return 0
        if msg == self.taskbar_created:
            notify(0, c.byref(self._data()))
            return 0
        if msg == UPDATE:
            data = self._data()
            if self.notice:
                data.flags |= 0x10
                data.title, data.info, data.infoFlags = "SKAZ", self.notice[:255], 3
                self.notice = None
            notify(1, c.byref(data))
            return 0
        if msg == EXIT:
            api(user, "DestroyWindow", w.BOOL, w.HWND)(hwnd)
            return 0
        if msg == 0x11:  # WM_QUERYENDSESSION
            return 1
        if msg == 0x16 and wp:  # WM_ENDSESSION
            self.command("quit")
            return 0
        if msg == 2:
            notify(2, c.byref(self._data()))
            api(user, "PostQuitMessage", None, c.c_int)(0)
            return 0
        return default_proc(hwnd, msg, wp, lp)

    def run(self, ready):
        cls = WindowClass()
        cls.proc, cls.instance, cls.name = self.callback, self.instance, "SkazTrayWindow"
        if not api(user, "RegisterClassW", w.ATOM, c.POINTER(WindowClass))(c.byref(cls)):
            raise c.WinError(c.get_last_error())
        self.hwnd = api(user, "CreateWindowExW", w.HWND, w.DWORD, w.LPCWSTR, w.LPCWSTR,
                        w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND,
                        w.HMENU, w.HINSTANCE, c.c_void_p)(
                            0, cls.name, "SKAZ", 0, 0, 0, 0, 0, None, None, self.instance, None)
        if not self.hwnd or not notify(0, c.byref(self._data())):
            raise c.WinError(c.get_last_error())
        ready()
        msg = w.MSG()
        get = api(user, "GetMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
        try:
            while get(c.byref(msg), None, 0, 0) > 0:
                api(user, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))(c.byref(msg))
                api(user, "DispatchMessageW", LRESULT, c.POINTER(w.MSG))(c.byref(msg))
        finally:
            notify(2, c.byref(self._data()))
            api(user, "DestroyIcon", w.BOOL, w.HICON)(self.icon)
