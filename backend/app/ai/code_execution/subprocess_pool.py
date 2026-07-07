"""One-shot subprocess sandbox for ad-hoc UPLOADED-FILE analysis runs.

WHY this exists (vs. running LLM-generated pandas code in-process, as the
live `code_execution.py` does today):

- **Memory accumulation.** Running arbitrary pandas/numpy code in the same
  long-lived worker process leaks memory across runs (fragmentation, stray
  references, C-extension caches) — there is no way to reclaim it short of
  restarting the whole worker. Running each analysis in a FRESH child
  process means the OS reclaims 100% of its memory the instant the child
  exits, no matter what the generated code did.
- **`forkserver` over `fork`/`spawn`.** `fork` from a multi-threaded async
  server can deadlock (locks held by other threads at fork time never get
  released in the child). `spawn` re-imports the whole interpreter + pandas/
  numpy from scratch every run, which is slow. `forkserver` starts one clean
  helper process early (before threads proliferate) and forks children from
  cheaply from *that* — fast like `fork`, safe like `spawn`. We preload
  pandas/numpy into the forkserver so children inherit them for free.
- **Per-process rlimits are now safe.** `resource.setrlimit` is process-wide;
  applying it in a shared thread pool would cap the whole worker. Applying
  it inside a dedicated one-shot child only caps that child.

This module is only used for UPLOAD-ONLY runs (no live DB/warehouse clients)
— the caller is responsible for gating that. It intentionally does not
import anything from `app.ai.code_execution` to avoid circular imports; it
is stdlib + pandas + numpy only.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import multiprocessing
import os
import tempfile
import time
from dataclasses import dataclass
from math import ceil
from typing import Any


@dataclass
class SandboxResult:
    df_parquet: bytes | None  # result DataFrame serialized as parquet bytes (None on error)
    df_path: str | None  # set instead of df_parquet when the frame is large (>50MB)
    stdout: str  # captured stdout from the run
    error: str | None  # error string on failure, else None
    killed: bool  # True if killed by timeout
    oom: bool  # True if the child was OOM-killed / hit the memory cap
    duration_ms: int
    rebuild_failed: bool = False  # Phase 4: a live client could not be rebuilt → caller falls back in-process
    # Phase 1: SQL executed INSIDE the child (live-client path). The child has no
    # DB/usage_context, so it only *records* the query string + timing + rows +
    # bytes + connection_id; the PARENT merges these into executed_queries/timings
    # and replays quota metering. None on the upload-only path (no live clients).
    captured_queries: list | None = None
    captured_timings: list | None = None


# --- context / concurrency setup (module load time) -----------------------

def _build_context():
    try:
        ctx = multiprocessing.get_context("forkserver")
        try:
            ctx.set_forkserver_preload(["pandas", "numpy"])
        except Exception:
            pass
        return ctx
    except Exception:
        try:
            return multiprocessing.get_context("spawn")
        except Exception:
            return multiprocessing.get_context()


_CTX = _build_context()


def _resolve_max_concurrency() -> int:
    """How many sandbox children may run at once.

    MEMORY MATH (the whole point): each child is rlimit-capped at `mem_mb`
    (see run_local_code / _resolve_mem_cap_mb), so the worst-case memory the
    sandbox pool can hold is `max_concurrency * mem_mb`. Keep that product
    well under the box's cgroup `mem_limit` so the pool can NEVER OOM the host
    — excess requests queue on the semaphore instead of allocating. Tune via
    env `HYBRID_SANDBOX_MAX_CONCURRENCY` (default = cpus-2, floor 2). Example:
    16GB box, mem_mb=1500 → keep concurrency ≤ ~8 (8*1.5GB=12GB < 16GB).
    """
    try:
        raw = os.environ.get("HYBRID_SANDBOX_MAX_CONCURRENCY", "").strip()
        if raw:
            n = int(raw)
            if n >= 1:
                return n
    except Exception:
        pass
    return max(2, (os.cpu_count() or 4) - 2)


# Bounds how many children may run at once (see _resolve_max_concurrency for the
# memory math). BoundedSemaphore → excess concurrent runs QUEUE, never over-commit.
_SEMAPHORE = multiprocessing.BoundedSemaphore(_resolve_max_concurrency())

_LARGE_RESULT_BYTES = 50 * 1024 * 1024  # 50MB


class _FileRef:
    """Tiny shim so generated code can do `excel_files[i].path` / `.filename`."""

    __slots__ = ("path", "filename")

    def __init__(self, path: str, filename: str | None):
        self.path = path
        self.filename = filename


def _invoke_generate_df(fn, ds_clients, excel_files: list) -> Any:
    """Call generate_df(ds_clients, excel_files, ...), binding any
    injectable-by-name params to None.

    `ds_clients` is `{}` for upload-only runs and a dict of rebuilt live clients
    for Phase-4 live runs. A generated function may declare a 3+-arg signature
    (http/loadables/...); bind those to None defensively so it doesn't TypeError
    (those injectables are always absent on the offload path — the caller gates
    them out).
    """
    injectable_names = {"http", "load_step", "load_entity", "federate", "input_df"}
    try:
        import inspect

        params = inspect.signature(fn).parameters
        names = set(params.keys())
    except (TypeError, ValueError):
        names = set()
    kwargs = {name: None for name in injectable_names if name in names}
    return fn(ds_clients, excel_files, **kwargs)


class _ChildQueryCapture:
    """In-child proxy around a rebuilt live client (Phase 1).

    The child has no DB/usage_context, so it cannot meter quota or hit the
    parent's result cache. What it CAN do — and must, or enabling the live
    subprocess path silently loses security + observability — is:
      * enforce the read-only STRING guard on every query (catches write/DDL
        assembled dynamically, exactly like the in-process wrapper's chokepoint);
      * record {sql, query_ms, rows, result_bytes, connection_id} per query so
        the PARENT can merge them into executed_queries/timings and replay quota.
    Everything else delegates to the real client via __getattr__.
    """

    __slots__ = ("_original", "_queries", "_timings", "_enforce_fn", "_bytes_fn")

    def __init__(self, original, queries: list, timings: list, enforce_fn, bytes_fn):
        self._original = original
        self._queries = queries
        self._timings = timings
        self._enforce_fn = enforce_fn      # _enforce_readonly_query or None
        self._bytes_fn = bytes_fn          # estimate_result_size_bytes or None

    def execute_query(self, query, *args, **kwargs):
        if self._enforce_fn is not None and isinstance(query, str):
            self._enforce_fn(query)  # raises on write/DDL — security chokepoint
        if isinstance(query, str):
            self._queries.append(query)
        idx = len(self._timings)
        _start = time.monotonic()
        conn_id = getattr(self._original, "_bow_connection_id", None)
        try:
            result = self._original.execute_query(query, *args, **kwargs)
            _ms = (time.monotonic() - _start) * 1000.0
            rows = len(result) if hasattr(result, "__len__") else None
            rbytes = 0
            if self._bytes_fn is not None:
                try:
                    rbytes = int(self._bytes_fn(result) or 0)
                except Exception:
                    rbytes = 0
            self._timings.append({
                "index": idx,
                "query_ms": round(_ms, 1),
                "rows": rows,
                "result_bytes": rbytes,
                "sql": query[:500] if isinstance(query, str) else None,
                "connection_id": str(conn_id) if conn_id else None,
            })
            return result
        except Exception as e:  # noqa: BLE001
            _ms = (time.monotonic() - _start) * 1000.0
            self._timings.append({
                "index": idx,
                "query_ms": round(_ms, 1),
                "rows": None,
                "sql": query[:500] if isinstance(query, str) else None,
                "connection_id": str(conn_id) if conn_id else None,
                "error": str(e)[:200],
            })
            raise

    def __getattr__(self, name):
        return getattr(self._original, name)


def _rebuild_clients(client_specs: dict, queries: list, timings: list) -> dict:
    """Phase 4: rebuild live SQL clients IN THE CHILD from serializable specs.

    Each spec is {"type": <connector type>, "params": <exact ctor kwargs incl
    decrypted creds>} stamped onto the parent-built client as `_build_spec`
    (see DataSourceService.construct_clients). Rebuilds with no DB via
    resolve_client_class — the child forks from the forkserver which has `app`
    on sys.path, so these imports work. Reapplies DRIVER-LEVEL read-only when
    READONLY_ENFORCE is on, AND (Phase 1) wraps each client in
    `_ChildQueryCapture` so the read-only STRING guard + query capture that the
    in-process path gets are NOT lost on the subprocess path. Raises on any
    failure → the caller reports rebuild_failed and falls back to in-process.
    """
    from app.schemas.data_source_registry import resolve_client_class
    import inspect as _inspect

    try:
        from app.settings.hybrid_flags import flags as _hf
        _readonly = bool(getattr(_hf, "READONLY_ENFORCE", False))
    except Exception:
        _readonly = False

    # Lazy imports at CHILD runtime (never at module load — avoids the circular
    # import the module header warns about). Fail-soft: missing → skip that arm.
    try:
        from app.ai.code_execution.code_execution import _enforce_readonly_query as _enforce_fn
    except Exception:
        _enforce_fn = None
    try:
        from app.ai.code_execution.code_execution import estimate_result_size_bytes as _bytes_fn
    except Exception:
        _bytes_fn = None

    clients: dict = {}
    for key, spec in client_specs.items():
        ctype = (spec or {}).get("type")
        params = (spec or {}).get("params") or {}
        ClientClass = resolve_client_class(ctype)
        try:
            sig = _inspect.signature(ClientClass.__init__)
            accepts_var = any(
                p.kind is _inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            allowed = params if accepts_var else {
                k: v for k, v in params.items() if k in sig.parameters and k != "self"
            }
        except Exception:
            allowed = params
        client = ClientClass(**allowed)
        if _readonly:
            try:
                setter = getattr(client, "set_read_only", None)
                if callable(setter):
                    setter(True)
                elif hasattr(client, "read_only"):
                    client.read_only = True
            except Exception:
                pass
        # Wrap for the string guard + capture. Only enforce the string guard when
        # READONLY_ENFORCE is on (matches the in-process wrapper's gate).
        clients[key] = _ChildQueryCapture(
            client, queries, timings,
            _enforce_fn if _readonly else None,
            _bytes_fn,
        )

    # Wrap in the tolerant resolver so `db_clients['<any sane key>']` resolves
    # (matches the in-process path). Fall back to a plain dict if unavailable.
    try:
        from app.ai.code_execution.code_execution import ClientResolver
        return ClientResolver(clients)
    except Exception:
        return clients


def _apply_rlimits(mem_mb: int, timeout_s: float) -> None:
    """Best-effort per-process resource limits (Linux; best-effort on macOS)."""
    try:
        import resource

        if mem_mb and mem_mb > 0:
            try:
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                new_soft = mem_mb * 1024 * 1024
                if hard != resource.RLIM_INFINITY:
                    new_soft = min(new_soft, hard)
                resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
            except Exception:
                pass
        try:
            cpu_soft, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
            new_cpu = int(ceil(timeout_s)) + 2
            if cpu_hard != resource.RLIM_INFINITY:
                new_cpu = min(new_cpu, cpu_hard)
            resource.setrlimit(resource.RLIMIT_CPU, (new_cpu, cpu_hard))
        except Exception:
            pass
        try:
            fsize_soft, fsize_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
            new_fsize = 512 * 1024 * 1024
            if fsize_hard != resource.RLIM_INFINITY:
                new_fsize = min(new_fsize, fsize_hard)
            resource.setrlimit(resource.RLIMIT_FSIZE, (new_fsize, fsize_hard))
        except Exception:
            pass
    except Exception:
        pass


def _worker(conn, payload: dict) -> None:
    """Runs in the CHILD process. Must never raise out — always sends a result."""
    code = payload["code"]
    file_refs = payload["file_refs"]
    allowed_builtin_names = payload["allowed_builtin_names"]
    mem_mb = payload["mem_mb"]
    spill_dir = payload.get("spill_dir")
    client_specs = payload.get("client_specs")

    _apply_rlimits(mem_mb, payload.get("timeout_s", 60.0))

    stdout_buf = io.StringIO()

    # Phase 1: per-query capture (live path). Populated in-child by
    # _ChildQueryCapture; sent back so the parent can restore executed_queries,
    # timings, and quota metering. Empty on the upload-only path.
    captured_queries: list = []
    captured_timings: list = []

    # Phase 4: rebuild live clients BEFORE the run. A rebuild failure is NOT a
    # code error — signal rebuild_failed so the parent falls back to in-process
    # (never a hard failure).
    db_clients: Any = {}
    if client_specs:
        try:
            db_clients = _rebuild_clients(client_specs, captured_queries, captured_timings)
        except Exception as e:  # noqa: BLE001
            try:
                conn.send({
                    "df_parquet": None, "df_path": None, "stdout": "",
                    "error": f"client rebuild failed: {type(e).__name__}: {e}",
                    "rebuild_failed": True,
                })
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            return

    try:
        import numpy as np
        import pandas as pd

        safe_builtins = {
            name: getattr(builtins, name)
            for name in allowed_builtin_names
            if hasattr(builtins, name)
        }
        excel_files = [
            _FileRef(ref.get("path"), ref.get("filename")) for ref in file_refs
        ]
        namespace: dict = {
            "__builtins__": safe_builtins,
            "__name__": "dash_sandbox_exec",
            "pd": pd,
            "np": np,
            "excel_files": excel_files,
            "db_clients": db_clients,
        }

        with contextlib.redirect_stdout(stdout_buf):
            exec(code, namespace)
            fn = namespace.get("generate_df")
            if not callable(fn):
                raise ValueError("No generate_df function found in code")
            df = _invoke_generate_df(fn, db_clients, excel_files)

            if df is None or not isinstance(df, pd.DataFrame):
                candidates = [
                    v
                    for k, v in namespace.items()
                    if k not in ("pd", "np", "excel_files", "db_clients", "__builtins__", "__name__")
                    and isinstance(v, pd.DataFrame)
                    and not v.empty
                ]
                if len(candidates) == 1:
                    df = candidates[0]
                else:
                    raise ValueError("generate_df did not return a DataFrame")

        buf = io.BytesIO()
        df.to_parquet(buf)
        data = buf.getvalue()

        if len(data) > _LARGE_RESULT_BYTES:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".parquet", dir=spill_dir, delete=False
            )
            tmp.write(data)
            tmp.close()
            conn.send(
                {
                    "df_parquet": None,
                    "df_path": tmp.name,
                    "stdout": stdout_buf.getvalue(),
                    "error": None,
                    "captured_queries": captured_queries,
                    "captured_timings": captured_timings,
                }
            )
        else:
            conn.send(
                {
                    "df_parquet": data,
                    "df_path": None,
                    "stdout": stdout_buf.getvalue(),
                    "error": None,
                    "captured_queries": captured_queries,
                    "captured_timings": captured_timings,
                }
            )
    except Exception as e:  # noqa: BLE001 - must never raise out of the worker
        try:
            conn.send(
                {
                    "df_parquet": None,
                    "df_path": None,
                    "stdout": stdout_buf.getvalue(),
                    "error": f"{type(e).__name__}: {e}",
                    "captured_queries": captured_queries,
                    "captured_timings": captured_timings,
                }
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_local_code(
    *,
    code: str,
    file_refs: list[dict],
    allowed_builtin_names: list[str],
    mem_mb: int,
    timeout_s: float,
    spill_dir: str | None = None,
    client_specs: dict | None = None,
) -> SandboxResult:
    start = time.monotonic()
    acquired = False
    parent_conn = None
    child_conn = None
    p = None
    try:
        _SEMAPHORE.acquire()
        acquired = True

        parent_conn, child_conn = _CTX.Pipe(duplex=False)
        payload = {
            "code": code,
            "file_refs": file_refs,
            "allowed_builtin_names": allowed_builtin_names,
            "mem_mb": mem_mb,
            "spill_dir": spill_dir,
            "timeout_s": timeout_s,
            "client_specs": client_specs,
        }
        p = _CTX.Process(target=_worker, args=(child_conn, payload))
        p.start()
        child_conn.close()
        child_conn = None

        try:
            if parent_conn.poll(timeout_s):
                result = parent_conn.recv()
                p.join(2)
                duration_ms = int((time.monotonic() - start) * 1000)
                error = result.get("error")
                oom = bool(
                    (p.exitcode is not None and p.exitcode == -9)
                    or (error and "MemoryError" in error)
                )
                return SandboxResult(
                    df_parquet=result.get("df_parquet"),
                    df_path=result.get("df_path"),
                    stdout=result.get("stdout", ""),
                    error=error,
                    killed=False,
                    oom=oom,
                    duration_ms=duration_ms,
                    rebuild_failed=bool(result.get("rebuild_failed", False)),
                    captured_queries=result.get("captured_queries"),
                    captured_timings=result.get("captured_timings"),
                )
            else:
                p.terminate()
                p.join(1)
                if p.is_alive():
                    p.kill()
                    p.join(1)
                duration_ms = int((time.monotonic() - start) * 1000)
                return SandboxResult(
                    df_parquet=None,
                    df_path=None,
                    stdout="",
                    error="Run exceeded the time limit and was stopped.",
                    killed=True,
                    oom=False,
                    duration_ms=duration_ms,
                )
        except (EOFError, BrokenPipeError, OSError) as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            oom = bool(p is not None and p.exitcode == -9)
            return SandboxResult(
                df_parquet=None,
                df_path=None,
                stdout="",
                error=f"Sandbox communication failed: {type(e).__name__}: {e}",
                killed=False,
                oom=oom,
                duration_ms=duration_ms,
            )
    except Exception as e:  # noqa: BLE001 - never raise out of run_local_code
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            df_parquet=None,
            df_path=None,
            stdout="",
            error=f"Sandbox error: {type(e).__name__}: {e}",
            killed=False,
            oom=False,
            duration_ms=duration_ms,
        )
    finally:
        try:
            if p is not None and p.is_alive():
                p.terminate()
                p.join(1)
                if p.is_alive():
                    p.kill()
                    p.join(1)
        except Exception:
            pass
        try:
            if child_conn is not None:
                child_conn.close()
        except Exception:
            pass
        try:
            if parent_conn is not None:
                parent_conn.close()
        except Exception:
            pass
        if acquired:
            _SEMAPHORE.release()
