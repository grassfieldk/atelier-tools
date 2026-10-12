from .base import GameAdapter
from .meruru import MeruruAdapter

_GAMES: dict[str, GameAdapter] = {"meruru-dx": MeruruAdapter()}


def get_game(game_id: str) -> GameAdapter:
    try:
        return _GAMES[game_id]
    except KeyError as exception:
        raise ValueError("ゲームが見つかりません") from exception


def registered_games() -> tuple[GameAdapter, ...]:
    return tuple(_GAMES.values())
