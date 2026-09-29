from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .core import PROJECT_ROOT, read_summary, search_index, search_structured


WEB_ROOT = PROJECT_ROOT / "web"
GAMES = {
    "meruru-dx": {
        "title": {"ja": "メルルのアトリエ DX", "en": "Atelier Meruru DX", "zh": "梅露露的炼金工房 DX"},
        "series": {"ja": "アーランドシリーズ", "en": "Arland Series", "zh": "亚兰德系列"},
    },
}


def create_app() -> FastAPI:
    app = FastAPI(title="Atelier Tools", version="0.2.0", docs_url=None, redoc_url=None)

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, exception: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exception)})

    @app.get("/api/games")
    async def games(language: str = "ja") -> dict:
        available = read_summary() is not None
        language = language if language in {"ja", "en", "zh"} else "ja"
        items = [
            {"id": game_id, "title": game["title"][language], "series": game["series"][language]}
            for game_id, game in GAMES.items()
        ] if available else []
        return {"items": items}

    @app.get("/api/games/{game_id}/search")
    async def search(
        game_id: str,
        q: str = "",
        category: str = "all",
        language: str = "all",
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> dict:
        if game_id not in GAMES:
            raise HTTPException(status_code=404, detail="ゲームが見つかりません")
        items = await run_in_threadpool(search_index, q, category, language, limit)
        return {"count": len(items), "limit": limit, "items": items}

    @app.get("/api/games/{game_id}/data/{kind}")
    async def game_data(
        game_id: str,
        kind: str,
        q: str = "",
        language: str = "ja",
    ) -> dict:
        if game_id not in GAMES:
            raise HTTPException(status_code=404, detail="ゲームが見つかりません")
        items = await run_in_threadpool(search_structured, kind, q, language)
        return {"count": len(items), "items": items}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/games/{game_id}")
    async def game(game_id: str) -> FileResponse:
        if game_id not in GAMES:
            raise HTTPException(status_code=404, detail="ゲームが見つかりません")
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=WEB_ROOT), name="web")
    return app
