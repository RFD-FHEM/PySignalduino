import logging
from unittest.mock import MagicMock

import pytest

from sd_protocols import SDProtocols
from signalduino.types import DecodedMessage




@pytest.fixture
def logger():
    """Fixture for a logger."""
    return logging.getLogger(__name__)


@pytest.fixture
def proto():
    """Fixture for a real SDProtocols instance."""
    return SDProtocols()

@pytest.fixture
def mock_protocols(mocker):
    """Fixture for a mocked SDProtocols instance."""
    mock = mocker.patch("signalduino.parser.mc.SDProtocols", autospec=True)
    return mock.return_value