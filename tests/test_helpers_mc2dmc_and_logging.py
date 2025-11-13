import pytest
from sd_protocols.sd_protocols import SDProtocols


@pytest.fixture
def fresh_proto():
    """Provide a fresh SDProtocols instance without conftest modifications."""
    return SDProtocols()


class TestMc2Dmc:
    """Tests migrated from temp_repo/t/SD_Protocols/02_mc2dmc.t"""

    def test_mc2dmc_no_args(self, fresh_proto):
        """mc2dmc without arguments -> (-1, 'no bitData provided')"""
        result = fresh_proto.mc2dmc(None)
        assert result == (-1, "no bitData provided")

    def test_mc2dmc_1001_to_010(self, fresh_proto):
        """mc2dmc 1001 => 010"""
        assert fresh_proto.mc2dmc("1001") == "010"

    def test_mc2dmc_110010_to_10100(self, fresh_proto):
        """mc2dmc 110010 => 10100"""
        assert fresh_proto.mc2dmc("110010") == "10100"


class TestRegisterLogCallback:
    """Tests migrated from temp_repo/t/SD_Protocols/01_registerLogCallback.t"""

    def test_register_log_callback_and_logging(self, fresh_proto):
        events = []

        def callback(message, level):
            # Mirror Perl test expectations: message and level captured
            events.append((level, message))

        # Register the callback
        fresh_proto.register_log_callback(callback)

        # Ensure it was stored
        assert callable(fresh_proto._log_callback)

        # Trigger logging
        fresh_proto._logging("Heavy debug message", 5)

        # Verify captured event (level, message)
        assert events == [(5, "Heavy debug message")]
