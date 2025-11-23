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