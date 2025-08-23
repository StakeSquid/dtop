#!/usr/bin/env python3
"""
Docker TUI - High-Performance Async Stats Module for Textual
-------------------------------------------------------------
Optimized for handling dozens of containers with sub-second updates.
Uses streaming API and parallel processing for maximum performance.
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

# Performance tuning parameters optimized for speed
MAX_CONCURRENT_STREAMS = 50  # High concurrency for many containers
STATS_UPDATE_INTERVAL = 1.0  # Update every second
STREAM_READ_TIMEOUT = 0.5  # Quick timeout for streaming reads
CONNECTION_TIMEOUT = 2.0  # Overall connection timeout
CLEANUP_INTERVAL = 60.0  # Cleanup old data every minute
STALE_DATA_THRESHOLD = 300.0  # Remove data older than 5 minutes
MAX_CONNECTION_POOL = 100  # Large connection pool for parallel requests


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


class FastStatsCollector:
    """Ultra-fast async stats collector using parallel streaming."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.connector: Optional[aiohttp.UnixConnector] = None
        self.stats_cache: Dict[str, ContainerStats] = {}
        self.previous_stats: Dict[str, Dict[str, Any]] = {}
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_cleanup = time.time()
        self.active_streams: Dict[str, asyncio.Task] = {}
        self.stream_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        
    @asynccontextmanager
    async def connect(self):
        """Context manager for aiohttp session with optimized settings."""
        try:
            # Create Unix socket connector with large connection pool
            self.connector = aiohttp.UnixConnector(
                path=DOCKER_SOCKET_PATH,
                limit=MAX_CONNECTION_POOL,
                limit_per_host=MAX_CONNECTION_POOL,
                force_close=False,
                keepalive_timeout=30
            )
            
            # Short timeout for fast failure detection
            timeout = aiohttp.ClientTimeout(
                total=CONNECTION_TIMEOUT,
                connect=0.5,
                sock_read=STREAM_READ_TIMEOUT
            )
            
            # Create session with optimized settings
            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=timeout,
                json_serialize=json.dumps,
                read_bufsize=65536  # Larger buffer for faster reads
            )
            
            self.connection_state = ConnectionState.CONNECTED
            logger.info("Connected to Docker daemon")
            
            yield self
            
        finally:
            await self.close()
    
    async def close(self):
        """Close all connections and cleanup."""
        # Cancel all active streams
        for task in self.active_streams.values():
            task.cancel()
        
        # Wait for cancellations
        if self.active_streams:
            await asyncio.gather(*self.active_streams.values(), return_exceptions=True)
        self.active_streams.clear()
        
        # Close session
        if self.session:
            await self.session.close()
            self.session = None
        
        if self.connector:
            await self.connector.close()
            self.connector = None
        
        self.connection_state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from Docker daemon")
    
    async def collect_all_stats_fast(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """
        Collect stats for all containers in parallel using streaming API.
        This is the fastest method for many containers.
        """
        if not self.session:
            return {}
        
        # Cleanup old data periodically
        await self._cleanup_old_data()
        
        # Start streams for new containers
        new_containers = set(container_ids) - set(self.active_streams.keys())
        for cid in new_containers:
            if cid not in self.active_streams:
                task = asyncio.create_task(self._stream_container_stats(cid))
                self.active_streams[cid] = task
        
        # Stop streams for removed containers
        removed_containers = set(self.active_streams.keys()) - set(container_ids)
        for cid in removed_containers:
            if cid in self.active_streams:
                self.active_streams[cid].cancel()
                del self.active_streams[cid]
        
        # Return current cache
        return {cid: self.stats_cache[cid] for cid in container_ids if cid in self.stats_cache}
    
    async def collect_stats_oneshot(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """
        Collect stats using parallel one-shot requests.
        Faster than sequential but slower than streaming.
        """
        if not self.session:
            return {}
        
        # Create tasks for all containers
        tasks = []
        for cid in container_ids:
            task = asyncio.create_task(self._fetch_stats_oneshot(cid))
            tasks.append((cid, task))
        
        # Wait for all tasks to complete
        results = {}
        for cid, task in tasks:
            try:
                stats_data = await task
                if stats_data:
                    stats = self._parse_stats(cid, stats_data)
                    results[cid] = stats
                    self.stats_cache[cid] = stats
            except Exception as e:
                logger.debug(f"Failed to get stats for {cid[:12]}: {e}")
        
        return results
    
    async def _stream_container_stats(self, container_id: str):
        """
        Stream stats for a single container.
        Reads one stat per second from the streaming endpoint.
        """
        if not self.session:
            return
        
        url = f"{BASE_URL}/containers/{container_id}/stats?stream=true"
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return
                
                # Read streaming stats
                async for line in response.content:
                    if not line:
                        continue
                    
                    try:
                        # Parse JSON stats
                        stats_data = json.loads(line)
                        stats = self._parse_stats(container_id, stats_data)
                        
                        # Update cache
                        self.stats_cache[container_id] = stats
                        
                        # Small delay to prevent CPU spinning
                        await asyncio.sleep(0.1)
                        
                    except json.JSONDecodeError:
                        continue
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.debug(f"Error parsing stats for {container_id[:12]}: {e}")
                        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Stream error for {container_id[:12]}: {e}")
        finally:
            # Remove from active streams
            self.active_streams.pop(container_id, None)
    
    async def _fetch_stats_oneshot(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch stats using one-shot API (faster than stream=false).
        Uses very short timeout to fail fast.
        """
        if not self.session:
            return None
        
        # Use streaming endpoint but read only first response
        url = f"{BASE_URL}/containers/{container_id}/stats?stream=true"
        
        try:
            # Use even shorter timeout for one-shot requests
            timeout = aiohttp.ClientTimeout(total=1.0, sock_read=0.5)
            
            async with self.session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return None
                
                # Read only first line of streaming response
                async for line in response.content:
                    if line:
                        try:
                            return json.loads(line)
                        except json.JSONDecodeError:
                            pass
                    break  # Only read first line
                    
        except asyncio.TimeoutError:
            logger.debug(f"Timeout getting stats for {container_id[:12]}")
        except Exception as e:
            logger.debug(f"Error getting stats for {container_id[:12]}: {e}")
        
        return None
    
    def _parse_stats(self, container_id: str, stats_data: Dict[str, Any]) -> ContainerStats:
        """Parse raw Docker stats into ContainerStats object."""
        stats = ContainerStats(container_id=container_id)
        
        # Parse CPU
        stats.cpu_percent = self._calculate_cpu_percent(stats_data)
        
        # Parse Memory
        memory_stats = stats_data.get("memory_stats", {})
        usage = memory_stats.get("usage", 0)
        limit = memory_stats.get("limit", 0)
        
        if limit > 0:
            cache = memory_stats.get("stats", {}).get("cache", 0)
            actual_usage = usage - cache
            stats.memory_usage = actual_usage
            stats.memory_limit = limit
            stats.memory_percent = (actual_usage / limit) * 100.0
        
        # Parse Network
        networks = stats_data.get("networks", {})
        for interface, data in networks.items():
            stats.network_rx_bytes += data.get("rx_bytes", 0)
            stats.network_tx_bytes += data.get("tx_bytes", 0)
        
        # Parse Block I/O
        blkio_stats = stats_data.get("blkio_stats", {})
        io_stats = (
            blkio_stats.get("io_service_bytes_recursive") or
            blkio_stats.get("io_service_bytes") or
            []
        )
        
        for entry in io_stats:
            op = entry.get("op", "").lower()
            value = entry.get("value", 0)
            
            if op == "read":
                stats.block_read_bytes += value
            elif op == "write":
                stats.block_write_bytes += value
        
        # Calculate rates if we have previous data
        prev = self.previous_stats.get(container_id)
        if prev:
            time_delta = stats.timestamp - prev.get("timestamp", stats.timestamp)
            if time_delta > 0:
                # Network rates
                prev_rx = prev.get("rx_bytes", 0)
                prev_tx = prev.get("tx_bytes", 0)
                if stats.network_rx_bytes >= prev_rx:
                    stats.network_rx_rate = (stats.network_rx_bytes - prev_rx) / time_delta
                if stats.network_tx_bytes >= prev_tx:
                    stats.network_tx_rate = (stats.network_tx_bytes - prev_tx) / time_delta
                
                # Block I/O rates
                prev_read = prev.get("read_bytes", 0)
                prev_write = prev.get("write_bytes", 0)
                if stats.block_read_bytes >= prev_read:
                    stats.block_read_rate = (stats.block_read_bytes - prev_read) / time_delta
                if stats.block_write_bytes >= prev_write:
                    stats.block_write_rate = (stats.block_write_bytes - prev_write) / time_delta
        
        # Store current values for next calculation
        self.previous_stats[container_id] = {
            "timestamp": stats.timestamp,
            "rx_bytes": stats.network_rx_bytes,
            "tx_bytes": stats.network_tx_bytes,
            "read_bytes": stats.block_read_bytes,
            "write_bytes": stats.block_write_bytes
        }
        
        return stats
    
    def _calculate_cpu_percent(self, stats: Dict[str, Any]) -> float:
        """Calculate CPU percentage from Docker stats."""
        try:
            cpu_stats = stats.get("cpu_stats", {})
            precpu_stats = stats.get("precpu_stats", {})
            
            # CPU usage delta
            cpu_delta = (
                cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
                precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            )
            
            # System CPU usage delta
            system_delta = (
                cpu_stats.get("system_cpu_usage", 0) -
                precpu_stats.get("system_cpu_usage", 0)
            )
            
            if system_delta > 0 and cpu_delta > 0:
                # Number of CPU cores
                online_cpus = cpu_stats.get("online_cpus")
                if online_cpus is None:
                    percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
                    online_cpus = len(percpu_usage) if percpu_usage else 1
                
                # Calculate percentage
                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                return min(cpu_percent, 100.0 * online_cpus)
        except (KeyError, TypeError, ZeroDivisionError):
            pass
        
        return 0.0
    
    async def _cleanup_old_data(self):
        """Remove old data to prevent memory growth."""
        current_time = time.time()
        
        if current_time - self.last_cleanup < CLEANUP_INTERVAL:
            return
        
        self.last_cleanup = current_time
        cutoff_time = current_time - STALE_DATA_THRESHOLD
        
        # Find stale containers
        stale_containers = []
        for cid, stats in self.stats_cache.items():
            if stats.timestamp < cutoff_time:
                stale_containers.append(cid)
        
        # Clean up stale data
        for cid in stale_containers:
            self.stats_cache.pop(cid, None)
            self.previous_stats.pop(cid, None)
            
            # Cancel stream if active
            if cid in self.active_streams:
                self.active_streams[cid].cancel()
                del self.active_streams[cid]
        
        if stale_containers:
            logger.debug(f"Cleaned up {len(stale_containers)} stale containers")


class StatsManager:
    """Manager for coordinating stats collection in Textual app."""
    
    def __init__(self):
        self.collector: Optional[FastStatsCollector] = None
        self.collection_task: Optional[asyncio.Task] = None
        self.running = False
        self.container_ids: List[str] = []
        self.update_callback: Optional[callable] = None
        self.use_streaming = True  # Use streaming for best performance
        
    async def start(self, update_callback: callable = None):
        """Start stats collection."""
        if self.running:
            return
        
        self.update_callback = update_callback
        self.collector = FastStatsCollector()
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
        """Main collection loop with optimized performance."""
        async with self.collector.connect():
            # Initial fast collection using one-shot
            if self.container_ids:
                initial_stats = await self.collector.collect_stats_oneshot(self.container_ids)
                if self.update_callback and initial_stats:
                    await self.update_callback(initial_stats)
            
            while self.running:
                try:
                    if self.container_ids:
                        if self.use_streaming:
                            # Use streaming for continuous updates (most efficient)
                            stats = await self.collector.collect_all_stats_fast(self.container_ids)
                        else:
                            # Use parallel one-shot requests (fallback)
                            stats = await self.collector.collect_stats_oneshot(self.container_ids)
                        
                        # Notify callback if set
                        if self.update_callback and stats:
                            await self.update_callback(stats)
                    
                    # Short sleep for responsive updates
                    await asyncio.sleep(STATS_UPDATE_INTERVAL)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Stats collection error: {e}")
                    # Try switching methods on error
                    self.use_streaming = not self.use_streaming
                    await asyncio.sleep(STATS_UPDATE_INTERVAL)
    
    def update_containers(self, container_ids: List[str]):
        """Update the list of containers to monitor."""
        self.container_ids = container_ids
    
    def add_container(self, container_id: str):
        """Add a container to monitor."""
        if container_id not in self.container_ids:
            self.container_ids.append(container_id)
    
    def remove_container(self, container_id: str):
        """Remove a container from monitoring."""
        if container_id in self.container_ids:
            self.container_ids.remove(container_id)
    
    def get_stats(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get formatted stats for a container."""
        if not self.collector:
            return None
        
        stats = self.collector.stats_cache.get(container_id)
        if stats:
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
                'time': stats.timestamp
            }
        return None
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get all formatted stats."""
        if not self.collector:
            return {}
        
        result = {}
        for cid, stats in self.collector.stats_cache.items():
            result[cid] = {
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
                'time': stats.timestamp
            }
        
        return result