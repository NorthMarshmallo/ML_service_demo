import pytest
from fastapi.testclient import TestClient

from amr_prediction.service.app import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def good_row():
    return {
        "sequence": "FISEAVIAVIIDWIDNNLHKPLRIEQIARYSGYSKWYLQRLFLQYRGESLGRYIRNKKLDSAARDLRETDENIYSIGLRYGYDSQQTFTRLFTRHFHLPPGEYRKKNK"
    }