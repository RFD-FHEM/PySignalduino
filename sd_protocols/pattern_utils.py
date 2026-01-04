"""
Pattern matching utilities for SIGNALduino protocols.
Ports logic from SIGNALduino_PatternExists and related Perl functions.
"""
from __future__ import annotations
import logging
import math
import itertools
from typing import Dict, List, Any, Optional, Tuple, Union

def is_in_tolerance(val1: float, val2: float, tol: float) -> bool:
    """Checks if abs(val1 - val2) <= tol."""
    return abs(val1 - val2) <= tol

def calculate_tolerance(val: float) -> float:
    """
    Calculates tolerance for a search value based on Perl logic.
    Perl: abs(abs($searchpattern)>3 ? abs($searchpattern)>16 ? $searchpattern*0.18 : $searchpattern*0.3 : 1)
    """
    abs_val = abs(val)
    if abs_val > 3:
        if abs_val > 16:
            return abs_val * 0.18
        else:
            return abs_val * 0.3
    return 1.0

def cartesian_product(lists: List[List[Any]]) -> List[List[Any]]:
    """Generates cartesian product of input lists."""
    if not lists:
        return [[]]
    return [list(p) for p in itertools.product(*lists)]

def pattern_exists(search_pattern: List[float], pattern_list: Dict[str, float], raw_data: str, debug_callback=None) -> Union[str, int]:
    """
    Checks if a sequence of values exists in the pattern list and finds matches in raw data.
    
    Args:
        search_pattern: List of logical pulse values to search for (e.g., [1, -1]).
        pattern_list: Dictionary of available patterns {id: value} (e.g., {'0': 1.0, '1': -1.0}).
        raw_data: The raw data string (sequence of pattern IDs) to search in.
        debug_callback: Optional callback for debug logging.
        
    Returns:
        The matching pattern string (e.g., "01") if found, otherwise -1.
    """
    
    # 1. Identify unique values in search pattern and find candidates for each
    unique_search_values = []
    seen_values = set()
    candidates_map: Dict[float, List[str]] = {} # Map search_val -> list of pattern_ids
    
    # Preserve order of first appearance for unique values
    for val in search_pattern:
        if val not in seen_values:
            seen_values.add(val)
            unique_search_values.append(val)
            
    # Find candidates for each unique search value
    candidates_list: List[List[str]] = []
    
    for search_val in unique_search_values:
        tol = calculate_tolerance(search_val)
        
        if debug_callback:
            debug_callback(f"tol: looking for ({search_val} +- {tol})")
            
        # Find matches in pattern_list
        matches = []
        # Store gaps for sorting: (gap, pattern_id)
        weighted_matches = []
        
        for pid, pval in pattern_list.items():
            gap = abs(pval - search_val)
            if gap <= 0.001 or gap <= tol: # The gap is likely 0.0 for exact match, add a small tolerance to guarantee it
                weighted_matches.append((gap, pid))
        
        if not weighted_matches:
            # If any value has no candidates, the pattern cannot exist
            return -1
            
        # Sort by gap (smallest first) and extract PIDs
        weighted_matches.sort(key=lambda x: x[0])
        matches = [m[1] for m in weighted_matches]
        
        candidates_list.append(matches)
        
    # 2. Generate cartesian product of candidates
    # This gives us all possible assignments of Pattern IDs to the Unique Search Values
    # e.g. search=[1, -1], candidates(1)=['0'], candidates(-1)=['1'] -> product=[['0', '1']]
    
    # Check for explosion risk
    total_combinations = 1
    for c in candidates_list:
        total_combinations *= len(c)
        
    if total_combinations > 10000:
        if debug_callback:
            debug_callback(f"Too many combinations: {total_combinations}. Aborting pattern match.")
        logging.debug(f"Too many combinations: {total_combinations} for {search_pattern}")
        return -1

    product = cartesian_product(candidates_list)
    
    if debug_callback:
        debug_callback(f"indexer: {unique_search_values}")
        debug_callback(f"sumlists: {candidates_list}")
        debug_callback(f"res: {product}")

    # 3. Check each combination
    for combination in product:
        # Check for duplicates: A single Pattern ID cannot map to different Search Values
        # Perl: next OUTERLOOP if ($count{$_} > 1)
        if len(set(combination)) != len(combination):
            continue
            
        # Create mapping: Search Value -> Pattern ID
        mapping = {}
        for i, search_val in enumerate(unique_search_values):
            mapping[search_val] = combination[i]
            
        # 4. Construct the target string
        target_string_parts = []
        for val in search_pattern:
            target_string_parts.append(mapping[val])
            
        target_string = "".join(target_string_parts)
        
        if debug_callback:
            debug_callback(f"Checking target string: {target_string}")
            
        # 5. Search in raw data
        if target_string in raw_data:
            return target_string
            
    return -1
