"""Smoke test: the four Clean Architecture packages are importable."""

import importlib

import pytest

LAYER_PACKAGES = ("domain", "application", "infrastructure", "api")


@pytest.mark.parametrize("package", LAYER_PACKAGES)
def test_layer_package_is_importable(package: str) -> None:
    module = importlib.import_module(package)

    assert module.__name__ == package
