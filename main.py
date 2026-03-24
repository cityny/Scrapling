from typing import Dict, Optional, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scrapling.fetchers.stealth_chrome import StealthyFetcher
from scrapling.fetchers.requests import Fetcher
import asyncio
import tempfile
import sys
import os
import uuid
import time
from typing import Union


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Target URL to scrape")
    impersonate: bool = Field(False, description="Use browser stealth fetcher if true")
    selectors: Optional[Dict[str, str]] = Field(None, description="Mapping name -> CSS selector")
    extra: Optional[Dict[str, Any]] = Field(None, description="Extra kwargs forwarded to the fetcher")


class RunPythonRequest(BaseModel):
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, description="Timeout in seconds for execution")


# Tasks store for long-running processes (polling model)
# task structure: {
#   task_id: {
#       "status": "running"|"completed"|"failed",
#       "exit_code": int|None,
#       "stdout_path": str,
#       "stderr_path": str,
#       "created_at": float,
#       "finished_at": float|None
#   }
# }
tasks: Dict[str, Dict[str, Union[str, int, float, None]]] = {}


class RunAsyncRequest(BaseModel):
    code: str = Field(..., description="Python code to execute")
    env: Optional[Dict[str, str]] = Field(None, description="Environment vars to inject into the child process")
    timeout: int = Field(300, description="Timeout in seconds for execution")


app = FastAPI(title="Scrapling Microservice")

# Allow n8n or any origin to call this service
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/scrape")
def scrape(req: ScrapeRequest, request: Request):
    try:
        fetch_kwargs = req.extra or {}

        # Keep original page_action value to report its incoming type
        pa_raw = fetch_kwargs.get("page_action")

        # Extract page_action to avoid leaking it into HTTP fetchers that don't accept it
        page_action_value = fetch_kwargs.pop("page_action", None)

        # If the caller passed `page_action` as a string (via JSON), convert it
        # into a callable that will be executed inside Playwright's page context.
        if isinstance(page_action_value, str):
            code_str = page_action_value
            def _page_action_from_string(page):
                try:
                    return page.evaluate(f"(async () => {{ {code_str} }})()")
                except Exception as e:
                    print(f"DEBUG: Error ejecutando page_action string: {e}")
                    return None

            page_action_value = _page_action_from_string

        # DEBUG: report incoming request and page_action types (raw vs converted)
        try:
            print(f"DEBUG API: Recibida petición para {req.url}. page_action incoming type: {type(pa_raw)}; converted type: {type(page_action_value)}")
        except Exception:
            pass

        if req.impersonate:
            # Browser-based stealth fetch
            if page_action_value is not None:
                fetch_kwargs["page_action"] = page_action_value
            response = StealthyFetcher.fetch(req.url, **fetch_kwargs)
        else:
            # Simple HTTP fetch
            # Use GET by default; forward extra kwargs if supported by Fetcher
            # Ensure page_action is not forwarded to HTTP Fetcher
            response = Fetcher.get(req.url, **fetch_kwargs)

        result: Dict[str, Any] = {"url": req.url, "success": True, "data": {}}

        if req.selectors:
            for name, selector in req.selectors.items():
                try:
                    nodes = response.css(selector)
                    if not nodes:
                        result["data"][name] = []
                        continue

                    items = []
                    for node in nodes:
                        items.append({
                            "text": str(node.get() or ""),
                            "html": str(node.html_content or ""),
                        })

                    result["data"][name] = items
                except Exception as e:  # per-selector errors should not break the whole response
                    result["data"][name] = {"error": str(e)}
        else:
            # If no selectors provided, return raw body and metadata
            result["data"] = {
                "body": response.body if hasattr(response, "body") else None,
                "status_code": getattr(response, "status", None),
            }

        # Add some meta info
        result["meta"] = {"headers": getattr(response, "headers", {}), "status": getattr(response, "status", None)}
        # Include page_action result if present (may be None)
        try:
            page_action_result_val = getattr(response, "meta", {}).get("page_action_result")
        except Exception:
            page_action_result_val = None
        result["data"]["page_action_result"] = page_action_result_val

        # DEBUG: log response.meta so we can trace page_action propagation in API calls
        try:
            print(f"DEBUG: response.meta = {getattr(response, 'meta', {})}")
        except Exception:
            pass

        return result

    except Exception as e:
        # Always return 200 with success: false to avoid stopping n8n flows
        return {"success": False, "error": str(e), "url": getattr(req, "url", None)}


@app.post("/run-python")
async def run_python(req: RunPythonRequest):
    max_chars = 50000
    tmp_path = None
    try:
        # Create temporary file with the provided code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write(req.code)
            tmp.flush()
            tmp_path = tmp.name

        # Spawn subprocess asynchronously
        proc = await asyncio.create_subprocess_exec(
            sys.executable, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=req.timeout)
            exit_code = proc.returncode
            success = True
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout_bytes, stderr_bytes = b"", f"Timeout de {req.timeout} segundos excedido".encode()
            exit_code = -1
            success = False

        stdout = stdout_bytes.decode('utf-8', errors='replace') if isinstance(stdout_bytes, (bytes, bytearray)) else str(stdout_bytes)
        stderr = stderr_bytes.decode('utf-8', errors='replace') if isinstance(stderr_bytes, (bytes, bytearray)) else str(stderr_bytes)

        if len(stdout) > max_chars:
            stdout = stdout[:max_chars] + "\n...[truncated]"
        if len(stderr) > max_chars:
            stderr = stderr[:max_chars] + "\n...[truncated]"

        return {"success": success, "stdout": stdout, "stderr": stderr, "exit_code": exit_code}

    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def _run_background_task(task_id: str, code: str, env: Optional[Dict[str, str]], timeout: int):
    """Background coroutine that runs the provided code in a subprocess,
    streaming stdout/stderr to files and updating the tasks dict."""
    task = tasks.get(task_id)
    if not task:
        return

    stdout_path = task["stdout_path"]
    stderr_path = task["stderr_path"]

    # Prepare environment for child process
    child_env = dict(os.environ)
    if env:
        # ensure keys/values are strings
        for k, v in env.items():
            child_env[str(k)] = str(v)
    async def _drain_stream_to_file(stream: asyncio.StreamReader, path: str):
        try:
            with open(path, 'ab') as f:
                while True:
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    f.write(chunk)
                    f.flush()
        except Exception:
            pass

    tmp_file = None
    out_task = None
    err_task = None
    try:
        # write code to a temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write(code)
            tmp.flush()
            tmp_file = tmp.name

        # Force unbuffered python in child env and/or use -u
        child_env["PYTHONUNBUFFERED"] = "1"

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", tmp_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
        )

        # Start tasks to drain stdout/stderr into files while process runs
        if proc.stdout:
            out_task = asyncio.create_task(_drain_stream_to_file(proc.stdout, stdout_path))
        if proc.stderr:
            err_task = asyncio.create_task(_drain_stream_to_file(proc.stderr, stderr_path))

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 else "failed"
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            exit_code = -1
            status = "failed"

        # Ensure any remaining output is drained
        if out_task:
            await out_task
        if err_task:
            await err_task

        task.update({"status": status, "exit_code": exit_code, "finished_at": time.time()})

    except Exception as e:
        task.update({"status": "failed", "exit_code": -1, "finished_at": time.time()})
        try:
            with open(stderr_path, 'ab') as ef:
                ef.write(str(e).encode('utf-8', errors='replace'))
        except Exception:
            pass
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass


@app.post("/run-async")
async def run_async(req: RunAsyncRequest):
    # Create task entry
    task_id = str(uuid.uuid4())
    created_at = time.time()

    stdout_tmp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
    stderr_tmp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
    stdout_tmp.close()
    stderr_tmp.close()

    tasks[task_id] = {
        "status": "running",
        "exit_code": None,
        "stdout_path": stdout_tmp.name,
        "stderr_path": stderr_tmp.name,
        "created_at": created_at,
        "finished_at": None,
    }

    # Launch background task (non-blocking)
    asyncio.create_task(_run_background_task(task_id, req.code, req.env, req.timeout))

    return {"task_id": task_id}


@app.get("/check/{task_id}")
async def check_task(task_id: str):
    info = tasks.get(task_id)
    if not info:
        return {"status": "not_found", "exit_code": None, "stdout": "", "stderr": ""}

    # Read accumulated stdout/stderr up to a cap
    cap = 50000
    stdout = ""
    stderr = ""
    try:
        if os.path.exists(info["stdout_path"]):
            with open(info["stdout_path"], 'rb') as f:
                data = f.read()
                stdout = data.decode('utf-8', errors='replace')
                if len(stdout) > cap:
                    stdout = stdout[-cap:]
        if os.path.exists(info["stderr_path"]):
            with open(info["stderr_path"], 'rb') as f:
                data = f.read()
                stderr = data.decode('utf-8', errors='replace')
                if len(stderr) > cap:
                    stderr = stderr[-cap:]
    except Exception as e:
        stderr = f"Error reading logs: {e}"

    return {
        "status": info.get("status"),
        "exit_code": info.get("exit_code"),
        "stdout": stdout,
        "stderr": stderr,
    }


async def _cleanup_loop():
    """Periodically remove tasks older than 1 hour from memory and delete their tmp files."""
    while True:
        now = time.time()
        expire_after = 3600
        to_delete = []
        for tid, info in list(tasks.items()):
            finished = info.get("finished_at")
            if finished and (now - finished) > expire_after:
                to_delete.append(tid)

        for tid in to_delete:
            info = tasks.pop(tid, None)
            if info:
                try:
                    if info.get("stdout_path") and os.path.exists(info.get("stdout_path")):
                        os.remove(info.get("stdout_path"))
                except Exception:
                    pass
                try:
                    if info.get("stderr_path") and os.path.exists(info.get("stderr_path")):
                        os.remove(info.get("stderr_path"))
                except Exception:
                    pass

        await asyncio.sleep(60)


@app.on_event("startup")
async def _start_cleanup():
    asyncio.create_task(_cleanup_loop())
