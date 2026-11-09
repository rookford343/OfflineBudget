"""Single-origin web serving: security headers and the built SPA.

The API lives under /api; everything else is the React app's static files,
with index.html as the fallback for client-side routes.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# cdn.plaid.com / *.plaid.com are allowed only for Plaid Link, which
# frontend/src/lib/plaidLink.ts loads as a script plus an iframe and which
# talks to Plaid's API.
# style-src allows 'unsafe-inline' because recharts and React set inline styles.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://cdn.plaid.com; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self' https://*.plaid.com; manifest-src 'self'; worker-src 'self'; "
        "frame-src https://cdn.plaid.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


# The service worker, its policy script and the manifest must be revalidated on
# every load, or a phone could keep running an old worker indefinitely.
REVALIDATE_ALWAYS = {"sw.js", "sw-policy.js", "manifest.webmanifest"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


def mount_frontend(app: FastAPI, dist_dir: str) -> None:
    """Serve files under dist_dir, falling back to index.html for non-/api GETs."""
    root_str = os.path.realpath(dist_dir)
    index = os.path.join(root_str, "index.html")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        if full_path:
            try:
                full = os.path.realpath(os.path.join(root_str, full_path))
            except (OSError, ValueError):
                raise HTTPException(status_code=404) from None
            if full.startswith(root_str + os.sep) and os.path.isfile(full):
                headers = {"Cache-Control": "no-cache"} if full_path in REVALIDATE_ALWAYS or full_path == "index.html" else None
                return FileResponse(full, headers=headers)
        # A missing file (assets, icons, anything with an extension) is a real 404,
        # never index.html: the service worker would cache that HTML under a script URL.
        if full_path.startswith(("assets/", "icons/")) or "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
