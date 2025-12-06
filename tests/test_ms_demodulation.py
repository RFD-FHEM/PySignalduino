import pytest
from sd_protocols.sd_protocols import SDProtocols

class TestMSDemodulation:
    @pytest.fixture
    def protocols(self):
        return SDProtocols()

    def test_ms_demodulate_protocol_3_1(self, protocols):
        # Using Protocol 3.1 (IT V3 / self-learning?)
        # sync: [1, -44]
        # zero: [1, -3.8]
        # one: [3.5, -1]
        # length_min: 24
        # preamble: "i"
        
        # Clock = 330
        # P0 = 330 (1)
        # P1 = -14520 (-44)
        # P2 = -1254 (-3.8)
        # P3 = 1155 (3.5)
        # P4 = -330 (-1)
        
        # Sync: P0, P1 -> "01"
        # Zero: P0, P2 -> "02"
        # One: P3, P4 -> "34"
        
        # Send 23 zeros and 1 one to satisfy pattern matching requirements
        # Data: "01" + "02"*23 + "34"
    
        msg_data = {
            "P0": "330",
            "P1": "-14520",
            "P2": "-1254",
            "P3": "1155",
            "P4": "-330",
            "data": "01" + "02"*23 + "34",
            "CP": "0",
            "SP": "0", # irrelevant
            "R": "0"
        }
    
        results = protocols.demodulate(msg_data, "MS")
    
        found = False
        for res in results:
            if res['protocol_id'] == '3.1':
                found = True
                assert res['meta']['bit_length'] == 24
                # 23 zeros + 1 one = 0000...01
                # Hex: 000001
                
                # Check payload starts with 'i'
                assert res['payload'].startswith('i')
                # 24 bits = 6 hex digits. Last digit 1.
                assert '000001' in res['payload']
        
        assert found
