from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["ja", "en", "zh"]
DataKind = Literal["items", "recipes", "traits", "maps", "monsters"]
DATA_KINDS: tuple[DataKind, ...] = ("items", "recipes", "traits", "maps", "monsters")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedText(Model):
    ja: str
    en: str
    zh: str


class TextColumn(Model):
    type: Literal["text"] = "text"
    id: str
    label: LocalizedText


class NumberColumn(Model):
    type: Literal["number"] = "number"
    id: str
    label: LocalizedText


Column = Annotated[TextColumn | NumberColumn, Field(discriminator="type")]


class TextCell(Model):
    type: Literal["text"]
    value: str | None


class NumberCell(Model):
    type: Literal["number"]
    value: float | None


Cell = Annotated[TextCell | NumberCell, Field(discriminator="type")]


class Reference(Model):
    kind: Literal["items", "categories", "monsters"]
    id: int


class Ingredient(Model):
    reference: Reference
    quantity: float


class Entity(Model):
    id: int
    name: LocalizedText
    cells: dict[str, dict[Language, Cell]]
    attributes: dict[str, str | float | bool | None] = Field(default_factory=dict)


class Item(Entity):
    kind: Literal["items"]
    categories: list[int] = Field(default_factory=list)


class Recipe(Entity):
    kind: Literal["recipes"]
    result: int
    ingredients: list[Ingredient]


class Trait(Entity):
    kind: Literal["traits"]


class MapArea(Entity):
    kind: Literal["maps"]
    items: list[int]
    monsters: list[int]


class MonsterDrop(Model):
    item: int | None
    source_item_id: int
    slot: int
    source_values: list[int]


class Monster(Entity):
    kind: Literal["monsters"]
    drops: list[MonsterDrop] = Field(default_factory=list)


class Dataset(Model):
    items: list[Item]
    recipes: list[Recipe]
    traits: list[Trait]
    maps: list[MapArea]
    monsters: list[Monster]
    categories: dict[int, LocalizedText] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> Dataset:
        identifiers: dict[str, set[int]] = {"categories": set(self.categories)}
        for kind in DATA_KINDS:
            entities = getattr(self, kind)
            identifiers[kind] = {entity.id for entity in entities}
            if len(identifiers[kind]) != len(entities):
                raise ValueError(f"Duplicate IDs: {kind}")
        for item in self.items:
            if not set(item.categories) <= identifiers["categories"]:
                raise ValueError(f"Unknown category: {item.id}")
        for recipe in self.recipes:
            if recipe.result not in identifiers["items"]:
                raise ValueError(f"Unknown recipe result: {recipe.id}")
            for ingredient in recipe.ingredients:
                if ingredient.reference.id not in identifiers[ingredient.reference.kind]:
                    raise ValueError(f"Unknown ingredient: {recipe.id}")
        for area in self.maps:
            if not set(area.items) <= identifiers["items"] or not set(area.monsters) <= identifiers["monsters"]:
                raise ValueError(f"Unknown map reference: {area.id}")
        for monster in self.monsters:
            if any(drop.item is not None and drop.item not in identifiers["items"] for drop in monster.drops):
                raise ValueError(f"Unknown monster drop: {monster.id}")
        return self


class GameColumns(Model):
    items: list[Column]
    recipes: list[Column]
    traits: list[Column]
    maps: list[Column]
    monsters: list[Column]

    def for_kind(self, kind: DataKind) -> list[Column]:
        return getattr(self, kind)


class GameDefinition(Model):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: LocalizedText
    series: LocalizedText
    columns: GameColumns

    @model_validator(mode="after")
    def validate_columns(self) -> GameDefinition:
        for kind in DATA_KINDS:
            columns = self.columns.for_kind(kind)
            if len({column.id for column in columns}) != len(columns):
                raise ValueError("Duplicate column IDs")
        return self


class DisplayRow(Model):
    id: int
    cells: dict[str, Cell]


class DisplayTextColumn(Model):
    id: str
    label: str
    type: Literal["text"]


class DisplayNumberColumn(Model):
    id: str
    label: str
    type: Literal["number"]


DisplayColumn = Annotated[DisplayTextColumn | DisplayNumberColumn, Field(discriminator="type")]


class DisplayCategory(Model):
    id: int
    name: str


class DataResponse(Model):
    kind: DataKind
    count: int
    columns: list[DisplayColumn]
    items: list[DisplayRow]
    categories: list[DisplayCategory] = Field(default_factory=list)


class GameSummary(Model):
    id: str
    title: str
    series: str


class GamesResponse(Model):
    items: list[GameSummary]


class ApiContract(Model):
    games: GamesResponse
    data: DataResponse
    dataset: Dataset
    definition: GameDefinition
