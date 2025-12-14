import pytest
import logging
from sd_protocols.sd_protocols import SDProtocols
from signalduino.parser.ms import MSParser
from signalduino.types import RawFrame

class TestMSParser:
    @pytest.fixture
    def protocols(self):
        return SDProtocols()
        
    @pytest.fixture
    def parser(self, protocols):
        logger = logging.getLogger("TestMSParser")
        return MSParser(protocols, logger)

    def test_corrupt_ms_data_special_chars(self, parser):
        # testname: Corrupt MS data, special chars
        # input: MS;=0;L=L=-1020;L=H=935;S=L=-525;S=H=444;D=354133323044313642333731303246303541423044364430;C==487;L==89;R==24;
        
        line = "MS;=0;L=L=-1020;L=H=935;S=L=-525;S=H=444;D=354133323044313642333731303246303541423044364430;C==487;L==89;R==24;"
        frame = RawFrame(line)
        
        results = list(parser.parse(frame))
        assert results == []

    def test_corrupt_ms_data_structure_broken(self, parser):
        # testname: Corrupt MS data, special char and structure broken
        # input: MS;P1=;L=L=-1015;L=H=944;S=L=-512;S=H=456;D=353531313436304235313330433137433244353036423130;C==487;L==89;R==45;
        
        line = "MS;P1=;L=L=-1015;L=H=944;S=L=-512;S=H=456;D=353531313436304235313330433137433244353036423130;C==487;L==89;R==45;"
        frame = RawFrame(line)
        
        results = list(parser.parse(frame))
        assert results == []

    def test_corrupt_ms_data_invalid_rssi(self, parser):
        # testname: Corrupt MS data, R= Argument "1q" isn't numeric
        # input: MS;P1=-8043;P2=505;P3=-1979;P4=-3960;D=2121232323242424232423242323232323242324232424232324242323232323232323232323232323242423;CP=2;SP=1;R=1q;
        
        line = "MS;P1=-8043;P2=505;P3=-1979;P4=-3960;D=2121232323242424232423242323232323242324232424232324242323232323232323232323232323242423;CP=2;SP=1;R=1q;"
        frame = RawFrame(line)
        
        results = list(parser.parse(frame))
        assert results == []

    def test_correct_mc_cul_tcm_97001(self, parser):
        # testname: Correct MC CUL_TCM_97001
        # input: MS;P1=502;P2=-9212;P3=-1939;P4=-3669;D=12131413141414131313131313141313131313131314141414141413131313141413131413;CP=1;SP=2;
        
        line = "MS;P1=502;P2=-9212;P3=-1939;P4=-3669;D=12131413141414131313131313141313131313131314141414141413131313141413131413;CP=1;SP=2;"
        frame = RawFrame(line)
        
        results = list(parser.parse(frame))
        
        # Expect at least one result
        assert len(results) > 0
        
        # Optional: Check if it matched Protocol 0
        p0_match = any(r.protocol_id == '0' for r in results)
        assert p0_match
