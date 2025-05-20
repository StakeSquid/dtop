#!/usr/bin/env python3
"""
Docker TUI - Stats Module
-----------
Handles container stats collection and processing.
"""
import time

def schedule_stats_collection(tui, containers):
    """Schedule stats collection for multiple containers in parallel"""
    if not containers:
        return
        
    # Submit jobs to thread pool
    futures = []
    for container in containers:
        future = tui.executor.submit(fetch_container_stats, tui, container)
        futures.append(future)

def fetch_container_stats(tui, container):
    """Fetch stats for a single container"""
    try:
        # Get stats without streaming
        stats = container.stats(stream=False)
        
        # Process CPU stats
        try:
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                          stats['precpu_stats']['system_cpu_usage']
            
            cpu_percent = 0.0
            if system_delta > 0 and cpu_delta > 0:
                # Calculate CPU percent using the same formula Docker uses
                cpu_count = len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', [1]))
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
        except (KeyError, TypeError):
            cpu_percent = 0.0
        
        # Process memory stats
        try:
            mem_percent = 0.0
            if 'memory_stats' in stats and 'usage' in stats['memory_stats'] and 'limit' in stats['memory_stats']:
                mem_usage = stats['memory_stats']['usage']
                mem_limit = stats['memory_stats']['limit']
                mem_percent = (mem_usage / mem_limit) * 100.0
        except (KeyError, TypeError, ZeroDivisionError):
            mem_percent = 0.0
        
        # Process network stats
        net_in = 0
        net_out = 0
        if 'networks' in stats:
            for interface in stats['networks'].values():
                net_in += interface['rx_bytes']
                net_out += interface['tx_bytes']
        
        # Cache stats with timestamp
        with tui.stats_lock:
            # Store previous network values for rate calculation
            prev_stats = tui.stats_cache[container.id]
            prev_time = prev_stats.get('time', time.time())
            prev_net_in = prev_stats.get('net_in', net_in)
            prev_net_out = prev_stats.get('net_out', net_out)
            
            # Calculate network rate
            time_diff = time.time() - prev_time
            if time_diff > 0:
                net_in_rate = (net_in - prev_net_in) / time_diff
                net_out_rate = (net_out - prev_net_out) / time_diff
            else:
                net_in_rate = 0
                net_out_rate = 0
            
            # Store current values
            tui.stats_cache[container.id] = {
                'cpu': cpu_percent,
                'mem': mem_percent,
                'net_in': net_in,
                'net_out': net_out,
                'net_in_rate': net_in_rate,
                'net_out_rate': net_out_rate,
                'time': time.time()
            }
    except Exception:
        # Ignore errors for individual containers
        pass
