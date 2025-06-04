import types
import datetime
import pytest
from dtop.core.docker_tui import DockerTUI

class DummyContainer:
    def __init__(self, id, name, image_tags=None, status='running'):
        self.id = id
        self.name = name
        self.image = types.SimpleNamespace(tags=image_tags or [])
        self.status = status
        self.attrs = {
            'Created': '2024-01-01T00:00:00Z',
            'State': {
                'Running': status == 'running',
                'StartedAt': '2024-01-01T00:00:00Z'
            }
        }

class DummyClient:
    def __init__(self, containers):
        self.containers = types.SimpleNamespace(list=lambda all=True: containers)

@pytest.fixture
def dummy_tui(monkeypatch):
    containers = [
        DummyContainer('1', 'alpha', ['img1'], 'running'),
        DummyContainer('2', 'bravo', ['img2'], 'exited')
    ]
    monkeypatch.setattr('docker.from_env', lambda: DummyClient(containers))
    monkeypatch.setattr('dtop.core.stats.schedule_stats_collection_sync', lambda *a, **k: None)
    return DockerTUI()

def test_fetch_containers(dummy_tui):
    conts = dummy_tui.fetch_containers()
    assert len(conts) == 2
    assert {c.name for c in conts} == {'alpha', 'bravo'}

def test_sort_containers(dummy_tui):
    containers = dummy_tui.fetch_containers()
    dummy_tui.sort_column = 0  # NAME
    sorted_list = dummy_tui.sort_containers(containers)
    assert [c.name for c in sorted_list] == ['alpha', 'bravo']

from dtop.utils.utils import format_bytes, format_datetime

def test_format_bytes():
    assert format_bytes(1024) == '1.0KB'
    assert format_bytes(1048576) == '1.0MB'

def test_format_datetime():
    iso = '2024-05-05T12:34:56Z'
    assert format_datetime(iso) == '2024-05-05 12:34:56'
