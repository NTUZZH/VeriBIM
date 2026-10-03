"""Starting, sizing and stopping the local vLLM server.

The card is shared with other users' processes, so the memory pool is sized
against the memory that is actually free at launch, never against the card's
capacity. One server runs at a time.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HEADROOM_MIB = 3072


@dataclass
class GpuMemory:
    total_mib: int
    used_mib: int
    free_mib: int


def read_gpu_memory(index: int = 0) -> GpuMemory:
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
            f"--id={index}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    total, used, free = (int(x.strip()) for x in out.split(","))
    return GpuMemory(total_mib=total, used_mib=used, free_mib=free)


def gpu_processes() -> list[tuple[int, int]]:
    """Return ``(pid, memory MiB)`` for every process holding GPU memory."""
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        pid, mem = (x.strip() for x in line.split(","))
        rows.append((int(pid), int(mem)))
    return rows


def plan_memory_utilization(headroom_mib: int = DEFAULT_HEADROOM_MIB, index: int = 0) -> tuple[float, GpuMemory]:
    """Choose ``--gpu-memory-utilization`` so the pool fits inside free memory.

    vLLM reads the fraction against the card's *total* memory, so the fraction
    has to be scaled down by whatever another process already holds.
    """
    memory = read_gpu_memory(index)
    budget = memory.free_mib - headroom_mib
    if budget <= 0:
        raise RuntimeError(
            f"only {memory.free_mib} MiB free on GPU {index}; not enough for a server"
        )
    utilization = budget / memory.total_mib
    return round(min(utilization, 0.95), 3), memory


class VllmServer:
    """A vLLM OpenAI-compatible server running in its own conda environment."""

    def __init__(
        self,
        command: list[str],
        log_file: Path,
        conda_env: str = "l2vllm",  # noqa: ARG002 - overridden per model
        conda_root: str | None = None,
    ) -> None:
        self.command = command
        self.log_file = Path(log_file)
        self.conda_env = conda_env
        self.conda_root = conda_root or os.environ.get("CONDA_ROOT", os.path.expanduser("~/miniconda3"))
        self._proc: subprocess.Popen | None = None
        self._log_handle = None

    #: Environment every server launch needs. FlashInfer JIT-builds its sampling
    #: kernels with the CUDA 13.3 nvcc bundled in the serving environment against
    #: that tree's CUDA 13.0 runtime headers, and the CCCL compatibility check
    #: rejects the mismatch, so the engine dies during warm-up. vLLM's own
    #: sampler is used instead.
    ENV_EXPORTS = {"VLLM_USE_FLASHINFER_SAMPLER": "0"}

    def shell_command(self) -> str:
        quoted = " ".join(_shell_quote(part) for part in self.command)
        exports = " ".join(
            f"export {name}={_shell_quote(value)};" for name, value in self.ENV_EXPORTS.items()
        )
        # `conda run` buffers output; sourcing the profile keeps the activate
        # hooks (which set CUDA_HOME for this environment) in effect.
        return (
            f"source {self.conda_root}/etc/profile.d/conda.sh && "
            f"conda activate {self.conda_env} && {exports} exec {quoted}"
        )

    def start(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_file.open("wb")
        self._proc = subprocess.Popen(
            ["bash", "-lc", self.shell_command()],
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def poll(self) -> int | None:
        return self._proc.poll() if self._proc else None

    def stop(self, timeout: float = 180.0) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and proc.poll() is None:
                time.sleep(1.0)
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                time.sleep(10.0)
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=30)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        self._proc = None

    def wait_for_memory_release(self, baseline_free_mib: int, tolerance_mib: int = 512, timeout: float = 300.0) -> GpuMemory:
        """Block until the card is back to roughly its pre-launch free memory."""
        deadline = time.monotonic() + timeout
        memory = read_gpu_memory()
        while time.monotonic() < deadline:
            memory = read_gpu_memory()
            if memory.free_mib >= baseline_free_mib - tolerance_mib:
                return memory
            time.sleep(5.0)
        return memory

    def __enter__(self) -> "VllmServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class ServerSupervisor:
    """Keeps one vLLM server alive for the length of a model's run.

    A server that dies takes the rest of the run with it unless something
    restarts it, so the supervisor watches health, restarts a bounded number of
    times, and records every start and death in an event log the run directory
    keeps.
    """

    def __init__(
        self,
        command: list[str],
        log_dir: Path,
        model_tag: str,
        base_url: str,
        conda_env: str = "l2vllm",
        max_restarts: int = 3,
        ready_timeout: float = 1800.0,
    ) -> None:
        self.command = command
        self.log_dir = Path(log_dir)
        self.model_tag = model_tag
        self.base_url = base_url.rstrip("/")
        self.port = int(self.base_url.rsplit(":", 1)[-1].split("/")[0])
        self.conda_env = conda_env
        self.max_restarts = max_restarts
        self.ready_timeout = ready_timeout
        self.restarts = 0
        self.launches = 0
        self.events: list[dict] = []
        self.baseline_free_mib = read_gpu_memory().free_mib
        self._server: VllmServer | None = None

    # -- event log ---------------------------------------------------------
    def _record(self, kind: str, **fields) -> None:
        event = {"event": kind, "when": datetime.now().isoformat(timespec="seconds"),
                 "model": self.model_tag, **fields}
        self.events.append(event)
        path = self.log_dir / "server_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    # -- lifecycle ---------------------------------------------------------
    def _log_file(self) -> Path:
        return self.log_dir / f"serve_{self.model_tag}_{self.launches:02d}.log"

    def start(self) -> None:
        # A server that has just been stopped can still hold the port for a few
        # seconds. Launching into that gives "Address already in use", which
        # looks like a model problem and is not one.
        wait_for_free_port(self.port)
        memory = read_gpu_memory()
        log_file = self._log_file()
        self._server = VllmServer(self.command, log_file, conda_env=self.conda_env)
        self._server.start()
        self.launches += 1
        self._record("server_start", launch=self.launches, log=str(log_file),
                     gpu_free_mib=memory.free_mib, command=" ".join(self.command))
        self.wait_ready()

    def wait_ready(self) -> None:
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if self.healthy():
                memory = read_gpu_memory()
                self._record("server_ready", launch=self.launches,
                             gpu_used_mib=memory.used_mib, gpu_free_mib=memory.free_mib)
                return
            if self._server is not None and self._server.poll() is not None:
                raise RuntimeError(
                    f"vLLM server exited during start-up; see {self._log_file()}"
                )
            time.sleep(5.0)
        raise RuntimeError(f"vLLM server not ready within {self.ready_timeout:.0f} s")

    def healthy(self) -> bool:
        request = urllib.request.Request(f"{self.base_url}/models")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status == 200
        except Exception:  # noqa: BLE001 - any failure means "not usable"
            return False

    def restart(self, reason: str) -> bool:
        """Restart after a death. Returns False once the restart budget is gone."""
        if self.restarts >= self.max_restarts:
            self._record("restart_refused", reason=reason, restarts=self.restarts)
            return False
        self.restarts += 1
        self._record("server_died", reason=reason, restart=self.restarts)
        self.stop()
        wait_for_free_memory(self.baseline_free_mib)
        self.start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._server = None
        memory = wait_for_free_memory(self.baseline_free_mib)
        self._record("server_stopped", gpu_used_mib=memory.used_mib,
                     gpu_free_mib=memory.free_mib)

    def __enter__(self) -> "ServerSupervisor":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def wait_for_free_port(port: int, host: str = "127.0.0.1", timeout: float = 120.0) -> bool:
    """Block until nothing is listening on the port, or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            if probe.connect_ex((host, port)) != 0:
                return True
        time.sleep(2.0)
    return False


def wait_for_free_memory(baseline_free_mib: int, tolerance_mib: int = 512,
                         timeout: float = 300.0) -> GpuMemory:
    """Block until the card is back to roughly its pre-launch free memory."""
    deadline = time.monotonic() + timeout
    memory = read_gpu_memory()
    while time.monotonic() < deadline:
        memory = read_gpu_memory()
        if memory.free_mib >= baseline_free_mib - tolerance_mib:
            return memory
        time.sleep(5.0)
    return memory


def running_serve_command(model_path: str) -> list[str]:
    """Read the command line of the vLLM server currently serving ``model_path``.

    Recording it in the run configuration makes a run directory self-describing:
    the memory fraction and the parser in force are visible without going back
    to the shell history.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [part for part in raw.decode("utf-8", "replace").split("\0") if part]
        if len(argv) >= 3 and argv[1].endswith("vllm") and argv[2] == "serve" and model_path in argv:
            return argv[1:]
        if len(argv) >= 2 and argv[0].endswith("vllm") and argv[1] == "serve" and model_path in argv:
            return argv
    return []


def _shell_quote(part: str) -> str:
    if part and all(c.isalnum() or c in "-_./:=" for c in part):
        return part
    return "'" + part.replace("'", "'\\''") + "'"
