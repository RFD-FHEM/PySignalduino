import pytest
from sd_protocols.pattern_utils import pattern_exists, calculate_tolerance

class TestPatternUtils:
    
    def test_calculate_tolerance(self):
        assert calculate_tolerance(1) == 1.0
        assert calculate_tolerance(2) == 1.0
        assert calculate_tolerance(3) == 1.0
        assert calculate_tolerance(4) == pytest.approx(1.2) # 4 * 0.3
        assert calculate_tolerance(10) == pytest.approx(3.0) # 10 * 0.3
        assert calculate_tolerance(20) == pytest.approx(3.6) # 20 * 0.18 (abs > 16)
        assert calculate_tolerance(-10) == pytest.approx(3.0)
    
    def test_pattern_exists_simple_match(self):
        # Search [1, -1] in patterns {0: 1.0, 1: -1.0}
        # Data "0101"
        patterns = {'0': 1.0, '1': -1.0}
        search = [1, -1]
        data = "0101"
        
        result = pattern_exists(search, patterns, data)
        assert result == "01"
        
    def test_pattern_exists_tolerance_match(self):
        # Search [10, -5]
        # Patterns: 0=11 (gap 1, tol=3), 1=-4 (gap 1, tol=1.5)
        patterns = {'0': 11.0, '1': -4.0}
        search = [10, -5]
        data = "01"
        
        result = pattern_exists(search, patterns, data)
        assert result == "01"
        
    def test_pattern_exists_no_match_values(self):
        # Value out of tolerance
        patterns = {'0': 20.0} # 20 vs 1 (tol 1) -> fail
        search = [1]
        data = "0"
        
        result = pattern_exists(search, patterns, data)
        assert result == -1
        
    def test_pattern_exists_match_values_not_in_data(self):
        patterns = {'0': 1.0}
        search = [1]
        data = "222" # Pattern 0 matches value 1, but "0" is not in data
        
        result = pattern_exists(search, patterns, data)
        assert result == -1

    def test_pattern_exists_ambiguity_check(self):
        # P0 fits both 1 and 2 (if tolerance allows)
        # Tol(1)=1 -> 0..2. P0=1.5 fits.
        # Tol(2)=1 -> 1..3. P0=1.5 fits.
        # So P0 is candidate for both 1 and 2.
        # Cartesian product will generate combination ['0', '0'].
        # Unique check should reject this because '0' maps to different logic values.
        
        patterns = {'0': 1.5}
        search = [1, 2]
        data = "00"
        
        # Should fail because '0' cannot represent both 1 and 2 in the same mapping set
        result = pattern_exists(search, patterns, data)
        assert result == -1
        
    def test_pattern_exists_sequence(self):
        # Search [1, 1] (two same pulses)
        patterns = {'0': 1.0}
        search = [1, 1]
        data = "00"
        
        # Unique values: [1]. Candidate for 1: ['0'].
        # Combination: ['0']. Mapping: 1->'0'.
        # Target string: '0' + '0' = "00".
        # Found in data.
        
        result = pattern_exists(search, patterns, data)
        assert result == "00"

    def test_pattern_exists_multiple_candidates(self):
        # P0=1.0, P1=1.1. Both fit 1.
        # Search [1]
        patterns = {'0': 1.0, '1': 1.1}
        search = [1]
        data = "1" # Only 1 is in data
        
        # Candidates for 1: ['0', '1'] (sorted by gap, 0 gap=0, 1 gap=0.1)
        # Combinations: [['0'], ['1']]
        # Loop 1: map 1->0. Target "0". Not in data.
        # Loop 2: map 1->1. Target "1". In data.
        
        result = pattern_exists(search, patterns, data)
        assert result == "1"
