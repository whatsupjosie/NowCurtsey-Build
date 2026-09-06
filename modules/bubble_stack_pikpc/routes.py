from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from .core import AABB, BubbleConfig, Vec3
from .engine import BubbleStackEngine, FrameObject

engine = BubbleStackEngine(BubbleConfig())

def make_app():
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise RuntimeError('Install bubble-stack-foundation[api] to use routes') from exc

    app = FastAPI(title='Bubble Stack PIKPC v1.6')

    @app.post('/api/bubble-stack/frame')
    def ingest_frame(payload: Dict[str, Any]) -> Dict[str, Any]:
        dt = payload.get('dt')
        objects: List[FrameObject] = []
        for item in payload.get('objects', []):
            mn = item['bounds']['min']; mx = item['bounds']['max']
            objects.append(FrameObject(
                object_id=item['object_id'],
                bounds=AABB(Vec3(*mn), Vec3(*mx)),
                semantic_tags=tuple(item.get('semantic_tags', ())),
            ))
        result = engine.step(objects, dt=dt)
        return {
            'time_seconds': result.time_seconds,
            'events': [engine._event_dict(e) for e in result.events],
            'transfer_pulses': [asdict(t) for t in result.transfer_pulses],
            'refined': result.refined,
            'collapsed': result.collapsed,
            'active_bubbles': result.active_bubbles,
        }

    @app.get('/api/bubble-stack/summary')
    def summary() -> Dict[str, Any]:
        return engine.jeremy_room_summary()

    @app.get('/api/bubble-stack/query')
    def query(x: float, y: float, z: float) -> Dict[str, Any]:
        return engine.query_point(Vec3(x, y, z))

    return app

