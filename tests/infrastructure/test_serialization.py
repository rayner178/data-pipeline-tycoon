"""Tests for explicit JSONB serialization of expected_result."""

from decimal import Decimal
from typing import Any

import pytest

from infrastructure.serialization import (
    deserialize_expected_result,
    serialize_expected_result,
)


def test_round_trip_preserves_types_and_tuple_structure() -> None:
    original = (
        (1, "Ana", True, Decimal("12.3400"), 3.5, None),
        (2, "12.3400", False, Decimal("0.0001"), 0, "0"),
    )

    encoded = serialize_expected_result(original)
    decoded = deserialize_expected_result(encoded)

    assert isinstance(encoded, list)
    assert all(isinstance(row, list) for row in encoded)
    assert decoded == original
    assert isinstance(decoded, tuple)
    assert all(isinstance(row, tuple) for row in decoded)
    # bool must stay bool, Decimal must stay Decimal with exact scale, str stays str
    assert type(decoded[0][2]) is bool
    assert type(decoded[1][2]) is bool
    assert type(decoded[0][3]) is Decimal
    assert str(decoded[0][3]) == "12.3400"
    assert type(decoded[1][1]) is str
    assert type(decoded[1][4]) is int


def test_empty_expected_result_round_trip() -> None:
    encoded = serialize_expected_result(())
    decoded = deserialize_expected_result(encoded)

    assert encoded == []
    assert decoded == ()


def test_decimal_encoded_with_explicit_type_tag() -> None:
    encoded = serialize_expected_result(((Decimal("42.50"), "42.50"),))

    assert encoded == [[{"__type__": "decimal", "value": "42.50"}, "42.50"]]


@pytest.mark.parametrize(
    "bad_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
    ],
)
def test_serialize_rejects_non_finite_numbers(bad_value: float | Decimal) -> None:
    with pytest.raises(ValueError):
        serialize_expected_result(((bad_value,),))


def test_serialize_rejects_unsupported_cell_type() -> None:
    bad: Any = ((object(),),)
    with pytest.raises(ValueError):
        serialize_expected_result(bad)


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-list",
        ["row-not-a-list"],
        [[{"__type__": "unknown", "value": "1"}]],
        [[{"__type__": "decimal", "value": "not-a-decimal"}]],
        [[{"__type__": "decimal", "value": "NaN"}]],
        [[{"__type__": "decimal"}]],
        [[1], [1, 2]],
    ],
)
def test_deserialize_rejects_invalid_payload(payload: Any) -> None:
    with pytest.raises(ValueError):
        deserialize_expected_result(payload)
