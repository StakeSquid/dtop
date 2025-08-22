#!/usr/bin/env python3
"""
Standalone entry point for dtop - works better with PyInstaller
"""
import sys
import os

# Add the package to path if needed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dtop.main import main

if __name__ == '__main__':
    main()