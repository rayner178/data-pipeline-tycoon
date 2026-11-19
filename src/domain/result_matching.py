"""Rules that decide whether a query result matches an expected result.

Comparison rules (also documented in docs/decisions.md):

- Rows are compared as a multiset: order is ignored, duplicates count. With
  ``ordered=True`` the row order must match as well.
- Columns are compared by position; column names are not part of a result.
- ``None`` only matches ``None``.
- ``bool`` is checked before ``int`` and never matches a number.
- ``int``, ``float`` and ``Decimal`` are rounded to ``DECIMAL_PLACES`` places
  with ``ROUND_HALF_EVEN`` before comparing. Known limitation: this is rounding,
  not a tolerance, so values less than 0.0001 apart may still differ when they
  fall on different sides of a rounding boundary (1.00014999 vs 1.00015001).
- Non-finite numbers (NaN, sNaN, +/-Infinity) never match, not even themselves.
- Text is compared exactly (case and whitespace sensitive).
"""

import math
from collections import Counter
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal

from domain.errors import DomainValidationError

type Cell = str | int | float | Decimal | bool | None
type Row = Sequence[Cell]
type QueryResult = Sequence[Row]
type FrozenResult = tuple[tuple[Cell, ...], ...]

type _NormalizedCell = tuple[str, str | bool | Decimal | None]
type _NormalizedRow = tuple[_NormalizedCell, ...]

DECIMAL_PLACES = 4
_QUANTUM = Decimal(1).scaleb(-DECIMAL_PLACES)
_MIN_PRECISION = 28


def results_match(
    actual: QueryResult, expected: QueryResult, *, ordered: bool = False
) -> bool:
    """Return True when ``actual`` matches ``expected`` under the module rules."""
    if _contains_non_finite(actual) or _contains_non_finite(expected):
        return False
    actual_rows = [_normalize_row(row) for row in actual]
    expected_rows = [_normalize_row(row) for row in expected]
    if ordered:
        return actual_rows == expected_rows
    return Counter(actual_rows) == Counter(expected_rows)


def freeze_expected_result(result: QueryResult) -> FrozenResult:
    """Validate an expected result and return it as an immutable tuple of tuples."""
    frozen = tuple(tuple(row) for row in result)
    if len({len(row) for row in frozen}) > 1:
        raise DomainValidationError("all expected rows must have the same width")
    for row in frozen:
        for cell in row:
            _validate_expected_cell(cell)
    return frozen


def _validate_expected_cell(cell: Cell) -> None:
    if _is_non_finite(cell):  # checked first: non-finite values cannot be rounded
        raise DomainValidationError("expected values must be finite numbers")
    _normalize_cell(cell)


def _contains_non_finite(result: QueryResult) -> bool:
    return any(_is_non_finite(cell) for row in result for cell in row)


def _is_non_finite(cell: Cell) -> bool:
    if isinstance(cell, bool):
        return False
    if isinstance(cell, float):
        return not math.isfinite(cell)
    if isinstance(cell, Decimal):
        return not cell.is_finite()
    return False


def _normalize_row(row: Row) -> _NormalizedRow:
    return tuple(_normalize_cell(cell) for cell in row)


def _normalize_cell(cell: Cell) -> _NormalizedCell:
    if cell is None:
        return ("null", None)
    if isinstance(cell, bool):  # before int: bool is a subclass of int
        return ("bool", cell)
    if isinstance(cell, int | float | Decimal):
        return ("number", _round(_to_decimal(cell)))
    if isinstance(cell, str):
        return ("text", cell)
    raise DomainValidationError(f"unsupported cell type: {type(cell).__name__}")


def _to_decimal(value: int | float | Decimal) -> Decimal:
    if isinstance(value, float):
        return Decimal(str(value))  # avoids binary artifacts such as 0.1 + 0.2
    return Decimal(value)


def _round(value: Decimal) -> Decimal:
    precision = max(_MIN_PRECISION, value.adjusted() + DECIMAL_PLACES + 2)
    context = Context(prec=precision, rounding=ROUND_HALF_EVEN)
    return value.quantize(_QUANTUM, context=context)
