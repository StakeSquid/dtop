#!/usr/bin/env python3
"""
Docker TUI - Reliable Async Stats Module for Textual
-----------------------------------------------------
High-performance stats collection with automatic recovery and reconnection.
Optimized for long-running stability with dozens of containers.
"""
import asyncio
import aiohttp
import time
import json
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from enum import Enum

# Configure logging
logger = logging.getLogger(__name__)

# Docker API configuration
DOCKER_SOCKET_PATH = "/var/run/docker.sock"
BASE_URL = "http://localhost"

# Performance and reliability parameters
MAX_CONCURRENT_REQUESTS = 30  # Balance between speed and stability
STATS_UPDATE_INTERVAL = 1.0  # Update every second
HEALTH_CHECK_INTERVAL = 5.0  # Check stream health every 5 seconds
STREAM_REFRESH_INTERVAL = 60.0  # Refresh streams every minute to prevent staleness
CONNECTION_TIMEOUT = 3.0  # Overall connection timeout
READ_TIMEOUT = 2.0  # Read timeout for individual requests
CLEANUP_INTERVAL = 60.0  # Cleanup old data every minute
STALE_DATA_THRESHOLD = 300.0  # Remove data older than 5 minutes
MAX_CONNECTION_POOL = 50  # Connection pool size
RECONNECT_DELAY = 1.0  # Delay before reconnecting failed stream
MAX_RECONNECT_ATTEMPTS = 3  # Max reconnection attempts before falling back


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
    last_update: float = field(default_factory=time.time)
    is_stale: bool = False


@dataclass
class StreamInfo:
    """Information about an active stream."""
    container_id: str
    task: Optional[asyncio.Task] = None
    start_time: float = field(default_factory=time.time)
    last_data_time: float = field(default_factory=time.time)
    reconnect_count: int = 0
    is_healthy: bool = True


class ReliableStatsCollector:
    """Reliable async stats collector with automatic recovery."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.connector: Optional[aiohttp.UnixConnector] = None
        self.stats_cache: Dict[str, ContainerStats] = {}
        self.previous_stats: Dict[str, Dict[str, Any]] = {}
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_cleanup = time.time()
        self.last_health_check = time.time()
        self.active_streams: Dict[str, StreamInfo] = {}
        self.monitored_containers: Set[str] = set()
        self.fallback_mode = False
        self.health_check_task: Optional[asyncio.Task] = None
        
    @asynccontextmanager
    async def connect(self):
        """Context manager for aiohttp session."""
        try:
            # Create Unix socket connector
            self.connector = aiohttp.UnixConnector(
                path=DOCKER_SOCKET_PATH,
                limit=MAX_CONNECTION_POOL,
                limit_per_host=MAX_CONNECTION_POOL,
                force_close=False,
                keepalive_timeout=30
            )
            
            # Configure timeouts
            timeout = aiohttp.ClientTimeout(
                total=CONNECTION_TIMEOUT,
                connect=1.0,
                sock_read=READ_TIMEOUT
            )
            
            # Create session
            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=timeout,
                json_serialize=json.dumps
            )
            
            self.connection_state = ConnectionState.CONNECTED
            
            # Start health check task
            self.health_check_task = asyncio.create_task(self._health_check_loop())
            
            logger.info("Connected to Docker daemon")
            
            yield self
            
        finally:
            await self.close()
    
    async def close(self):
        """Close all connections and cleanup."""
        # Cancel health check
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all active streams
        for stream_info in self.active_streams.values():
            if stream_info.task:
                stream_info.task.cancel()
        
        # Wait for cancellations
        tasks = [s.task for s in self.active_streams.values() if s.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
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
    
    async def collect_stats(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """
        Main entry point for stats collection.
        Manages streams and returns cached stats.
        """
        if not self.session:
            return {}
        
        # Update monitored containers
        self.monitored_containers = set(container_ids)
        
        # Start/stop streams as needed
        await self._manage_streams()
        
        # Perform periodic maintenance
        await self._periodic_maintenance()
        
        # Return current stats
        return self._get_current_stats(container_ids)
    
    async def _manage_streams(self):
        """Start and stop streams based on monitored containers."""
        # Start streams for new containers
        for cid in self.monitored_containers:
            if cid not in self.active_streams:
                await self._start_stream(cid)
        
        # Stop streams for removed containers
        to_remove = []
        for cid, stream_info in self.active_streams.items():
            if cid not in self.monitored_containers:
                if stream_info.task:
                    stream_info.task.cancel()
                to_remove.append(cid)
        
        for cid in to_remove:
            del self.active_streams[cid]
    
    async def _start_stream(self, container_id: str):
        """Start a stats stream for a container."""
        stream_info = StreamInfo(container_id=container_id)
        
        if self.fallback_mode:
            # Use polling in fallback mode
            stream_info.task = asyncio.create_task(
                self._poll_container_stats(container_id)
            )
        else:
            # Use streaming normally
            stream_info.task = asyncio.create_task(
                self._stream_container_stats(container_id)
            )
        
        self.active_streams[container_id] = stream_info
    
    async def _stream_container_stats(self, container_id: str):
        """
        Stream stats for a single container with automatic reconnection.
        """
        stream_info = self.active_streams.get(container_id)
        if not stream_info:
            return
        
        while container_id in self.monitored_containers:
            try:
                await self._stream_stats_once(container_id)
                
                # If stream ended normally, wait before reconnecting
                if container_id in self.monitored_containers:
                    await asyncio.sleep(RECONNECT_DELAY)
                    stream_info.reconnect_count += 1
                    
                    # Switch to polling if too many reconnects
                    if stream_info.reconnect_count > MAX_RECONNECT_ATTEMPTS:
                        logger.debug(f"Switching to polling for {container_id[:12]}")
                        await self._poll_container_stats(container_id)
                        return
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Stream error for {container_id[:12]}: {e}")
                await asyncio.sleep(RECONNECT_DELAY)
    
    async def _stream_stats_once(self, container_id: str):
        """Single streaming session for a container."""
        if not self.session:
            return
        
        url = f"{BASE_URL}/containers/{container_id}/stats?stream=true"
        stream_info = self.active_streams.get(container_id)
        
        try:
            # Use longer timeout for streaming
            timeout = aiohttp.ClientTimeout(total=None, sock_read=10.0)
            
            async with self.session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return
                
                # Read streaming stats
                async for line in response.content:
                    if not line or container_id not in self.monitored_containers:
                        break
                    
                    try:
                        stats_data = json.loads(line)
                        stats = self._parse_stats(container_id, stats_data)
                        
                        # Update cache
                        self.stats_cache[container_id] = stats
                        
                        # Update stream health
                        if stream_info:
                            stream_info.last_data_time = time.time()
                            stream_info.is_healthy = True
                            stream_info.reconnect_count = 0  # Reset on success
                        
                        # Small delay between reads
                        await asyncio.sleep(0.1)
                        
                    except json.JSONDecodeError:
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.debug(f"Error parsing stats: {e}")
                        
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            logger.debug(f"Stream timeout for {container_id[:12]}")
        except Exception as e:
            logger.debug(f"Stream error for {container_id[:12]}: {e}")
    
    async def _poll_container_stats(self, container_id: str):
        """
        Poll stats for a container (fallback mode).
        More reliable but slightly less efficient than streaming.
        """
        while container_id in self.monitored_containers:
            try:
                stats_data = await self._fetch_stats_once(container_id)
                if stats_data:
                    stats = self._parse_stats(container_id, stats_data)
                    self.stats_cache[container_id] = stats
                    
                    # Update stream health
                    stream_info = self.active_streams.get(container_id)
                    if stream_info:
                        stream_info.last_data_time = time.time()
                        stream_info.is_healthy = True
                
                await asyncio.sleep(STATS_UPDATE_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Polling error for {container_id[:12]}: {e}")
                await asyncio.sleep(STATS_UPDATE_INTERVAL)
    
    async def _fetch_stats_once(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Fetch stats once using the streaming endpoint."""
        if not self.session:
            return None
        
        url = f"{BASE_URL}/containers/{container_id}/stats?stream=true"
        
        try:
            # Short timeout for one-shot requests
            timeout = aiohttp.ClientTimeout(total=2.0, sock_read=1.0)
            
            async with self.session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    return None
                
                # Read first line only
                async for line in response.content:
                    if line:
                        try:
                            return json.loads(line)
                        except json.JSONDecodeError:
                            pass
                    break
                    
        except Exception as e:
            logger.debug(f"Failed to fetch stats for {container_id[:12]}: {e}")
        
        return None
    
    async def _health_check_loop(self):
        """Periodic health check for all streams."""
        while True:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                await self._check_stream_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Health check error: {e}")
    
    async def _check_stream_health(self):
        """Check health of all active streams and restart if needed."""
        current_time = time.time()
        stale_threshold = HEALTH_CHECK_INTERVAL * 2
        
        for cid, stream_info in list(self.active_streams.items()):
            if cid not in self.monitored_containers:
                continue
            
            # Check if stream is stale
            if current_time - stream_info.last_data_time > stale_threshold:
                logger.debug(f"Stream stale for {cid[:12]}, restarting...")
                stream_info.is_healthy = False
                
                # Cancel old task
                if stream_info.task:
                    stream_info.task.cancel()
                
                # Restart stream
                await self._start_stream(cid)
            
            # Check if task is still running
            elif stream_info.task and stream_info.task.done():
                # Task ended unexpectedly, restart
                logger.debug(f"Stream task ended for {cid[:12]}, restarting...")
                await self._start_stream(cid)
    
    async def _periodic_maintenance(self):
        """Perform periodic cleanup and maintenance."""
        current_time = time.time()
        
        # Cleanup old data
        if current_time - self.last_cleanup > CLEANUP_INTERVAL:
            await self._cleanup_old_data()
            self.last_cleanup = current_time
        
        # Periodic stream refresh to prevent long-lived connection issues
        if current_time - self.last_health_check > STREAM_REFRESH_INTERVAL:
            await self._refresh_old_streams()
            self.last_health_check = current_time
    
    async def _refresh_old_streams(self):
        """Refresh streams that have been running for too long."""
        current_time = time.time()
        
        for cid, stream_info in list(self.active_streams.items()):
            if cid not in self.monitored_containers:
                continue
            
            # Refresh streams older than the refresh interval
            if current_time - stream_info.start_time > STREAM_REFRESH_INTERVAL:
                logger.debug(f"Refreshing stream for {cid[:12]}")
                
                # Cancel old task
                if stream_info.task:
                    stream_info.task.cancel()
                
                # Start new stream
                await self._start_stream(cid)
    
    async def _cleanup_old_data(self):
        """Remove old data to prevent memory growth."""
        current_time = time.time()
        cutoff_time = current_time - STALE_DATA_THRESHOLD
        
        # Find stale containers
        stale_containers = []
        for cid, stats in self.stats_cache.items():
            if stats.last_update < cutoff_time:
                stale_containers.append(cid)
        
        # Clean up stale data
        for cid in stale_containers:
            self.stats_cache.pop(cid, None)
            self.previous_stats.pop(cid, None)
        
        if stale_containers:
            logger.debug(f"Cleaned up {len(stale_containers)} stale containers")
    
    def _get_current_stats(self, container_ids: List[str]) -> Dict[str, ContainerStats]:
        """Get current stats for specified containers."""
        current_time = time.time()
        result = {}
        
        for cid in container_ids:
            if cid in self.stats_cache:
                stats = self.stats_cache[cid]
                # Mark as stale if too old
                stats.is_stale = (current_time - stats.last_update) > 5.0
                result[cid] = stats
        
        return result
    
    def _parse_stats(self, container_id: str, stats_data: Dict[str, Any]) -> ContainerStats:
        """Parse raw Docker stats into ContainerStats object."""
        current_time = time.time()
        stats = ContainerStats(
            container_id=container_id,
            timestamp=current_time,
            last_update=current_time
        )
        
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
        
        # Calculate rates
        prev = self.previous_stats.get(container_id)
        if prev:
            time_delta = current_time - prev.get("timestamp", current_time)
            if time_delta > 0.5:  # Need at least 0.5s for accurate rates
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
        
        # Store for next calculation
        self.previous_stats[container_id] = {
            "timestamp": current_time,
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


class StatsManager:
    """Manager for coordinating stats collection in Textual app."""
    
    def __init__(self):
        self.collector: Optional[ReliableStatsCollector] = None
        self.collection_task: Optional[asyncio.Task] = None
        self.running = False
        self.container_ids: List[str] = []
        self.update_callback: Optional[callable] = None
        
    async def start(self, update_callback: callable = None):
        """Start stats collection."""
        if self.running:
            return
        
        self.update_callback = update_callback
        self.collector = ReliableStatsCollector()
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
                        # Collect stats
                        stats = await self.collector.collect_stats(self.container_ids)
                        
                        # Notify callback
                        if self.update_callback and stats:
                            await self.update_callback(stats)
                    
                    # Wait for next update
                    await asyncio.sleep(STATS_UPDATE_INTERVAL)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Stats collection error: {e}")
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
                'time': stats.timestamp,
                'is_stale': stats.is_stale
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
                'time': stats.timestamp,
                'is_stale': stats.is_stale
            }
        
        return result