from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .core import PROJECT_ROOT
from .controller import get_data, get_detail, list_games, search_game
from .games.registry import get_game
from .models import DataKind, DataResponse, DetailResponse, GamesResponse, Language


WEB_ROOT = PROJECT_ROOT / "web"
def require_game(game_id: str) -> None:
    try:
        get_game(game_id)
    except ValueError as exception:
        raise HTTPException(status_code=404, detail=str(exception)) from exception


def create_app() -> FastAPI:
    app = FastAPI(title="Atelier Tools", version="0.2.0", docs_url=None, redoc_url=None)

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, exception: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exception)})

    @app.get("/api/games")
    async def games(language: Language = "ja") -> GamesResponse:
        return await run_in_threadpool(list_games, language)

    @app.get("/api/games/{game_id}/search")
    async def search(
        game_id: str,
        q: str = "",
        category: str = "all",
        language: str = "all",
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> dict:
        require_game(game_id)
        try:
            items = await run_in_threadpool(search_game, game_id, q, category, language, limit)
        except FileNotFoundError as exception:
            raise HTTPException(status_code=404, detail=str(exception)) from exception
        return {"count": len(items), "limit": limit, "items": items}

    @app.get("/api/games/{game_id}/data/{kind}")
    async def game_data(
        game_id: str,
        kind: DataKind,
        q: str = "",
        language: Language = "ja",
    ) -> DataResponse:
        require_game(game_id)
        try:
            return await run_in_threadpool(get_data, game_id, kind, language, q)
        except FileNotFoundError as exception:
            raise HTTPException(status_code=404, detail=str(exception)) from exception

    @app.get("/api/games/{game_id}/data/{kind}/{identifier}")
    async def game_detail(game_id: str, kind: DataKind, identifier: int, language: Language = "ja") -> DetailResponse:
        require_game(game_id)
        try:
            return await run_in_threadpool(get_detail, game_id, kind, identifier, language)
        except FileNotFoundError as exception:
            raise HTTPException(status_code=404, detail=str(exception)) from exception

    @app.get("/games/{game_id}/{kind}/{identifier}")
    async def detail_page(game_id: str, kind: DataKind, identifier: int) -> FileResponse:
        require_game(game_id)
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/games/{game_id}")
    async def game(game_id: str) -> FileResponse:
        require_game(game_id)
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=WEB_ROOT), name="web")
    return app
