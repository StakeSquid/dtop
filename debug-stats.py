#!/usr/bin/env python3
"""
Debug script to test docker stats output parsing
"""
import subprocess
import re

def parse_docker_io_string(io_string):
    """Parse Docker I/O string like '1.23GB / 4.56GB' and return tuple of bytes"""
    if not io_string or io_string == '-' or io_string == '--':
        return 0, 0
    
    # Parse strings like "1.23GB / 4.56GB" or "123MB / 456MB"
    parts = io_string.split(' / ')
    if len(parts) != 2:
        # Try without spaces
        parts = io_string.split('/')
        if len(parts) != 2:
            return 0, 0
    
    def parse_size(size_str):
        size_str = size_str.strip()
        # Handle kiB, MiB, GiB formats as well
        match = re.match(r'([\d.]+)\s*([KMGTP]i?B)?', size_str, re.IGNORECASE)
        if not match:
            return 0
        
        value = float(match.group(1))
        unit = match.group(2) or 'B'
        
        # Handle both binary (KiB) and decimal (KB) units
        multipliers = {
            'B': 1, 'KB': 1024, 'MB': 1024**2, 
            'GB': 1024**3, 'TB': 1024**4, 'PB': 1024**5,
            'KIB': 1024, 'MIB': 1024**2, 
            'GIB': 1024**3, 'TIB': 1024**4, 'PIB': 1024**5
        }
        
        unit_upper = unit.upper()
        return int(value * multipliers.get(unit_upper, 1))
    
    try:
        rx = parse_size(parts[0])
        tx = parse_size(parts[1])
        return rx, tx
    except:
        return 0, 0

# Get stats from docker
fmt = (
    "{{.Container}}|{{.Name}}|{{.CPUPerc}}|"
    "{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}"
)
cmd = ["docker", "stats", "--no-stream", "--format", fmt]

try:
    output = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    print("Raw output from docker stats:")
    print(output)
    print("\nParsed values:")
    
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) != 6:
            print(f"Skipping line with {len(parts)} parts: {line}")
            continue
            
        short_id, name, cpu, mem, netio, blockio = parts
        print(f"\nContainer: {name}")
        print(f"  CPU: {cpu}")
        print(f"  Memory: {mem}")
        print(f"  NetIO raw: '{netio}'")
        net_rx, net_tx = parse_docker_io_string(netio)
        print(f"  NetIO parsed: RX={net_rx} bytes, TX={net_tx} bytes")
        print(f"  BlockIO raw: '{blockio}'")
        block_read, block_write = parse_docker_io_string(blockio)
        print(f"  BlockIO parsed: Read={block_read} bytes, Write={block_write} bytes")
        
except subprocess.CalledProcessError as e:
    print(f"Error running docker stats: {e}")
    print(f"stderr: {e.stderr}")
except Exception as e:
    print(f"Unexpected error: {e}")
