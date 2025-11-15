import logging
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_protocols():
    """Fixture for a mocked SDProtocols."""
    protocols = MagicMock()
    protocols.demodulate = MagicMock(return_value=[])
    return protocols


@pytest.fixture
def logger():
    """Fixture for a logger."""
    return logging.getLogger(__name__)


@pytest.fixture
def proto():
    """Fixture for a real SDProtocols instance."""
    from sd_protocols import SDProtocols
    return SDProtocols()