"""Structured API errors: {code, message, hint}. Stack traces and secrets never leave the server."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("neuroqueue")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str = "") -> None:
        self.status, self.code, self.message, self.hint = status, code, message, hint
        super().__init__(message)


def _body(code: str, message: str, hint: str = "") -> dict:
    return {"code": code, "message": message, "hint": hint}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(_body(e.code, e.message, e.hint), status_code=e.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return JSONResponse(_body(f"HTTP_{e.status_code}", str(e.detail)), status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(_body("VALIDATION_ERROR", f"{where}: {first.get('msg', 'invalid input')}".strip(": "),
                                  "Check the request fields and try again."), status_code=422)

    @app.exception_handler(Exception)
    async def _any(request: Request, e: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("INTERNAL_ERROR", "Something went wrong on the server.",
                                  "Try again. If it keeps happening, contact support."), status_code=500)
