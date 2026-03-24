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


class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Target URL to scrape")
    impersonate: bool = Field(False, description="Use browser stealth fetcher if true")
    selectors: Optional[Dict[str, str]] = Field(None, description="Mapping name -> CSS selector")
    extra: Optional[Dict[str, Any]] = Field(None, description="Extra kwargs forwarded to the fetcher")


class RunPythonRequest(BaseModel):
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, description="Timeout in seconds for execution")


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

        if req.impersonate:
            # Browser-based stealth fetch
            response = StealthyFetcher.fetch(req.url, **fetch_kwargs)
        else:
            # Simple HTTP fetch
            # Use GET by default; forward extra kwargs if supported by Fetcher
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
