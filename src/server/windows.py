"""Small Win32 primitives for the Windows launcher; no model/UI dependencies."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path

k32 = c.WinDLL("kernel32", use_last_error=True)


def api(dll, name, restype, *args):
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = args
    return function


close_handle = api(k32, "CloseHandle", w.BOOL, w.HANDLE)
create_file = api(k32, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
                  c.c_void_p, w.DWORD, w.DWORD, w.HANDLE)


class FileLock:
    """Exclusive open, also understood by PowerShell's FileShare.None."""
    def __init__(self, path: Path):
        self.handle = create_file(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if self.handle == c.c_void_p(-1).value:
            error = c.get_last_error()
            if error in (32, 33):
                raise BlockingIOError(str(path))
            raise c.WinError(error)

    def close(self):
        if self.handle is not None:
            close_handle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class BasicLimits(c.Structure):
    _fields_ = [("ProcessTime", c.c_int64), ("JobTime", c.c_int64),
                ("Flags", w.DWORD), ("MinWorkingSet", c.c_size_t),
                ("MaxWorkingSet", c.c_size_t), ("ActiveProcesses", w.DWORD),
                ("Affinity", c.c_size_t), ("Priority", w.DWORD),
                ("Scheduling", w.DWORD)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


class ExtendedLimits(c.Structure):
    _fields_ = [("Basic", BasicLimits), ("Io", IoCounters),
                ("ProcessMemory", c.c_size_t), ("JobMemory", c.c_size_t),
                ("PeakProcessMemory", c.c_size_t), ("PeakJobMemory", c.c_size_t)]


class Job:
    """Closing this handle kills server AND descendants, even if tray crashes."""
    def __init__(self):
        self.handle = api(k32, "CreateJobObjectW", w.HANDLE, c.c_void_p, w.LPCWSTR)(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        info = ExtendedLimits()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api(k32, "SetInformationJobObject", w.BOOL, w.HANDLE, c.c_int,
                   c.c_void_p, w.DWORD)(self.handle, 9, c.byref(info), c.sizeof(info)):
            self.close()
            raise c.WinError(c.get_last_error())

    def assign(self, process):
        if not api(k32, "AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)(
                self.handle, int(process._handle)):
            raise c.WinError(c.get_last_error())

    def close(self):
        if self.handle:
            close_handle(self.handle)
            self.handle = None


def message(text, title="SKAZ", flags=0x10):
    return api(c.WinDLL("user32"), "MessageBoxW", c.c_int, w.HWND, w.LPCWSTR,
               w.LPCWSTR, w.UINT)(None, text, title, flags)
