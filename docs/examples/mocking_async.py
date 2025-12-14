from unittest.mock import AsyncMock, MagicMock

mock_client = AsyncMock()
mock_client.__aenter__ = AsyncMock(return_value=mock_client)
mock_client.__aexit__ = AsyncMock(return_value=None)