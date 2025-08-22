#!/usr/bin/env python3
"""Test script to verify textual_log_view features."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dtop.views.textual_log_view import LogViewScreen

# Test filter expression parsing
def test_filter_parsing():
    screen = LogViewScreen(None)
    
    # Test basic expression
    tokens = screen.parse_filter_expression("error AND warning")
    print(f"Basic AND: {tokens}")
    assert tokens == [('TERM', 'error'), ('AND', 'AND'), ('TERM', 'warning')]
    
    # Test with parentheses
    tokens = screen.parse_filter_expression("(error OR warning) AND critical")
    print(f"With parentheses: {tokens}")
    assert ('LPAREN', '(') in tokens and ('RPAREN', ')') in tokens
    
    # Test quoted strings
    tokens = screen.parse_filter_expression('"multi word" AND test')
    print(f"Quoted string: {tokens}")
    assert ('TERM', 'multi word') in tokens
    
    # Test exclusion
    tokens = screen.parse_filter_expression("-exclude +include")
    print(f"Exclusion/inclusion: {tokens}")
    assert ('TERM', '-exclude') in tokens and ('TERM', '+include') in tokens
    
    print("✓ Filter parsing tests passed")

# Test filter evaluation
def test_filter_evaluation():
    screen = LogViewScreen(None)
    
    # Test basic AND
    tokens = [('TERM', 'error'), ('AND', 'AND'), ('TERM', 'log')]
    assert screen.evaluate_filter(tokens, "error in log file") == True
    assert screen.evaluate_filter(tokens, "error in file") == False
    
    # Test OR
    tokens = [('TERM', 'error'), ('OR', 'OR'), ('TERM', 'warning')]
    assert screen.evaluate_filter(tokens, "error message") == True
    assert screen.evaluate_filter(tokens, "warning message") == True
    assert screen.evaluate_filter(tokens, "info message") == False
    
    # Test exclusion
    tokens = [('TERM', '-debug')]
    assert screen.evaluate_filter(tokens, "error message") == True
    assert screen.evaluate_filter(tokens, "debug message") == False
    
    print("✓ Filter evaluation tests passed")

# Test timestamp extraction
def test_timestamp_extraction():
    screen = LogViewScreen(None)
    
    # Test Docker format
    log = "2024-01-15T10:30:45.123456789Z Starting service"
    ts = screen.extract_log_timestamp(log)
    assert ts is not None
    print(f"Docker timestamp: {ts}")
    
    # Test standard format
    log = "2024-01-15 10:30:45 Application started"
    ts = screen.extract_log_timestamp(log)
    assert ts is not None
    print(f"Standard timestamp: {ts}")
    
    # Test time only
    log = "10:30:45 Processing request"
    ts = screen.extract_log_timestamp(log)
    assert ts is not None
    print(f"Time only: {ts}")
    
    print("✓ Timestamp extraction tests passed")

if __name__ == "__main__":
    print("Testing textual_log_view features...")
    print("-" * 40)
    
    test_filter_parsing()
    print()
    test_filter_evaluation()
    print()
    test_timestamp_extraction()
    
    print("-" * 40)
    print("All tests passed! ✓")