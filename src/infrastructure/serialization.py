"""Explicit JSONB serialization for Challenge.expected_result."""

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from domain.result_matching import (
    Cell,
    FrozenResult,
    QueryResult,
    freeze_expected_result,
)

_DECIMAL_TAG = "decimal"


def serialize_expected_result(result: QueryResult) -> list[list[Any]]:
    """Convert a domain QueryResult into a JSON-serializable list of rows."""
    return [[_encode_cell(cell) for cell in row] for row in result]


def deserialize_expected_result(payload: Any) -> FrozenResult:
    """Restore a validated, immutable FrozenResult from JSONB payload."""
    if not isinstance(payload, list):
        raise ValueError("expected_result payload must be a list of rows")
    rows: list[list[Cell]] = []
    for raw_row in payload:
        if not isinstance(raw_row, list):
            raise ValueError("each expected_result row must be a list")
        rows.append([_decode_cell(item) for item in raw_row])
    try:
        return freeze_expected_result(rows)
    except Exception as exc:  # DomainValidationError inherits from ValueError
        raise ValueError(str(exc)) from exc


def _encode_cell(cell: Cell) -> Any:
    if cell is None:
        return None
    if isinstance(cell, bool):  # checked before int because bool subclasses int
        return cell
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float):
        if not math.isfinite(cell):
            raise ValueError("expected_result cannot contain non-finite floats")
        return cell
    if isinstance(cell, str):
        return cell
    if isinstance(cell, Decimal):
        if not cell.is_finite():
            raise ValueError("expected_result cannot contain non-finite Decimals")
        return {"__type__": _DECIMAL_TAG, "value": str(cell)}
    raise ValueError(f"unsupported expected_result cell type: {type(cell).__name__}")


def _decode_cell(item: Any) -> Cell:
    if item is None:
        return None
    if isinstance(item, bool):  # checked before int because bool subclasses int
        return item
    if isinstance(item, int | float | str):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("expected_result cannot contain non-finite floats")
        return item
    if isinstance(item, dict) and item.get("__type__") == _DECIMAL_TAG:
        raw_value = item.get("value")
        if not isinstance(raw_value, str):
            raise ValueError("decimal payload must carry a string value")
        try:
            decimal_value = Decimal(raw_value)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal literal: {raw_value!r}") from exc
        if not decimal_value.is_finite():
            raise ValueError("expected_result cannot contain non-finite Decimals")
        return decimal_value
    raise ValueError(f"unsupported expected_result JSON value: {item!r}")
