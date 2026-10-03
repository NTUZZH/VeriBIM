"""Parent-side driver for the per-task code sandbox."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


class SandboxTimeout(RuntimeError):
    """One tool call ran past the per-call timeout."""


class SandboxCrash(RuntimeError):
    """The worker process died while executing a snippet."""


@dataclass
class SnippetResult:
    ok: bool
    stdout: str
    result: str | None
    error: str | None
    commits: int
    total_commits: int
    duration_seconds: float
    #: Attempts the worker's sandbox guard refused during this snippet, each
    #: {"event", "arg", "snippet"}; always empty when the guard is off.
    blocked: list = field(default_factory=list)

    def raw_output(self, capture_stdout: bool = True) -> str:
        """The full text a snippet produced, before any cap is applied."""
        parts: list[str] = []
        if capture_stdout and self.stdout:
            parts.append(self.stdout.rstrip("\n"))
        if self.result is not None:
            parts.append(self.result)
        if self.error:
            parts.append(self.error.rstrip("\n"))
        text = "\n".join(p for p in parts if p)
        return text or "(code executed, no output)"

    def as_tool_output(self, max_chars: int, capture_stdout: bool = True) -> str:
        """Render what the model gets back from the tool.

        A snippet may print, may assign to ``result``, or may raise. All three
        are folded into one string, because that is what the published runs
        must have done: 87% of the cached snippets only ever call ``print``.
        """
        return truncate(self.raw_output(capture_stdout), max_chars)


#: The last statement of an ISO 10303-21 (STEP) file. The IFC library writes
#: the working file in place, so a worker that dies during ``commit()`` leaves
#: a file that stops part-way; the library still opens such a file and
#: silently drops everything after the cut, so opening it is not a test.
STEP_TRAILER = b"END-ISO-10303-21;"


def has_step_trailer(path: Path, tail_bytes: int = 4096) -> bool:
    """True if ``path`` is a non-empty file that ends on the STEP trailer."""
    try:
        with Path(path).open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                return False
            fh.seek(max(0, size - tail_bytes))
            return fh.read().rstrip().endswith(STEP_TRAILER)
    except OSError:
        return False


def truncate(text: str, max_chars: int) -> str:
    """Keep the head and the tail of an over-long tool output."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    dropped = len(text) - head - tail
    return f"{text[:head]}\n... [{dropped} characters omitted] ...\n{text[-tail:]}"


class Sandbox:
    """A worker process holding one open IFC model for the length of a task."""

    def __init__(
        self,
        input_ifc: Path,
        working_ifc: Path,
        log_file: Path,
        python_executable: str | None = None,
        startup_timeout: float = 900.0,
    ) -> None:
        self.input_ifc = Path(input_ifc)
        self.working_ifc = Path(working_ifc)
        self.log_file = Path(log_file)
        self.python_executable = python_executable or sys.executable
        self.startup_timeout = startup_timeout
        self._proc: subprocess.Popen | None = None
        self._reader = None
        self._log_handle = None
        self.copy_seconds = 0.0
        #: Workers started so far; a restart after a crash is the second.
        self.starts = 0
        #: Exit status of the last worker that ``close`` shut down (negative
        #: for a signal, e.g. -11 for SIGSEGV), None before the first close.
        self.last_returncode: int | None = None

    def start(self, copy_input: bool = True) -> None:
        """Start a worker on the working file.

        The first start copies the input model to the working file. A restart
        after a crash passes ``copy_input=False`` to reopen the working file as
        the last ``commit()`` left it. Everything else, the environment and
        with it the sandbox guard, is built the same way on every start.
        """
        self.working_ifc.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if copy_input:
            t0 = time.monotonic()
            shutil.copyfile(self.input_ifc, self.working_ifc)
            self.copy_seconds += time.monotonic() - t0

        read_fd, write_fd = os.pipe()
        env = dict(os.environ)
        env["MODIFC_RESULT_FD"] = str(write_fd)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
        if env.get("VERIBIM_SANDBOX_GUARD") == "1":
            # The executed code needs no credentials: under the guard the
            # worker does not inherit API keys or tokens, which a snippet
            # could otherwise print into its transcript.
            for name in list(env):
                upper = name.upper()
                if any(word in upper for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
                    del env[name]
        # A restart appends, so the first worker's log (and the fault report
        # it may end on) is kept.
        self._log_handle = self.log_file.open("wb" if self.starts == 0 else "ab")
        if self.starts > 0:
            self._log_handle.write(
                f"\n=== sandbox restart {self.starts} "
                f"({'input copy' if copy_input else 'last commit'}) ===\n".encode())
            self._log_handle.flush()
        self.starts += 1
        self._proc = subprocess.Popen(
            [self.python_executable, "-m", "modifc_harness.sandbox_worker", str(self.working_ifc)],
            stdin=subprocess.PIPE,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            pass_fds=(write_fd,),
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        os.close(write_fd)
        self._reader = os.fdopen(read_fd, "r", encoding="utf-8")

        ready = self._read_message(self.startup_timeout)
        if ready.get("kind") != "ready":
            raise SandboxCrash(ready.get("error", "sandbox worker failed to start"))

    def _read_message(self, timeout: float) -> dict:
        assert self._reader is not None and self._proc is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxTimeout(f"no sandbox reply within {timeout:.0f} s")
            ready, _, _ = select.select([self._reader], [], [], min(remaining, 1.0))
            if ready:
                line = self._reader.readline()
                if not line:
                    raise SandboxCrash("sandbox worker closed its result pipe")
                return json.loads(line)
            if self._proc.poll() is not None:
                raise SandboxCrash(
                    f"sandbox worker exited with code {self._proc.returncode}"
                )

    def execute(self, code: str, timeout: float) -> SnippetResult:
        assert self._proc is not None and self._proc.stdin is not None
        t0 = time.monotonic()
        try:
            self._proc.stdin.write(json.dumps({"kind": "run", "code": code}) + "\n")
            self._proc.stdin.flush()
        except OSError as exc:
            # The worker died between the last reply and this one, so the pipe is
            # gone. That is a crashed trajectory, not a crashed run: report it the
            # same way as a worker that dies mid-snippet.
            raise SandboxCrash(f"sandbox worker closed its input pipe: {exc}") from exc
        message = self._read_message(timeout)
        return SnippetResult(
            ok=bool(message.get("ok")),
            stdout=message.get("stdout", ""),
            result=message.get("result"),
            error=message.get("error"),
            commits=int(message.get("commits", 0)),
            total_commits=int(message.get("total_commits", 0)),
            duration_seconds=time.monotonic() - t0,
            blocked=list(message.get("blocked") or []),
        )

    def close(self) -> None:
        """Shut the worker down. Never raises: this runs in a `finally`.

        A worker that has already died leaves a broken pipe behind, and letting
        that surface here would mask whatever ended the trajectory and take the
        whole run with it.
        """
        proc = self._proc
        if proc is not None:
            try:
                if proc.poll() is None and proc.stdin is not None:
                    proc.stdin.write(json.dumps({"kind": "shutdown"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=20)
            except Exception:
                pass
            # Close the pipe explicitly and under guard, so the interpreter never
            # flushes it later, outside anyone's try block.
            try:
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=20)
                except Exception:
                    pass
            self.last_returncode = proc.returncode
            self._proc = None
        for handle in (self._reader, self._log_handle):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass
        self._reader = None
        self._log_handle = None

    def __enter__(self) -> "Sandbox":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
