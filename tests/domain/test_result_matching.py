"""Tests for the query result comparison rules (see docs/decisions.md)."""

from decimal import Decimal

import pytest

from domain.result_matching import Cell, results_match

# --- Rows and columns -------------------------------------------------------


def test_identical_results_match() -> None:
    assert results_match([(1, "Ana")], [(1, "Ana")])


def test_empty_results_match() -> None:
    assert results_match([], [])


def test_empty_result_does_not_match_non_empty() -> None:
    assert not results_match([], [(1,)])


def test_row_order_is_ignored_by_default() -> None:
    assert results_match([(2, "Luis"), (1, "Ana")], [(1, "Ana"), (2, "Luis")])


def test_row_order_is_respected_when_ordered() -> None:
    assert not results_match([(2,), (1,)], [(1,), (2,)], ordered=True)


def test_same_row_order_matches_when_ordered() -> None:
    assert results_match([(1,), (2,)], [(1,), (2,)], ordered=True)


def test_ordered_comparison_still_counts_duplicates() -> None:
    assert not results_match([(1,), (1,), (2,)], [(1,), (2,)], ordered=True)


def test_extra_duplicate_row_does_not_match() -> None:
    assert not results_match([(1, "Ana"), (1, "Ana")], [(1, "Ana")])


def test_missing_duplicate_row_does_not_match() -> None:
    assert not results_match([(1, "Ana")], [(1, "Ana"), (1, "Ana")])


def test_extra_row_does_not_match() -> None:
    assert not results_match([(1,), (2,), (3,)], [(1,), (2,)])


def test_different_value_does_not_match() -> None:
    assert not results_match([(1, "Ana")], [(1, "Luis")])


def test_extra_column_does_not_match() -> None:
    assert not results_match([(1, "Ana", None)], [(1, "Ana")])


def test_columns_are_compared_by_position() -> None:
    assert not results_match([("Ana", 1)], [(1, "Ana")])


# --- None -------------------------------------------------------------------


def test_none_matches_none() -> None:
    assert results_match([(None,)], [(None,)])


@pytest.mark.parametrize("value", [0, "", False, Decimal("0"), 0.0])
def test_none_does_not_match_falsy_values(value: Cell) -> None:
    assert not results_match([(None,)], [(value,)])
    assert not results_match([(value,)], [(None,)])


# --- Booleans (checked before int) ------------------------------------------


@pytest.mark.parametrize(
    ("boolean", "number"),
    [(True, 1), (False, 0), (True, Decimal("1")), (True, 1.0), (False, 0.0)],
)
def test_booleans_do_not_match_numbers(boolean: bool, number: Cell) -> None:
    assert not results_match([(boolean,)], [(number,)])
    assert not results_match([(number,)], [(boolean,)])


def test_booleans_do_not_match_numbers_when_ordered() -> None:
    assert not results_match([(True,)], [(1,)], ordered=True)


def test_booleans_match_same_booleans() -> None:
    assert results_match([(True,), (False,)], [(False,), (True,)])


# --- Numbers and decimals ---------------------------------------------------


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (1, 1.0),
        (1, Decimal("1.0000")),
        (Decimal("2.5"), 2.5),
        (0.1 + 0.2, 0.3),
        (10**30, Decimal("1E+30")),
        (-0.00001, 0),
    ],
)
def test_equivalent_numbers_match(actual: Cell, expected: Cell) -> None:
    assert results_match([(actual,)], [(expected,)])


def test_numbers_equal_at_four_decimal_places_match() -> None:
    assert results_match([(1,)], [(1.00004,)])


@pytest.mark.parametrize("other", [1.0001, 1.001, Decimal("0.9999")])
def test_numbers_differing_at_four_decimal_places_do_not_match(other: Cell) -> None:
    assert not results_match([(1,)], [(other,)])


@pytest.mark.parametrize(
    ("value", "rounded"),
    [
        (Decimal("1.00005"), Decimal("1.0000")),
        (Decimal("1.00015"), Decimal("1.0002")),
        (Decimal("1.00025"), Decimal("1.0002")),
        (Decimal("-1.00005"), Decimal("-1.0000")),
    ],
)
def test_half_even_rounding_at_fourth_decimal(value: Decimal, rounded: Decimal) -> None:
    assert results_match([(value,)], [(rounded,)])


def test_values_straddling_a_rounding_boundary_do_not_match() -> None:
    """Known limitation: rounding is not a tolerance.

    These values are 2e-8 apart, but 1.00014999 rounds to 1.0001 and
    1.00015001 rounds to 1.0002, so they do not match.
    """
    assert not results_match([(Decimal("1.00014999"),)], [(Decimal("1.00015001"),)])


def test_number_does_not_match_numeric_text() -> None:
    assert not results_match([(1,)], [("1",)])


# --- Non-finite numbers -----------------------------------------------------

NON_FINITE: list[Cell] = [
    float("nan"),
    float("inf"),
    float("-inf"),
    Decimal("NaN"),
    Decimal("sNaN"),
    Decimal("Infinity"),
    Decimal("-Infinity"),
]


@pytest.mark.parametrize("value", NON_FINITE)
def test_non_finite_numbers_never_match_themselves(value: Cell) -> None:
    assert not results_match([(value,)], [(value,)])
    assert not results_match([(value,)], [(value,)], ordered=True)


@pytest.mark.parametrize("value", NON_FINITE)
def test_non_finite_numbers_do_not_match_finite_numbers(value: Cell) -> None:
    assert not results_match([(value,)], [(0,)])
    assert not results_match([(0,)], [(value,)])


# --- Text -------------------------------------------------------------------


def test_text_is_case_sensitive() -> None:
    assert not results_match([("Ana",)], [("ana",)])


def test_text_is_whitespace_sensitive() -> None:
    assert not results_match([("Ana ",)], [("Ana",)])
