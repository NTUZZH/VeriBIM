"""Subprocess that executes model-generated code against one IFC model.

One worker is started per task and lives for the whole task, so an object the
model creates in one tool call is still there in the next one. The worker reads
newline-delimited JSON requests on stdin and writes newline-delimited JSON
replies to the file descriptor named by ``MODIFC_RESULT_FD``. Real stdout and
stderr are left to the parent's log file, so anything the executed code prints
is captured in memory rather than corrupting the protocol.

Usage: ``python -m modifc_harness.sandbox_worker <working_ifc_path>``

With ``VERIBIM_SANDBOX_GUARD=1`` in the environment the worker confines the
executed code before the first snippet runs (see ``install_guard``): file
access is limited to the working directory and the Python installation, and
starting processes, opening sockets and the introspection that could reach
the guard are refused. Every refused attempt is returned with the snippet's
reply under ``blocked``. ``VERIBIM_SANDBOX_LANDLOCK=1`` adds a kernel
file-system ruleset (Linux Landlock) under the same guard, which also covers
file access made from compiled code.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout


def build_namespace(working_path: str) -> tuple[dict, dict]:
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.guid
    import ifcopenshell.util
    import ifcopenshell.util.element

    ifc = ifcopenshell.open(working_path)
    state = {"commits": 0}

    def commit() -> None:
        """Persist the in-memory model to the working file."""
        ifc.write(working_path)
        state["commits"] += 1

    namespace = {
        "__name__": "__main__",
        "__builtins__": __builtins__,
        "ifc": ifc,
        "ifcopenshell": ifcopenshell,
        "api": ifcopenshell.api,
        "util": ifcopenshell.util,
        "element_util": ifcopenshell.util.element,
        "guid": ifcopenshell.guid,
        "commit": commit,
        "result": None,
    }

    def _safe_exit(code=None):
        """Stand-in for the site helpers ``exit`` and ``quit``, which close
        standard input before raising SystemExit and would end the worker's
        request loop; the snippet still stops with a SystemExit the model sees."""
        raise SystemExit(code)

    namespace["exit"] = _safe_exit
    namespace["quit"] = _safe_exit
    # The geometry helper library: measured placement of fillings and
    # box elements, copies and arrays, one relationship per call. Bound as
    # ``geom`` so a trajectory reads ``geom.add_filling(...)``; the module has
    # no project imports and no state. Absent only when the module is missing,
    # which keeps an older checkout of the harness runnable.
    # The helper library is bound as ``geom`` unless VERIBIM_NO_GEOM is set, an
    # opt-in switch for the ablation arm that measures the trained model without
    # the library; headline runs never set it.
    import os
    if not os.environ.get("VERIBIM_NO_GEOM"):
        try:
            from modifc_harness import veribim_geom
            namespace["geom"] = veribim_geom
        except ImportError:
            pass
    return namespace, state


# ------------------------------------------------------------ sandbox guard
# The guard is switched on by VERIBIM_SANDBOX_GUARD=1. It is installed after
# the model is opened and before the first snippet runs, and it cannot be
# removed afterwards: an audit hook stays for the life of the process. It
# allows what an edit needs (the working directory, read and write; the Python
# installation and the harness package, read only; this process's own /proc
# entries and a few harmless system files, read only) and refuses everything
# else: other file access, directory listing and globbing, processes, sockets,
# and the introspection a snippet could use to reach the hook.
# The hook is built so that nothing a snippet can reach changes its decision.
# Its policy and every function it calls are bound as keyword defaults of a
# function that nothing else references, the values are immutable, and the
# body reads no global or enclosing name, so neither patching a module nor
# editing the locals of a hook frame found in a traceback alters it. It never
# calls code the snippet could have defined or patched.

GUARD_ENV = "VERIBIM_SANDBOX_GUARD"
LANDLOCK_ENV = "VERIBIM_SANDBOX_LANDLOCK"

#: Audit events raised by the wrappers around the IFC library's own file I/O,
#: which is compiled code that the "open" event never sees.
IFC_READ_EVENT = "modifc.sandbox.ifc_read"
IFC_WRITE_EVENT = "modifc.sandbox.ifc_write"

_PROCESS_EVENTS = frozenset({
    "subprocess.Popen", "_posixsubprocess.fork_exec", "os.system", "os.exec",
    "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "os.startfile",
    "pty.spawn", "os.killpg",
})
_NETWORK_EVENTS = frozenset({
    "urllib.Request", "http.client.connect", "http.client.send",
    "ftplib.connect", "smtplib.connect", "poplib.connect", "imaplib.open",
    "nntplib.connect", "telnetlib.Telnet.open", "webbrowser.open",
})
_REFUSED_EVENTS = frozenset({
    # Introspection that can find the hook or rewrite memory.
    "gc.get_objects", "gc.get_referrers", "gc.get_referents",
    "sys._current_frames", "sys._current_exceptions", "sys.remote_exec",
    "remote_debugger_script",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle",
    "ctypes.call_function", "ctypes.cdata", "ctypes.PyObj_FromPtr",
    "ctypes.string_at", "ctypes.wstring_at",
    # Changing the directory relative paths resolve against, links that
    # could point outside, and namespace changes.
    "os.chdir", "os.chroot", "os.link", "os.symlink", "os.mknod",
    "os.mkfifo", "os.unshare", "os.setns",
})
#: Low-level path events: (read paths, write paths, dir_fd position or -1).
_PATH_EVENTS = {
    "os.listdir": ((0,), (), -1), "os.scandir": ((0,), (), -1),
    "os.getxattr": ((0,), (), -1), "os.listxattr": ((0,), (), -1),
    "os.remove": ((), (0,), 1), "os.rmdir": ((), (0,), 1),
    "os.mkdir": ((), (0,), 2), "os.chmod": ((), (0,), 2),
    "os.lchmod": ((), (0,), -1), "os.chown": ((), (0,), 3),
    "os.utime": ((), (0,), 3), "os.truncate": ((), (0,), -1),
    "os.chflags": ((), (0,), -1), "os.lchflags": ((), (0,), -1),
    "os.setxattr": ((), (0,), -1), "os.removexattr": ((), (0,), -1),
    "tempfile.mkstemp": ((), (0,), -1), "tempfile.mkdtemp": ((), (0,), -1),
    IFC_READ_EVENT: ((0,), (), -1), IFC_WRITE_EVENT: ((), (0,), -1),
}
#: High-level events whose arguments are the caller's own objects. They are
#: checked when a path can be read from them without running caller code;
#: the low-level events they lead to are checked in every case.
_HIGH_EVENTS = {
    "os.walk": ((0,), ()), "os.fwalk": ((0,), ()),
    "pathlib.Path.glob": ((0,), ()), "pathlib.Path.rglob": ((0,), ()),
    "shutil.copyfile": ((0,), (1,)), "shutil.copymode": ((0,), (1,)),
    "shutil.copystat": ((0,), (1,)), "shutil.copytree": ((0,), (1,)),
    "shutil.move": ((0,), (1,)), "shutil.rmtree": ((), (0,)),
    "shutil.chown": ((), (0,)), "shutil.make_archive": ((2,), (0,)),
    "shutil.unpack_archive": ((0,), (1,)),
}


def _flatten_events(table: dict) -> tuple:
    """A dict of event specs as a tuple of (event, spec) pairs, which cannot
    be changed once built."""
    return tuple(sorted(table.items()))


def _guard_roots(working_path: str) -> tuple:
    """Directories the guard allows: (read-write, read-only, listable)."""
    import site

    real = os.path.realpath
    workdir = os.path.dirname(real(working_path))
    # Temporary files go to a directory inside the working directory, so the
    # kernel layer can also remove it at shutdown; /tmp itself is not
    # allowed, since other processes keep their own files there.
    private_tmp = os.path.join(workdir, ".sandbox_tmp")
    os.makedirs(private_tmp, exist_ok=True)
    read_only = {sys.prefix, sys.base_prefix, sys.exec_prefix,
                 f"/proc/{os.getpid()}", "/dev/urandom", "/dev/random",
                 "/dev/zero", "/etc/localtime", "/etc/timezone",
                 "/usr/share/zoneinfo", "/etc/os-release",
                 "/usr/lib/os-release"}
    try:
        read_only.update(site.getsitepackages())
        if site.ENABLE_USER_SITE and site.getusersitepackages() in sys.path:
            read_only.add(site.getusersitepackages())
    except AttributeError:
        pass
    for name in ("ifcopenshell", "numpy", "modifc_harness"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None):
            read_only.add(os.path.dirname(module.__file__))
    read_write = (workdir, "/dev/null")
    read_only = sorted({real(p) for p in read_only if p} - set(read_write))
    # The import system lists the directories on sys.path when it looks for
    # a module it has not seen; listing those directories themselves (not
    # their contents' contents) stays allowed so an import does not count as
    # an attempt.
    listable = frozenset(real(p or os.getcwd()) for p in sys.path)
    return read_write, tuple(read_only), listable, private_tmp


def _make_hook(read_write, read_only, listable, records, index):
    """Build the audit hook. See the note at the top of this section."""
    import pathlib
    import posix
    import stat as stat_module

    def with_slash(paths):
        return tuple(p.rstrip("/") + "/" for p in paths)

    def hook(event, args, *,
             _rw=with_slash(read_write), _ro=with_slash(read_only),
             _listable=listable, _cwd=posix.getcwd(), _pid=os.getpid(),
             _records=records, _index=index,
             _process=_PROCESS_EVENTS, _network=_NETWORK_EVENTS,
             _refused=_REFUSED_EVENTS,
             _path_events=frozenset(_PATH_EVENTS),
             _path_specs=_flatten_events(_PATH_EVENTS),
             _high_events=frozenset(_HIGH_EVENTS),
             _high_specs=_flatten_events(_HIGH_EVENTS),
             _write_flags=(os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
                           | os.O_APPEND),
             _lstat=posix.lstat, _stat=posix.stat, _readlink=posix.readlink,
             _islnk=stat_module.S_ISLNK, _isdir=stat_module.S_ISDIR,
             _type=type, _str=str, _bytes=bytes, _int=int,
             _issubclass=issubclass, _type_name=type.__dict__["__name__"].__get__,
             _raw_paths=pathlib.PurePath.__dict__["_raw_paths"].__get__,
             _path_types=(pathlib.PurePath, pathlib.PurePosixPath, pathlib.Path,
                          pathlib.PosixPath),
             _list=list, _len=len, _PermissionError=PermissionError,
             _OSError=OSError, _ValueError=ValueError):
        # ---- events refused whatever their arguments
        if event in _refused:
            _records.append((event, "", _index[0]))
            raise _PermissionError(f"sandbox: {event} is not permitted")
        if event in _process or (event == "os.kill" and not (
                args and _type(args[0]) is _int and args[0] == _pid)):
            _records.append((event, "", _index[0]))
            raise _PermissionError(
                "sandbox: starting or signalling processes is not permitted")
        if event in _network or event.startswith("socket."):
            _records.append((event, "", _index[0]))
            raise _PermissionError("sandbox: network access is not permitted")

        # ---- collect the paths this event touches: (argument, kind, dir fd)
        # kind is "r" (read), "w" (write), "l" (list) or "d" (open, which
        # may also be a directory).
        todo = _list()
        strict = True
        if event == "open":
            if args and _type(args[0]) is not _int:
                mode = args[1] if _len(args) > 1 else None
                flags = args[2] if _len(args) > 2 else 0
                write = _type(flags) is _int and (flags & _write_flags) != 0
                if _type(mode) is _str:
                    for c in "wax+":
                        if c in mode:
                            write = True
                todo.append((args[0], "w" if write else "d", -1))
        elif event in _path_events:
            for name, spec in _path_specs:
                if name == event:
                    reads, writes, fd_pos = spec
                    dir_fd = -1
                    if 0 <= fd_pos < _len(args) and _type(args[fd_pos]) is _int:
                        dir_fd = args[fd_pos]
                    for pos in reads:
                        if pos < _len(args):
                            kind = "l" if event in ("os.listdir", "os.scandir") else "r"
                            todo.append((args[pos], kind, dir_fd))
                    for pos in writes:
                        if pos < _len(args):
                            todo.append((args[pos], "w", dir_fd))
                    break
        elif event == "os.rename":
            src_fd = args[2] if _len(args) > 2 and _type(args[2]) is _int else -1
            dst_fd = args[3] if _len(args) > 3 and _type(args[3]) is _int else -1
            todo.append((args[0], "w", src_fd))
            todo.append((args[1], "w", dst_fd))
        elif event == "sqlite3.connect":
            db = args[0] if args else None
            if _type(db) is _str and db.startswith("file:"):
                db = db[5:].split("?")[0]
            if not (_type(db) is _str and (db == "" or db == ":memory:")):
                todo.append((db, "w", -1))
        elif event == "glob.glob" or event == "glob.glob/2":
            pattern = args[0] if args else None
            root_dir = args[2] if _len(args) > 2 else None
            dir_fd = args[3] if _len(args) > 3 and _type(args[3]) is _int else -1
            if _type(pattern) is _bytes:
                pattern = pattern.decode("utf-8", "surrogateescape")
            if _type(root_dir) is _bytes:
                root_dir = root_dir.decode("utf-8", "surrogateescape")
            if _type(pattern) is _str:
                cut = _len(pattern)
                for c in "*?[":
                    at = pattern.find(c)
                    if 0 <= at < cut:
                        cut = at
                static = pattern[:cut]
                slash = static.rfind("/")
                if slash > 0:
                    static = static[:slash]
                elif slash == 0:
                    static = "/"
                else:
                    static = "."
                if not static.startswith("/") and _type(root_dir) is _str:
                    static = root_dir + "/" + static
                todo.append((static, "l", dir_fd))
        elif event in _high_events:
            strict = False
            for name, spec in _high_specs:
                if name == event:
                    reads, writes = spec
                    for pos in reads:
                        if pos < _len(args):
                            kind = "l" if name.startswith(("os.", "pathlib.")) else "r"
                            todo.append((args[pos], kind, -1))
                    for pos in writes:
                        if pos < _len(args):
                            todo.append((args[pos], "w", -1))
                    break
        else:
            return

        # ---- check each path against the allowed roots
        for raw, kind, dir_fd in todo:
            t = _type(raw)
            if t is _str:
                text = raw
            elif t is _bytes:
                text = raw.decode("utf-8", "surrogateescape")
            elif t is _int:
                continue                      # an already-open descriptor
            elif raw is None and kind == "l":
                text = "."
            elif _issubclass(t, _str):
                text = "".join((raw,))
            elif _issubclass(t, _bytes):
                text = b"".join((raw,)).decode("utf-8", "surrogateescape")
            elif (t is _path_types[0] or t is _path_types[1]
                  or t is _path_types[2] or t is _path_types[3]):
                parts = _raw_paths(raw)
                text = ""
                for part in parts:
                    if _type(part) is not _str:
                        text = None
                        break
                    if part.startswith("/"):
                        text = part
                    elif text:
                        text = text + "/" + part
                    else:
                        text = part
                if text is None:
                    continue
                if text == "":
                    text = "."
            elif strict:
                _records.append((event, "<" + _type_name(t) + ">", _index[0]))
                raise _PermissionError(
                    "sandbox: a path of type " + _type_name(t)
                    + " is not accepted; pass the path as a str")
            else:
                continue
            shown = text if _len(text) <= 300 else text[:300] + "..."

            # Resolve to an absolute path with every symlink followed.
            if text.startswith("/"):
                full = text
            else:
                base = _cwd
                if dir_fd >= 0:
                    try:
                        base = _readlink("/proc/self/fd/%d" % dir_fd)
                    except (_OSError, _ValueError):
                        base = "/nonexistent-descriptor"
                full = base + "/" + text
            pending = full.split("/")
            pending.reverse()
            done = _list()
            hops = 0
            while pending:
                part = pending.pop()
                if part == "" or part == ".":
                    continue
                if part == "..":
                    if done:
                        done.pop()
                    continue
                candidate = "/" + "/".join(done) + ("/" if done else "") + part
                try:
                    link = _islnk(_lstat(candidate).st_mode)
                except (_OSError, _ValueError):
                    link = False
                if not link:
                    done.append(part)
                    continue
                hops += 1
                if hops > 40:
                    done = ["\x00loop"]
                    break
                try:
                    target = _readlink(candidate)
                except (_OSError, _ValueError):
                    done.append(part)
                    continue
                if target.startswith("/"):
                    done = _list()
                pieces = target.split("/")
                pieces.reverse()
                pending.extend(pieces)
            resolved = "/" + "/".join(done)
            probe = resolved + "/"

            if kind == "w":
                allowed = probe.startswith(_rw)
            elif kind == "l":
                allowed = (probe.startswith(_rw) or probe.startswith(_ro)
                           or resolved in _listable)
            else:
                allowed = probe.startswith(_rw) or probe.startswith(_ro)
                if allowed and kind == "d" and not probe.startswith(_rw):
                    # A directory descriptor outside the working directory
                    # would let a later open resolve against it.
                    try:
                        allowed = not _isdir(_stat(resolved).st_mode)
                    except (_OSError, _ValueError):
                        pass
            if not allowed:
                _records.append((event, shown, _index[0]))
                raise _PermissionError(
                    "sandbox: access outside the working directory is not "
                    "permitted: " + shown)

    return hook


def _wrap_ifc_io() -> None:
    """Route the IFC library's compiled file I/O through audit events.

    ``ifcopenshell.open`` and ``file.write`` read and write in compiled code,
    which the interpreter's "open" event never sees. Every entry point of the
    compiled module that takes a file name is replaced by a wrapper that first
    raises an audit event carrying each string argument, which the hook
    checks like any other path. The Python-level ``ifcopenshell.open`` is
    wrapped as well, so a refused path fails before the library tests whether
    it exists.
    """
    import functools

    import ifcopenshell
    from ifcopenshell import _ifcopenshell_wrapper as compiled

    audit = sys.audit
    fspath = os.fspath

    def wrap(original, event, audit=audit, is_text=isinstance,
             text=(str, bytes)):
        def guarded(*args, **kwargs):
            for value in args:
                if is_text(value, text):
                    audit(event, value)
            for value in kwargs.values():
                if is_text(value, text):
                    audit(event, value)
            return original(*args, **kwargs)
        guarded.__name__ = getattr(original, "__name__", "guarded")
        guarded.__doc__ = getattr(original, "__doc__", None)
        return guarded

    reads = ("open", "parse_ifcxml", "file_initialize", "new_file",
             "new_InstanceStreamer")
    for name in dir(compiled):
        if name in reads:
            setattr(compiled, name, wrap(getattr(compiled, name), IFC_READ_EVENT))
        elif name == "file_write" or (name.startswith("new_")
                                      and name.endswith("Serializer")):
            setattr(compiled, name, wrap(getattr(compiled, name), IFC_WRITE_EVENT))

    library_open = ifcopenshell.open

    @functools.wraps(library_open)
    def open_checked(path, *args, **kwargs):
        audit(IFC_READ_EVENT, fspath(path))
        return library_open(path, *args, **kwargs)

    ifcopenshell.open = open_checked


def _apply_landlock(read_write, read_only) -> int:
    """Restrict this process's file access in the kernel (Linux Landlock).

    The ruleset allows the same roots as the audit hook, plus the system
    library directories a late library load reads, denies every TCP bind and
    connect, and on kernels that support it scopes signals and abstract
    sockets to the process. It covers compiled code and any child process,
    which the audit hook cannot. Returns the Landlock ABI version, and raises
    if the kernel refuses, so a run that asked for it never runs without it.
    """
    import ctypes
    import stat

    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    create_ruleset, add_rule, restrict_self = 444, 445, 446

    long = ctypes.c_long
    abi = syscall(long(create_ruleset), None, long(0), long(1))
    if abi < 1:
        raise OSError(ctypes.get_errno(), "Landlock is not available")
    fs_all = (1 << 13) - 1
    if abi >= 2:
        fs_all |= 1 << 13              # refer
    if abi >= 3:
        fs_all |= 1 << 14              # truncate
    if abi >= 5:
        fs_all |= 1 << 15              # ioctl on devices
    file_only = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14) | (1 << 15)
    read = (1 << 2) | (1 << 3)         # read file, read directory

    class RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64),
                    ("handled_access_net", ctypes.c_uint64),
                    ("scoped", ctypes.c_uint64)]

    # The kernel struct is packed to 12 bytes; this one has the same first
    # 12 bytes plus tail padding, which the kernel does not read.
    class PathBeneathAttr(ctypes.Structure):
        _fields_ = [("allowed_access", ctypes.c_uint64),
                    ("parent_fd", ctypes.c_int32)]

    attr = RulesetAttr(fs_all, (1 << 0) | (1 << 1) if abi >= 4 else 0,
                       (1 << 0) | (1 << 1) if abi >= 6 else 0)
    size = 8 if abi < 4 else (16 if abi < 6 else 24)
    ruleset = syscall(long(create_ruleset), ctypes.byref(attr), long(size),
                      long(0))
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset failed")
    system = ("/usr/lib", "/lib", "/lib64", "/etc/ld.so.cache",
              "/sys/devices/system/cpu")
    try:
        rules = [(p, fs_all) for p in read_write]
        rules += [(p, read) for p in tuple(read_only) + system]
        for path, access in rules:
            try:
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                if not stat.S_ISDIR(os.fstat(fd).st_mode):
                    access &= file_only
                rule = PathBeneathAttr(access & fs_all, fd)
                if syscall(long(add_rule), long(ruleset), long(1),
                           ctypes.byref(rule), long(0)) != 0:
                    raise OSError(ctypes.get_errno(),
                                  f"landlock_add_rule failed for {path}")
            finally:
                os.close(fd)
        if libc.prctl(long(38), long(1), long(0), long(0), long(0)) != 0:
            # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), "prctl(NO_NEW_PRIVS) failed")
        if syscall(long(restrict_self), long(ruleset), long(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self failed")
    finally:
        os.close(ruleset)
    return abi


class Guard:
    """The worker's handle on an installed guard: the log of refused
    attempts and the index of the snippet running. The hook itself is not
    reachable from here."""

    def __init__(self, records: list, index: list, private_tmp: str,
                 landlock_abi: int) -> None:
        self._records = records
        self._index = index
        self._snippets = 0
        self.private_tmp = private_tmp
        self.landlock_abi = landlock_abi

    def begin_snippet(self) -> None:
        self._index[0] = self._snippets
        self._snippets += 1

    def drain(self) -> list:
        """Refused attempts since the last call, as JSON-ready records."""
        taken = self._records[:]
        del self._records[:len(taken)]
        return [{"event": event, "arg": arg, "snippet": index}
                for event, arg, index in taken]

    def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.private_tmp, ignore_errors=True)


def install_guard(working_path: str, landlock: bool = False) -> Guard:
    """Confine this process before the first snippet runs. Irreversible."""
    import tempfile

    read_write, read_only, listable, private_tmp = _guard_roots(working_path)
    # Temporary files go to a private directory inside the allowed roots, and
    # no bytecode cache is written into the installation, which would
    # otherwise be refused and counted.
    tempfile.tempdir = private_tmp
    os.environ["TMPDIR"] = private_tmp
    sys.dont_write_bytecode = True
    _wrap_ifc_io()
    landlock_abi = _apply_landlock(read_write, read_only) if landlock else 0
    records: list = []
    index = [0]
    sys.addaudithook(_make_hook(read_write, read_only, listable, records, index))
    return Guard(records, index, private_tmp, landlock_abi)


def run_snippet(namespace: dict, state: dict, code: str) -> dict:
    """Execute one snippet and collect everything the model should see back."""
    before = state["commits"]
    guard = state.get("guard")
    if guard is not None:
        guard.begin_snippet()
    namespace["result"] = None
    buf = io.StringIO()
    error = None
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            exec(compile(code, "<execute_ifc_code>", "exec"), namespace)
    except BaseException:  # noqa: BLE001 - the text goes back to the model
        error = traceback.format_exc()
    reply = {
        "ok": error is None,
        "stdout": buf.getvalue(),
        "result": None if namespace.get("result") is None else str(namespace["result"]),
        "error": error,
        "commits": state["commits"] - before,
        "total_commits": state["commits"],
    }
    if guard is not None:
        reply["blocked"] = guard.drain()
    return reply


def main() -> int:
    working_path = sys.argv[1]
    result_fd = int(os.environ["MODIFC_RESULT_FD"])
    out = os.fdopen(result_fd, "w", encoding="utf-8", buffering=1)
    # Requests are read from a private handle on descriptor 0 and sys.stdin is
    # pointed at /dev/null, so executed code that closes or reads standard
    # input (exit(), sys.stdin.close(), input()) can neither end nor consume the
    # request stream.
    requests = os.fdopen(os.dup(0), "r", encoding="utf-8")
    sys.stdin = open(os.devnull, "r", encoding="utf-8")

    try:
        namespace, state = build_namespace(working_path)
        if os.environ.get(GUARD_ENV) == "1":
            state["guard"] = install_guard(
                working_path, landlock=os.environ.get(LANDLOCK_ENV) == "1")
    except BaseException:  # noqa: BLE001
        out.write(json.dumps({"kind": "startup_error", "error": traceback.format_exc()}) + "\n")
        out.flush()
        return 1
    out.write(json.dumps({"kind": "ready"}) + "\n")
    out.flush()

    for line in requests:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        if request.get("kind") == "shutdown":
            break
        reply = run_snippet(namespace, state, request["code"])
        reply["kind"] = "result"
        out.write(json.dumps(reply) + "\n")
        out.flush()
    if state.get("guard") is not None:
        state["guard"].cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
