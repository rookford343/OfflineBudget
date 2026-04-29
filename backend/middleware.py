"""Request audit logging middleware."""
from __future__ import annotations
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from backend.auth import decode_token
from backend.database import SessionLocal
from backend import models

# Paths to skip logging entirely
_SKIP_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

# Only log mutating methods (skip GET, HEAD, OPTIONS)
_LOG_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        if request.method not in _LOG_METHODS:
            return response
        if request.url.path in _SKIP_PATHS:
            return response

        # Try to identify the user from the JWT (best-effort)
        user_id = None
        username = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_token(token)
            if payload:
                user_id = payload.get("sub")
                username = payload.get("username")
                if user_id:
                    try:
                        user_id = int(user_id)
                    except (ValueError, TypeError):
                        user_id = None

        # Capture request body summary for mutation methods
        body_summary = None
        try:
            body_bytes = await request.body()
            if body_bytes:
                text = body_bytes.decode("utf-8", errors="replace")
                body_summary = text[:200] if len(text) > 200 else text
        except Exception:
            pass

        try:
            db = SessionLocal()
            log_entry = models.AuditLog(
                user_id=user_id,
                username=username,
                method=request.method,
                path=str(request.url.path),
                status_code=response.status_code,
                duration_ms=duration_ms,
                body_summary=body_summary,
            )
            db.add(log_entry)
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

        return response
