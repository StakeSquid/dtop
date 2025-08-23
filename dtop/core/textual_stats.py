#!/usr/bin/env python3
"""
Docker TUI - Advanced Async Stats Module for Textual
------------------------------------------------------
High-performance async stats collection for Docker containers with:
- Concurrent stats fetching for dozens of containers
- Intelligent rate limiting and batching
- Graceful error handling and recovery
- Memory-efficient caching and cleanup
"""
import asyncio
import aiohttp
import time
import json
import logging
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
from contextlib import asynccontextmanager
from enum import Enum

# Configure logging
logger = logging.getLogger(__name__)

# Docker API configuration
DOCKER_SOCKET_PATH = "/var/run/docker.sock"
BASE_URL = "http://localhost"

# Performance tuning parameters
MAX_CONCURRENT_REQUESTS = 20  # Max parallel stats requests
BATCH_SIZE = 10  # Containers per batch
STATS_UPDATE_INTERVAL = 1.0  # Seconds between updates
REQUEST_TIMEOUT = 3.0  # Timeout for individual requests
CLEANUP_INTERVAL = 60.0  # Cleanup old data every minute
STALE_DATA_THRESHOLD = 300.0  # Remove data older than 5 minutes
MAX_RETRIES = 2  # Retry failed requests
RETRY_DELAY = 0.5  # Delay between retries


class StatsError(Exception):
    """Base exception for stats collection errors."""
    pass


class ConnectionState(Enum):
    """Docker connection state."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


@dataclass
class ContainerStats:
    """Container statistics data."""
    container_id: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_usage: int = 0
    memory_limit: int = 0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    network_rx_rate: float = 0.0
    network_tx_rate: float = 0.0
    block_read_bytes: int = 0
    block_write_bytes: int = 0
    block_read_rate: float = 0.0
    block_write_rate: float = 0.0
    timestamp: float = field(default_factory=time.time)
    error_count: int = 0
    last_error: Optional[str] = None


@dataclass
class StatsHistory:
    """Historical stats for rate calculations."""
    container_id: str
    previous_stats: Optional[ContainerStats] = None
    current_stats: Optional[ContainerStats] = None
    last_update: float = field(default_factory=time.time)
    
    def calculate_rates(self, new_stats: Dict[str, Any], timestamp: float) -> ContainerStats:
        """Calculate rates from raw stats."""
        stats = ContainerStats(container_id=self.container_id, timestamp=timestamp)
        
        # Parse CPU stats
        stats.cpu_percent = self._parse_cpu_percent(new_stats)
        
        # Parse memory stats
        stats.memory_percent, stats.memory_usage, stats.memory_limit = self._parse_memory_stats(new_stats)
        
        # Parse network stats
        stats.network_rx_bytes, stats.network_tx_bytes = self._parse_network_stats(new_stats)
        
        # Parse block I/O stats
        stats.block_read_bytes, stats.block_write_bytes = self._parse_block_io_stats(new_stats)
        
        # Calculate rates if we have previous data
        if self.current_stats and timestamp > self.last_update:
            time_delta = timestamp - self.last_update
            
            # Network rates
            if stats.network_rx_bytes >= self.current_stats.network_rx_bytes:
                stats.network_rx_rate = (stats.network_rx_bytes - self.current_stats.network_rx_bytes) / time_delta
            
            if stats.network_tx_bytes >= self.current_stats.network_tx_bytes:
                stats.network_tx_rate = (stats.network_tx_bytes - self.current_stats.network_tx_bytes) / time_delta
            
            # Block I/O rates
            if stats.block_read_bytes >= self.current_stats.block_read_bytes:
                stats.block_read_rate = (stats.block_read_bytes - self.current_stats.block_read_bytes) / time_delta
            
            if stats.block_write_bytes >= self.current_stats.block_write_bytes:
                stats.block_write_rate = (stats.block_write_bytes - self.current_stats.block_write_bytes) / time_delta
        
        # Update history
        self.previous_stats = self.current_stats
        self.current_stats = stats
        self.last_update = timestamp
        
        return stats
    
    def _parse_cpu_percent(self, stats: Dict[str, Any]) -> float:
        """Parse CPU percentage from Docker stats."""
        try:
            cpu_stats = stats.get("cpu_stats", {})
            precpu_stats = stats.get("precpu_stats", {})
            
            cpu_delta = (
                cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
                precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            )
            
            system_delta = (
                cpu_stats.get("system_cpu_usage", 0) -
                precpu_stats.get("system_cpu_usage", 0)
            )
            
            if system_delta > 0 and cpu_delta > 0:
                percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
                cpu_count = len(percpu_usage) if percpu_usage else 1
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
                return min(cpu_percent, 100.0)
        except (KeyError, TypeError, ZeroDivisionError):
            pass
        return 0.0
    
    def _parse_memory_stats(self, stats: Dict[str, Any]) -> Tuple[float, int, int]:
        """Parse memory stats from Docker stats."""
        try:
            memory_stats = stats.get("memory_stats", {})
            usage = memory_stats.get("usage", 0)
            limit = memory_stats.get("limit", 0)
            
            if limit > 0:
                cache = memory_stats.get("stats", {}).get("cache", 0)
                actual_usage = usage - cache
                percent = (actual_usage / limit) * 100.0
                return percent, actual_usage, limit
        except (KeyError, TypeError, ZeroDivisionError):
            pass
        return 0.0, 0, 0
    
    def _parse_network_stats(self, stats: Dict[str, Any]) -> Tuple[int, int]:
        """Parse network stats from Docker stats."""
        rx_bytes = 0
        tx_bytes = 0
        
        networks = stats.get("networks", {})
        for interface, data in networks.items():
            rx_bytes += data.get("rx_bytes", 0)
            tx_bytes += data.get("tx_bytes", 0)
        
        return rx_bytes, tx_bytes
    
    def _parse_block_io_stats(self, stats: Dict[str, Any]) -> Tuple[int, int]:
        """Parse block I/O stats from Docker stats."""
        read_bytes = 0
        write_bytes = 0
        
        blkio_stats = stats.get("blkio_stats", {})
        
        # Try different formats
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


class AsyncStatsCollector:
    """Advanced async stats collector for Docker containers."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.connector: Optional[aiohttp.UnixConnector] = None
        self.stats_history: Dict[str, StatsHistory] = {}
        self.stats_cache: Dict[str, ContainerStats] = {}
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_cleanup = time.time()
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.collection_lock = asyncio.Lock()
        self.batch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
    @asynccontextmanager
    async def connect(self):
        """Context manager for aiohttp session."""
        try:
            # Create Unix socket connector with connection pooling
            self.connector = aiohttp.UnixConnector(
                path=DOCKER_SOCKET_PATH,
                limit=MAX_CONCURRENT_REQUESTS * 2,
                limit_per_host=MAX_CONCURRENT_REQUESTS,
                force_close=False,
                keepalive_timeout=30
            )
            
            # Configure timeouts
            timeout = aiohttp.ClientTimeout(
                total=REQUEST_TIMEOUT,
                connect=1.0,
                sock_read=REQUEST_TIMEOUT
            )
            
            # Create session
            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=timeout,
                json_serialize=json.dumps
            )
            
            self.connection_state = ConnectionState.CONNECTED
            logger.info("Connected to Docker daemon")
            
            yield self
            
        finally:
            await self.close()
    
    async def close(self):
        """Close aiohttp session and cleanup."""
        if self.session:
            await self.session.close()
            self.session = None
        
        if self.connector:
            await self.connector.close()
            self.connector = None
        
        self.connection_state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from Docker daemon")
    
    async def collect_stats(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """Collect stats for multiple containers efficiently."""
        if not self.session:
            raise StatsError("Not connected to Docker daemon")
        
        async with self.collection_lock:
            # Perform cleanup if needed
            await self._cleanup_old_data()
            
            # Filter out containers with too many errors
            valid_containers = [
                cid for cid in container_ids
                if self.error_counts[cid] < MAX_RETRIES * 2
            ]
            
            # Process in batches
            results = {}
            for i in range(0, len(valid_containers), BATCH_SIZE):
                batch = valid_containers[i:i + BATCH_SIZE]
                batch_results = await self._collect_batch(batch)
                results.update(batch_results)
            
            # Update cache
            self.stats_cache.update(results)
            
            return results
    
    async def _collect_batch(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """Collect stats for a batch of containers."""
        tasks = []
        for container_id in container_ids:
            task = self._fetch_container_stats_with_retry(container_id)
            tasks.append(task)
        
        # Gather results with exception handling
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        stats_dict = {}
        timestamp = time.time()
        
        for container_id, result in zip(container_ids, results):
            if isinstance(result, Exception):
                # Handle error
                self.error_counts[container_id] += 1
                logger.debug(f"Stats collection error for {container_id[:12]}: {result}")
                
                # Use cached data if available
                if container_id in self.stats_cache:
                    cached = self.stats_cache[container_id]
                    cached.last_error = str(result)
                    cached.error_count = self.error_counts[container_id]
                    stats_dict[container_id] = cached
            elif result:
                # Process successful result
                self.error_counts[container_id] = 0
                
                # Get or create history
                if container_id not in self.stats_history:
                    self.stats_history[container_id] = StatsHistory(container_id)
                
                history = self.stats_history[container_id]
                stats = history.calculate_rates(result, timestamp)
                stats_dict[container_id] = stats
        
        return stats_dict
    
    async def _fetch_container_stats_with_retry(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Fetch stats for a single container with retry logic."""
        async with self.batch_semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    return await self._fetch_container_stats(container_id)
                except asyncio.TimeoutError:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    else:
                        raise
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        raise
        
        return None
    
    async def _fetch_container_stats(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Fetch raw stats for a single container."""
        if not self.session:
            return None
        
        url = f"{BASE_URL}/containers/{container_id}/stats?stream=false"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    # Container not found
                    return None
                else:
                    raise StatsError(f"API error: {response.status}")
        except asyncio.TimeoutError:
            raise
        except Exception as e:
            logger.debug(f"Failed to fetch stats for {container_id[:12]}: {e}")
            raise
    
    async def _cleanup_old_data(self):
        """Remove old data to prevent memory growth."""
        current_time = time.time()
        
        if current_time - self.last_cleanup < CLEANUP_INTERVAL:
            return
        
        self.last_cleanup = current_time
        cutoff_time = current_time - STALE_DATA_THRESHOLD
        
        # Clean up history
        stale_containers = [
            cid for cid, history in self.stats_history.items()
            if history.last_update < cutoff_time
        ]
        
        for cid in stale_containers:
            del self.stats_history[cid]
            self.stats_cache.pop(cid, None)
            self.error_counts.pop(cid, None)
        
        if stale_containers:
            logger.debug(f"Cleaned up stats for {len(stale_containers)} stale containers")
    
    def get_container_stats(self, container_id: str) -> Optional[ContainerStats]:
        """Get cached stats for a container."""
        return self.stats_cache.get(container_id)
    
    def get_all_stats(self) -> Dict[str, ContainerStats]:
        """Get all cached stats."""
        return self.stats_cache.copy()
    
    def clear_container_stats(self, container_id: str):
        """Clear stats for a specific container."""
        self.stats_history.pop(container_id, None)
        self.stats_cache.pop(container_id, None)
        self.error_counts.pop(container_id, None)
    
    def format_stats_for_ui(self, stats: ContainerStats) -> Dict[str, Any]:
        """Format stats for UI display."""
        return {
            'cpu': stats.cpu_percent,
            'mem': stats.memory_percent,
            'mem_usage': stats.memory_usage,
            'mem_limit': stats.memory_limit,
            'net_rx': stats.network_rx_bytes,
            'net_tx': stats.network_tx_bytes,
            'net_in_rate': stats.network_rx_rate,
            'net_out_rate': stats.network_tx_rate,
            'block_read': stats.block_read_bytes,
            'block_write': stats.block_write_bytes,
            'block_read_rate': stats.block_read_rate,
            'block_write_rate': stats.block_write_rate,
            'time': stats.timestamp,
            'error': stats.last_error,
            'error_count': stats.error_count
        }


class StatsManager:
    """Manager for coordinating stats collection in Textual app."""
    
    def __init__(self):
        self.collector: Optional[AsyncStatsCollector] = None
        self.collection_task: Optional[asyncio.Task] = None
        self.running = False
        self.container_ids: Set[str] = set()
        self.update_callback: Optional[callable] = None
        
    async def start(self, update_callback: callable = None):
        """Start stats collection."""
        if self.running:
            return
        
        self.update_callback = update_callback
        self.collector = AsyncStatsCollector()
        self.running = True
        
        # Start collection task
        self.collection_task = asyncio.create_task(self._collection_loop())
        logger.info("Stats collection started")
    
    async def stop(self):
        """Stop stats collection."""
        self.running = False
        
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass
            self.collection_task = None
        
        if self.collector:
            await self.collector.close()
            self.collector = None
        
        logger.info("Stats collection stopped")
    
    async def _collection_loop(self):
        """Main collection loop."""
        async with self.collector.connect():
            while self.running:
                try:
                    if self.container_ids:
                        # Collect stats for all containers
                        stats = await self.collector.collect_stats(list(self.container_ids))
                        
                        # Notify callback if set
                        if self.update_callback:
                            await self.update_callback(stats)
                    
                    # Wait for next update interval
                    await asyncio.sleep(STATS_UPDATE_INTERVAL)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Stats collection error: {e}")
                    await asyncio.sleep(STATS_UPDATE_INTERVAL)
    
    def update_containers(self, container_ids: List[str]):
        """Update the list of containers to monitor."""
        self.container_ids = set(container_ids)
    
    def add_container(self, container_id: str):
        """Add a container to monitor."""
        self.container_ids.add(container_id)
    
    def remove_container(self, container_id: str):
        """Remove a container from monitoring."""
        self.container_ids.discard(container_id)
        if self.collector:
            self.collector.clear_container_stats(container_id)
    
    def get_stats(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get formatted stats for a container."""
        if not self.collector:
            return None
        
        stats = self.collector.get_container_stats(container_id)
        if stats:
            return self.collector.format_stats_for_ui(stats)
        return None
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get all formatted stats."""
        if not self.collector:
            return {}
        
        all_stats = self.collector.get_all_stats()
        return {
            cid: self.collector.format_stats_for_ui(stats)
            for cid, stats in all_stats.items()
        }