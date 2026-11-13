"""Caches for parsed IFC models and for the meshes of individual entities.

Parsing a realistic scene costs seconds and hundreds of megabytes, and one
scored task opens three models (input, ground truth, prediction) of which the
first two recur across every task on the same scene and across every rollout of
the same task.  Both caches are therefore process-local and bounded:

* ``ModelCache`` keys a parsed ``ifcopenshell.file`` by (absolute path, mtime,
  size).  It is a least-recently-used cache with a capacity in entries; the
  default of three keeps input, ground truth and prediction of one task
  resident, and a larger capacity keeps whole scenes resident across tasks.
* ``MeshCache`` keys a triangulated mesh by (model key, entity GUID).  Its
  capacity is counted in vertices so that a few large meshes cannot grow the
  process without bound.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import ifcopenshell


def model_key(path: str | os.PathLike) -> tuple[str, int, int]:
    path = os.path.abspath(os.fspath(path))
    st = os.stat(path)
    return (path, int(st.st_mtime_ns), int(st.st_size))


class ModelCache:
    """Least-recently-used cache of parsed IFC models."""

    def __init__(self, capacity: int = 4) -> None:
        self.capacity = max(1, capacity)
        self._store: OrderedDict[tuple[str, int, int], Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, path: str | os.PathLike):
        key = model_key(path)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self.hits += 1
                return self._store[key]
        model = ifcopenshell.open(os.fspath(path))
        with self._lock:
            self.misses += 1
            self._store[key] = model
            self._store.move_to_end(key)
            while len(self._store) > self.capacity:
                self._store.popitem(last=False)
        return model

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "resident": len(self._store)}


@dataclass
class Mesh:
    verts: Any  # (n, 3) float64
    faces: Any  # (m, 3) int32
    area: float


class MeshCache:
    """Least-recently-used cache of per-entity triangle meshes."""

    def __init__(self, capacity_vertices: int = 4_000_000) -> None:
        self.capacity_vertices = capacity_vertices
        self._store: OrderedDict[tuple[Any, str], Mesh | None] = OrderedDict()
        self._vertices = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[Any, str]):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self.hits += 1
                return self._store[key], True
            self.misses += 1
            return None, False

    def put(self, key: tuple[Any, str], mesh: Mesh | None) -> None:
        with self._lock:
            self._store[key] = mesh
            self._store.move_to_end(key)
            if mesh is not None:
                self._vertices += len(mesh.verts)
            while self._vertices > self.capacity_vertices and len(self._store) > 1:
                _, evicted = self._store.popitem(last=False)
                if evicted is not None:
                    self._vertices -= len(evicted.verts)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._vertices = 0

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "resident": len(self._store),
                "vertices": self._vertices}


# Process-wide default caches.  Worker processes each get their own.
MODELS = ModelCache(capacity=6)
MESHES = MeshCache()
