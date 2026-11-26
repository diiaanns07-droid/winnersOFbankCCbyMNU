"""Таксономия issue_type, иерархия и пограничные синонимы."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("taxonomy.toml")

EXACT, PARENT, BORDERLINE, NONE = "exact", "parent", "borderline", "none"


@dataclass(frozen=True)
class Taxonomy:
    types: dict[str, dict]
    kind_map: dict[str, str]
    source: str
    version: str = "1"
    _borderline: frozenset = field(default=frozenset(), repr=False)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Taxonomy":
        p = Path(path) if path else DEFAULT_PATH
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        types = data["types"]
        pairs = set()
        for name, spec in types.items():
            parent = spec.get("parent")
            if parent is not None and parent not in types:
                raise ValueError(f"taxonomy: {name}.parent={parent!r} не описан в [types]")
            for other in spec.get("borderline", []):
                if other not in types:
                    raise ValueError(f"taxonomy: {name}.borderline содержит неизвестный тип {other!r}")
                pairs.add(frozenset((name, other)))
        kind_map = {k.casefold(): v for k, v in data.get("product_kind_map", {}).items()}
        for k, v in kind_map.items():
            if v not in types:
                raise ValueError(f"taxonomy: product_kind_map[{k!r}]={v!r} не описан в [types]")
        return cls(types=types, kind_map=kind_map, source=str(p), version=str(data.get("version", "1")),
                   _borderline=frozenset(pairs))

    def known(self, issue_type: str) -> bool:
        return issue_type in self.types

    def parent(self, issue_type: str) -> str | None:
        return self.types.get(issue_type, {}).get("parent")

    def relation(self, pred_type: str, gold_type: str) -> str:
        """Связь типа предсказания с типом эталона: exact | parent | borderline | none.

        parent: предсказан родитель эталонного подтипа (например, contradiction для
        unit_mismatch) или наоборот. borderline: пара объявлена пограничной.
        """
        if pred_type == gold_type:
            return EXACT
        if self.parent(gold_type) == pred_type or self.parent(pred_type) == gold_type:
            return PARENT
        if frozenset((pred_type, gold_type)) in self._borderline:
            return BORDERLINE
        return NONE

    def map_kind(self, kind: str | None) -> tuple[str, bool]:
        """issue_type по Finding.kind продукта; второй элемент — найдено ли отображение."""
        if not kind:
            return "other", False
        key = str(kind).casefold()
        if key in self.types:
            return key, True
        if key in self.kind_map:
            return self.kind_map[key], True
        return "other", False
