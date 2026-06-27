import pytest

from daedalus.ledger import Ledger


@pytest.fixture
def ledger():
    lg = Ledger(":memory:")
    yield lg
    lg.close()
