#!/usr/bin/env python3
"""
Docker TUI - Async Stats Module
-----------
Handles container stats collection using async HTTP calls to Docker API.
Based on direct Docker API access for better performance.
"""
import asyncio
import time
import json
import sys
import os
import threading
from typing import Dict, Tuple, List, Optional
from collections import defaultdict

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("Warning: aiohttp not installed. Stats collection will be limited.", file=sys.stderr)
    print("Install with: pip install aiohttp", file=sys.stderr)

DOCKER_SOCKET_PATH = "/var/run/docker.sock"
BASE_URL = "http://localhost"  # hostname is ignored when using UnixConnector


def parse_blkio_stats(stats: dict) -> Tuple[int, int]:
    """
    Parse block I/O statistics from Docker stats.
    Returns (read_bytes, write_bytes).
    
    Handles both newer io_service_bytes_recursive and legacy formats.
    """
    read_bytes = 0
    write_bytes = 0
    
    blkio_stats = stats.get("blkio_stats", {})
    
    # Try newer format first, fall back to legacy
    io_stats = (
        blkio_stats.get("io_service_bytes_recursive") or
        blkio_stats.get("io_service_bytes") or
        []
    )
    
    for entry in io_stats:
        op = entry.get("op", "").lower()
        value = entry.get("value", 0)
        
        if op == "read":
            read_bytes += value
        elif op == "write":
            write_bytes += value
    
    return read_bytes, write_bytes


def parse_network_stats(stats: dict) -> Tuple[int, int]:
    """
    Parse network statistics from Docker stats.
    Returns (rx_bytes, tx_bytes).
    """
    rx_bytes = 0
    tx_bytes = 0
    
    networks = stats.get("networks", {})
    for interface, data in networks.items():
        rx_bytes += data.get("rx_bytes", 0)
        tx_bytes += data.get("tx_bytes", 0)
    
    return rx_bytes, tx_bytes


def parse_cpu_stats(stats: dict) -> float:
    """
    Parse CPU percentage from Docker stats.
    Returns CPU percentage (0-100).
    """
    try:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        
        # Calculate CPU delta
        cpu_delta = (
            cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
            precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        )
        
        # Calculate system delta
        system_delta = (
            cpu_stats.get("system_cpu_usage", 0) -
            precpu_stats.get("system_cpu_usage", 0)
        )
        
        if system_delta > 0 and cpu_delta > 0:
            # Get number of CPUs
            percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
            cpu_count = len(percpu_usage) if percpu_usage else 1
            
            # Calculate percentage
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
            return min(cpu_percent, 100.0)  # Cap at 100%
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    
    return 0.0


def parse_memory_stats(stats: dict) -> float:
    """
    Parse memory percentage from Docker stats.
    Returns memory percentage (0-100).
    """
    try:
        memory_stats = stats.get("memory_stats", {})
        usage = memory_stats.get("usage", 0)
        limit = memory_stats.get("limit", 0)
        
        if limit > 0:
            # Account for cache if available
            cache = memory_stats.get("stats", {}).get("cache", 0)
            actual_usage = usage - cache
            return (actual_usage / limit) * 100.0
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    
    return 0.0


class AsyncStatsCollector:
    """Async stats collector using aiohttp to query Docker API directly."""
    
    def __init__(self, tui):
        self.tui = tui
        self.session: Optional['aiohttp.ClientSession'] = None
        self.previous_stats: Dict[str, dict] = {}
        self.previous_timestamp: Dict[str, float] = {}
        # ADDED: Track last cleanup time
        self.last_cleanup_time = time.time()
        self.cleanup_interval = 300  # Clean up every 5 minutes
        
    async def __aenter__(self):
        """Create aiohttp session with Unix socket connector."""
        if not AIOHTTP_AVAILABLE:
            return self
            
        # ADDED: Connection limits to prevent resource exhaustion
        connector = aiohttp.UnixConnector(
            path=DOCKER_SOCKET_PATH,
            limit=150,  # Increased for high container count
            limit_per_host=100  # Increased for high container count
        )
        timeout = aiohttp.ClientTimeout(total=5.0)  # 5 second timeout
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            
    async def cleanup_old_entries(self):
        """Remove entries for containers that haven't been seen recently"""
        current_time = time.time()
        if current_time - self.last_cleanup_time < self.cleanup_interval:
            return
            
        # Remove entries older than 10 minutes
        cutoff_time = current_time - 600
        
        stale_ids = [
            cid for cid, timestamp in self.previous_timestamp.items()
            if timestamp < cutoff_time
        ]
        
        for stale_id in stale_ids:
            self.previous_stats.pop(stale_id, None)
            self.previous_timestamp.pop(stale_id, None)
            
        self.last_cleanup_time = current_time
            
    async def get_running_containers(self) -> List[dict]:
        """Get list of running containers from Docker API."""
        if not self.session:
            return []
            
        try:
            filters = json.dumps({"status": ["running"]})
            url = f"{BASE_URL}/containers/json?filters={filters}"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
            
        return []
        
    async def fetch_container_stats(self, container_id: str) -> Optional[dict]:
        """Fetch stats for a single container."""
        if not self.session:
            return None
            
        try:
            url = f"{BASE_URL}/containers/{container_id}/stats?stream=false"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
            
        return None
        
    async def collect_all_stats(self, containers: List) -> None:
        """Collect stats for all containers in parallel."""
        # ADDED: Periodic cleanup
        await self.cleanup_old_entries()
        
        # Filter running containers
        running_containers = [c for c in containers if c.status == 'running']
        
        if not running_containers:
            return
            
        # Fetch stats for all containers in parallel
        tasks = [self.fetch_container_stats(c.id) for c in running_containers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        current_time = time.time()
        
        # Process results
        for container, result in zip(running_containers, results):
            if isinstance(result, Exception) or result is None:
                continue
                
            container_id = container.id
            
            # Parse stats
            cpu_percent = parse_cpu_stats(result)
            mem_percent = parse_memory_stats(result)
            read_bytes, write_bytes = parse_blkio_stats(result)
            rx_bytes, tx_bytes = parse_network_stats(result)
            
            # Calculate rates if we have previous data
            prev_stats = self.previous_stats.get(container_id, {})
            prev_time = self.previous_timestamp.get(container_id, current_time)
            time_delta = current_time - prev_time
            
            # Initialize rates
            read_rate = write_rate = rx_rate = tx_rate = 0.0
            
            if time_delta > 0.5 and prev_stats:  # At least 0.5 seconds
                # Calculate byte rates
                prev_read = prev_stats.get('read_bytes', read_bytes)
                prev_write = prev_stats.get('write_bytes', write_bytes)
                prev_rx = prev_stats.get('rx_bytes', rx_bytes)
                prev_tx = prev_stats.get('tx_bytes', tx_bytes)
                
                # Only calculate positive rates (handle counter resets)
                if read_bytes >= prev_read:
                    read_rate = (read_bytes - prev_read) / time_delta
                if write_bytes >= prev_write:
                    write_rate = (write_bytes - prev_write) / time_delta
                if rx_bytes >= prev_rx:
                    rx_rate = (rx_bytes - prev_rx) / time_delta
                if tx_bytes >= prev_tx:
                    tx_rate = (tx_bytes - prev_tx) / time_delta
            elif prev_stats:
                # Keep previous rates if time delta is too small
                read_rate = prev_stats.get('block_read_rate', 0)
                write_rate = prev_stats.get('block_write_rate', 0)
                rx_rate = prev_stats.get('net_in_rate', 0)
                tx_rate = prev_stats.get('net_out_rate', 0)
            
            # Update cache
            with self.tui.stats_lock:
                self.tui.stats_cache[container_id] = {
                    'cpu': cpu_percent,
                    'mem': mem_percent,
                    'net_rx': rx_bytes,
                    'net_tx': tx_bytes,
                    'net_in_rate': rx_rate,
                    'net_out_rate': tx_rate,
                    'block_read': read_bytes,
                    'block_write': write_bytes,
                    'block_read_rate': read_rate,
                    'block_write_rate': write_rate,
                    'time': current_time
                }
            
            # Store current stats for next iteration
            self.previous_stats[container_id] = {
                'read_bytes': read_bytes,
                'write_bytes': write_bytes,
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
                'block_read_rate': read_rate,
                'block_write_rate': write_rate,
                'net_in_rate': rx_rate,
                'net_out_rate': tx_rate
            }
            self.previous_timestamp[container_id] = current_time
            
        # Clean up stats for containers that are no longer running
        current_ids = {c.id for c in containers if c.status == 'running'}
        stale_ids = set(self.previous_stats.keys()) - current_ids
        
        for stale_id in stale_ids:
            self.previous_stats.pop(stale_id, None)
            self.previous_timestamp.pop(stale_id, None)
            
            # Zero out rates for stopped containers
            with self.tui.stats_lock:
                if stale_id in self.tui.stats_cache:
                    self.tui.stats_cache[stale_id].update({
                        'net_in_rate': 0,
                        'net_out_rate': 0,
                        'block_read_rate': 0,
                        'block_write_rate': 0,
                        'cpu': 0,
                        'mem': 0
                    })


# Global stats collector instance and lock
_stats_collector: Optional[AsyncStatsCollector] = None
_stats_loop: Optional[asyncio.AbstractEventLoop] = None
_stats_thread: Optional[threading.Thread] = None
_stats_lock = threading.Lock()
_stats_initialized = False


async def initialize_stats_collector(tui):
    """Initialize the global stats collector."""
    global _stats_collector
    if _stats_collector is None:
        _stats_collector = AsyncStatsCollector(tui)
        await _stats_collector.__aenter__()
    return _stats_collector


async def cleanup_stats_collector():
    """Clean up the global stats collector."""
    global _stats_collector
    if _stats_collector:
        await _stats_collector.__aexit__(None, None, None)
        _stats_collector = None


async def schedule_stats_collection(tui, containers):
    """Schedule async stats collection for containers."""
    global _stats_collector
    
    if not _stats_collector:
        _stats_collector = await initialize_stats_collector(tui)
    
    try:
        await _stats_collector.collect_all_stats(containers)
    except Exception as e:
        # Only log error if it's not a shutdown-related error
        if "cancelled" not in str(e).lower() and "closed" not in str(e).lower() and str(e).strip():
            print(f"Stats collection error: {e}", file=sys.stderr)
            # Only print traceback in debug mode
            if os.environ.get('DEBUG'):
                import traceback
                print(traceback.format_exc(), file=sys.stderr)


def _run_stats_loop():
    """Run the stats event loop in a dedicated thread."""
    global _stats_loop
    try:
        asyncio.set_event_loop(_stats_loop)
        _stats_loop.run_forever()
    except Exception as e:
        print(f"Stats loop error: {e}", file=sys.stderr)
    finally:
        # Clean up the loop
        _stats_loop.close()


def _ensure_stats_loop():
    """Ensure the stats event loop is running."""
    global _stats_loop, _stats_thread, _stats_initialized
    
    with _stats_lock:
        # Check if already initialized
        if _stats_initialized and _stats_thread and _stats_thread.is_alive():
            return
        
        # Create new event loop
        _stats_loop = asyncio.new_event_loop()
        
        # Start the loop in a daemon thread
        _stats_thread = threading.Thread(target=_run_stats_loop, daemon=True)
        _stats_thread.start()
        
        # Mark as initialized
        _stats_initialized = True
        
        # Give the loop a moment to start
        time.sleep(0.1)


# Compatibility wrapper for the existing synchronous interface
def schedule_stats_collection_sync(tui, containers):
    """Synchronous wrapper for backward compatibility."""
    if not AIOHTTP_AVAILABLE:
        # Fall back to docker-py stats if aiohttp not available
        for container in containers:
            if container.status != 'running':
                continue
            try:
                stats = container.stats(stream=False)
                
                # Parse basic stats
                cpu_percent = parse_cpu_stats(stats)
                mem_percent = parse_memory_stats(stats)
                read_bytes, write_bytes = parse_blkio_stats(stats)
                rx_bytes, tx_bytes = parse_network_stats(stats)
                
                # Simple rate calculation (no previous values)
                with tui.stats_lock:
                    tui.stats_cache[container.id] = {
                        'cpu': cpu_percent,
                        'mem': mem_percent,
                        'net_rx': rx_bytes,
                        'net_tx': tx_bytes,
                        'net_in_rate': 0,  # Can't calculate without history
                        'net_out_rate': 0,
                        'block_read': read_bytes,
                        'block_write': write_bytes,
                        'block_read_rate': 0,
                        'block_write_rate': 0,
                        'time': time.time()
                    }
            except Exception:
                pass
        return
    
    global _stats_loop, _stats_collector
    
    try:
        # Ensure the stats event loop is running
        _ensure_stats_loop()
        
        # Initialize collector if needed
        if _stats_loop and not _stats_collector:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    initialize_stats_collector(tui), 
                    _stats_loop
                )
                future.result(timeout=5.0)
            except Exception as e:
                print(f"Failed to initialize stats collector: {e}", file=sys.stderr)
                return
        
        # Schedule the stats collection in the dedicated loop
        if _stats_loop:
            future = asyncio.run_coroutine_threadsafe(
                schedule_stats_collection(tui, containers), 
                _stats_loop
            )
            # Wait for completion with timeout
            future.result(timeout=10.0)
    except Exception as e:
        # Only log error if it's not a cancellation during shutdown
        if "cancelled" not in str(e).lower() and "closed" not in str(e).lower() and str(e).strip():
            import traceback
            print(f"Stats collection sync error: {e}", file=sys.stderr)
            # Only print traceback in debug mode
            if os.environ.get('DEBUG'):
                print(traceback.format_exc(), file=sys.stderr)


def cleanup_stats_sync():
    """Clean up the stats event loop and collector."""
    global _stats_loop, _stats_thread, _stats_collector, _stats_initialized
    
    with _stats_lock:
        if _stats_loop:
            # Clean up the collector first
            if _stats_collector:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        cleanup_stats_collector(), 
                        _stats_loop
                    )
                    future.result(timeout=5.0)
                except Exception as e:
                    print(f"Error cleaning up stats collector: {e}", file=sys.stderr)
            
            # Stop the event loop
            _stats_loop.call_soon_threadsafe(_stats_loop.stop)
            
            # Wait for thread to finish
            if _stats_thread and _stats_thread.is_alive():
                _stats_thread.join(timeout=2.0)
            
            # Reset state
            _stats_loop = None
            _stats_thread = None
            _stats_collector = None
            _stats_initialized = False
