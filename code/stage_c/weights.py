"""Keep the sampling server's adapter in step with the policy being trained.

Stage C samples from an external vLLM server rather than from the trainer's own
model. Nothing in that arrangement makes the server's adapter follow the
optimizer, so without the synchronisation here every rollout after the first
step would come from the Stage B adapter and the run would not be on-policy at
all. vLLM exposes runtime LoRA loading (`/v1/load_lora_adapter`), gated by
VLLM_ALLOW_RUNTIME_LORA_UPDATING, so the trainer writes the current policy to
disk and asks the server to pick it up.

Each push registers a step-suffixed name and unloads the previous one, which
keeps a single adapter resident and avoids any question of whether the server
caches by name. The retired directory is removed in the same call.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import urllib.error
import urllib.request

import json as _json

from stage_a.chat_format import assert_saved_template, save_adapter


def _post(base_url: str, route: str, payload: dict, timeout: float) -> tuple[int, str]:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    request = urllib.request.Request(
        f"{url}{route}", data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")[:400]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]


@dataclass
class AdapterSync:
    """Publish the trainable adapter to the sampling server."""

    base_url: str
    serve_root: Path
    stem: str = "policy"
    adapter_name: str = "policy"
    timeout: float = 300.0
    keep: int = 1
    current: str | None = None
    history: list[dict] = field(default_factory=list)

    def push(self, model, tokenizer, step: int) -> dict:
        """Write the policy at `step` and swap the server onto it."""
        started = time.time()
        name = f"{self.stem}_s{step:04d}"
        directory = self.serve_root / name
        record: dict = {"step": step, "name": name, "path": str(directory)}
        try:
            template = save_adapter(model, tokenizer, directory,
                                    adapter_name=self.adapter_name)
            record["template_md5"] = template["md5"]
            record["template_matches"] = template["matches"]
            # A restarted trainer meets a server that still holds this step's
            # name from the previous attempt; evict it first, ignoring "not
            # loaded" refusals.
            _post(self.base_url, "/v1/unload_lora_adapter",
                  {"lora_name": name}, self.timeout)
            status, body = _post(self.base_url, "/v1/load_lora_adapter",
                                 {"lora_name": name, "lora_path": str(directory)},
                                 self.timeout)
            record["load_status"] = status
            if status >= 300:
                record["load_body"] = body
                raise RuntimeError(
                    f"the server refused the step-{step} adapter ({status}): {body}")
            previous, self.current = self.current, name
            if previous is not None:
                unloaded, _ = _post(self.base_url, "/v1/unload_lora_adapter",
                                    {"lora_name": previous}, self.timeout)
                record["unload_status"] = unloaded
                stale = self.serve_root / previous
                if self.keep <= 1 and stale.is_dir():
                    shutil.rmtree(stale, ignore_errors=True)
        finally:
            record["seconds"] = round(time.time() - started, 2)
            self.history.append(record)
        return record

    def verify(self) -> dict:
        """Confirm the live adapter directory still carries the canonical template."""
        if self.current is None:
            return {"current": None}
        checked = assert_saved_template(self.serve_root / self.current)
        if not checked["matches"]:
            raise AssertionError(
                f"the served adapter {self.current} lost the canonical template")
        return {"current": self.current, **checked}
