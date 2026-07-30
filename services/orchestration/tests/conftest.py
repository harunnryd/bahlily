import itertools
from typing import Any

import pytest

from tests.utils import FakeToolCallingModel


@pytest.fixture
def make_fake_model() -> Any:
    def _make(responses: list[Any]) -> FakeToolCallingModel:
        return FakeToolCallingModel(messages=itertools.cycle(responses))

    return _make
