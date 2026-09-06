"""
modules/timeline.py — Deterministic Timeline Sequencer
══════════════════════════════════════════════════════
Rear View Foresight LLC — Feic Mo Chroí — 2026-03-25
"""
from __future__ import annotations
import asyncio, json, logging, time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException, Request
from modules.route_security import require_role

logger = logging.getLogger("pubcast.timeline")

class TimelineState(str, Enum):
    IDLE="idle"; RUNNING="running"; PAUSED="paused"; COMPLETE="complete"; FAILED="failed"

class EventType(str, Enum):
    CAMERA="camera"; ENTRANCE="entrance"; ENVIRONMENT="environment"; WALK="walk"
    RECORD="record"; AUDIO="audio"; LIGHTING="lighting"; CHAT="chat"
    CUSTOM="custom"; SEQUENCE_END="sequence_end"

@dataclass
class TimelineEvent:
    t: float; event_type: EventType; params: Dict[str,Any]=field(default_factory=dict)
    label: str=""; critical: bool=False; fired: bool=False
    fired_at: Optional[float]=None; error: Optional[str]=None
    def to_dict(self):
        return {"t":self.t,"type":self.event_type.value,"params":self.params,
                "label":self.label,"critical":self.critical}
    @classmethod
    def from_dict(cls, d):
        return cls(t=d["t"],event_type=EventType(d.get("type","custom")),
                   params=d.get("params",{}),label=d.get("label",""),critical=d.get("critical",False))

@dataclass
class TimelineDefinition:
    name: str; description: str=""; duration: float=60.0
    events: List[TimelineEvent]=field(default_factory=list); loop: bool=False; version: str="1.0"
    def validate(self):
        issues=[]
        if not self.events: issues.append("No events")
        for i,e in enumerate(self.events):
            if e.t<0: issues.append(f"Event {i} negative time")
            if e.t>self.duration: issues.append(f"Event {i} exceeds duration")
        return issues
    def to_dict(self):
        return {"name":self.name,"description":self.description,"duration":self.duration,
                "events":[e.to_dict() for e in self.events],"loop":self.loop,"version":self.version}
    @classmethod
    def from_dict(cls, d):
        return cls(name=d["name"],description=d.get("description",""),duration=d.get("duration",60),
                   events=[TimelineEvent.from_dict(e) for e in d.get("events",[])],
                   loop=d.get("loop",False),version=d.get("version","1.0"))
    def save(self, path: Path):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(self.to_dict(),indent=2))
    @classmethod
    def load(cls, path: Path): return cls.from_dict(json.loads(path.read_text()))

class TimelinePlayer:
    def __init__(self, tick_rate=1/60):
        self._timeline: Optional[TimelineDefinition]=None; self._state=TimelineState.IDLE
        self._start_time=0.0; self._pause_offset=0.0; self._pause_time=0.0
        self._tick_rate=tick_rate; self._handlers: Dict[EventType,List[Callable]]={}
        self._on_complete: List[Callable]=[]; self._on_error: List[Callable]=[]
        self._task: Optional[asyncio.Task]=None; self._log: List[Dict]=[]
    @property
    def state(self): return self._state
    @property
    def elapsed(self):
        if self._state==TimelineState.RUNNING: return time.time()-self._start_time-self._pause_offset
        elif self._state==TimelineState.PAUSED: return self._pause_time-self._start_time-self._pause_offset
        return 0
    @property
    def progress(self):
        return min(1.0,self.elapsed/self._timeline.duration) if self._timeline else 0
    def register_handler(self,et,handler): self._handlers.setdefault(et,[]).append(handler)
    def on_complete(self,cb): self._on_complete.append(cb)
    def on_error(self,cb): self._on_error.append(cb)
    def load_timeline(self,td):
        issues=td.validate()
        if not issues: self._timeline=td; self._reset(); self._state=TimelineState.IDLE; self._log=[]
        return issues
    async def start(self):
        if not self._timeline or self._state==TimelineState.RUNNING: return False
        self._reset(); self._state=TimelineState.RUNNING; self._start_time=time.time(); self._pause_offset=0; self._log=[]
        self._task=asyncio.create_task(self._run()); return True
    async def stop(self):
        self._state=TimelineState.IDLE
        if self._task: self._task.cancel(); self._task=None
    async def pause(self):
        if self._state==TimelineState.RUNNING: self._state=TimelineState.PAUSED; self._pause_time=time.time()
    async def resume(self):
        if self._state==TimelineState.PAUSED: self._pause_offset+=time.time()-self._pause_time; self._state=TimelineState.RUNNING
    def status(self):
        return {"state":self._state.value,"timeline":self._timeline.name if self._timeline else None,
                "elapsed":round(self.elapsed,2),"progress":round(self.progress,3),
                "duration":self._timeline.duration if self._timeline else 0,
                "events_fired":sum(1 for e in (self._timeline.events if self._timeline else []) if e.fired),
                "events_failed":sum(1 for e in (self._timeline.events if self._timeline else []) if e.error)}
    def get_log(self): return list(self._log)
    async def _run(self):
        try:
            while self._state in (TimelineState.RUNNING,TimelineState.PAUSED):
                if self._state==TimelineState.PAUSED: await asyncio.sleep(0.1); continue
                el=self.elapsed
                for ev in self._timeline.events:
                    if not ev.fired and el>=ev.t: await self._fire(ev,el)
                if el>=self._timeline.duration:
                    if self._timeline.loop: self._reset(); self._start_time=time.time(); self._pause_offset=0
                    else:
                        self._state=TimelineState.COMPLETE
                        for cb in self._on_complete:
                            try:
                                if asyncio.iscoroutinefunction(cb): await cb()
                                else: cb()
                            except Exception as exc:
                                logger.warning("Timeline completion callback failed: %s", exc)
                        break
                await asyncio.sleep(self._tick_rate)
        except asyncio.CancelledError:
            logger.debug("Timeline task cancelled")
        except Exception as exc:
            self._state=TimelineState.FAILED; logger.exception("Timeline failed: %s",exc)
    async def _fire(self,ev,elapsed):
        ev.fired=True; ev.fired_at=elapsed
        entry={"t":ev.t,"fired_at":elapsed,"drift":round(elapsed-ev.t,4),"type":ev.event_type.value,"label":ev.label,"success":True}
        specific = self._handlers.get(ev.event_type, [])
        custom = [h for h in self._handlers.get(EventType.CUSTOM, []) if h not in specific]
        for handler in specific + custom:
            try:
                r=await handler(ev) if asyncio.iscoroutinefunction(handler) else handler(ev)
                if r is False: raise RuntimeError(f"Handler returned False for {ev.label}")
            except Exception as exc:
                ev.error=str(exc); entry["success"]=False; entry["error"]=str(exc)
                if ev.critical: self._state=TimelineState.FAILED; return
                break
        self._log.append(entry)

    def scene_state(self) -> Dict[str, Any]:
        """Return current scene state so a late-joining client can catch up."""
        if not self._timeline or self._state != TimelineState.RUNNING:
            return {"active": False}
        elapsed = self.elapsed
        fired_events = [
            {"t": e.t, "type": e.event_type.value, "params": e.params, "label": e.label}
            for e in self._timeline.events if e.fired
        ]
        return {
            "active": True,
            "timeline": self._timeline.name,
            "elapsed": round(elapsed, 2),
            "progress": round(self.progress, 3),
            "fired_events": fired_events,
        }

    def _reset(self):
        if self._timeline:
            for e in self._timeline.events: e.fired=False; e.fired_at=None; e.error=None

# Built-in timelines
CAST_SYNC_60=TimelineDefinition(name="cast_sync_60",description="60-second opening",duration=62,events=[
    TimelineEvent(t=0,event_type=EventType.ENVIRONMENT,params={"ambient":0.08,"key":0.2},label="Dark stage"),
    TimelineEvent(t=0,event_type=EventType.CAMERA,params={"cam":"wide","duration":0},label="Wide",critical=True),
    TimelineEvent(t=0,event_type=EventType.RECORD,params={"action":"start"},label="Rec start"),
    TimelineEvent(t=5,event_type=EventType.ENTRANCE,params={"index":0,"duration":3},label="Host enters"),
    TimelineEvent(t=5,event_type=EventType.ENVIRONMENT,params={"ambient":0.15,"key":0.5},label="Lights 1"),
    TimelineEvent(t=10,event_type=EventType.CAMERA,params={"cam":"medium","duration":2.5},label="Medium"),
    TimelineEvent(t=12,event_type=EventType.ENTRANCE,params={"index":1,"duration":3},label="Pete enters"),
    TimelineEvent(t=12,event_type=EventType.ENVIRONMENT,params={"ambient":0.25,"key":0.8},label="Lights 2"),
    TimelineEvent(t=18,event_type=EventType.ENTRANCE,params={"index":2,"duration":3},label="Purfluous enters"),
    TimelineEvent(t=22,event_type=EventType.CAMERA,params={"cam":"wide","duration":3},label="Wide pull"),
    TimelineEvent(t=25,event_type=EventType.ENVIRONMENT,params={"ambient":0.4,"key":1.5},label="Full lights"),
    TimelineEvent(t=30,event_type=EventType.WALK,params={"duration":4},label="Walk to seats"),
    TimelineEvent(t=35,event_type=EventType.CAMERA,params={"cam":"close","duration":2},label="Close-up"),
    TimelineEvent(t=40,event_type=EventType.CAMERA,params={"cam":"wide","duration":2},label="Wide hold"),
    TimelineEvent(t=45,event_type=EventType.ENVIRONMENT,params={"ambient":0.45,"key":1.6},label="Final ambience"),
    TimelineEvent(t=55,event_type=EventType.CAMERA,params={"cam":"medium","duration":3},label="Medium lock"),
    TimelineEvent(t=60,event_type=EventType.SEQUENCE_END,params={},label="Complete"),
])
INTERVIEW_SETUP=TimelineDefinition(name="interview_setup",description="Interview transition",duration=10,events=[
    TimelineEvent(t=0,event_type=EventType.CAMERA,params={"cam":"close","duration":1.5},label="Close on host"),
    TimelineEvent(t=0,event_type=EventType.ENVIRONMENT,params={"ambient":0.2,"key":1.8},label="Interview light"),
    TimelineEvent(t=8,event_type=EventType.CAMERA,params={"cam":"medium","duration":2},label="Pull to medium"),
    TimelineEvent(t=10,event_type=EventType.SEQUENCE_END,params={},label="Ready"),
])
SHOW_CLOSE=TimelineDefinition(name="show_close",description="Closing sequence",duration=16,events=[
    TimelineEvent(t=0,event_type=EventType.CAMERA,params={"cam":"wide","duration":2},label="Wide pull"),
    TimelineEvent(t=3,event_type=EventType.ENVIRONMENT,params={"ambient":0.15,"key":0.4},label="Dim"),
    TimelineEvent(t=10,event_type=EventType.ENVIRONMENT,params={"ambient":0.08,"key":0.2},label="Near dark"),
    TimelineEvent(t=14,event_type=EventType.RECORD,params={"action":"stop"},label="Rec stop"),
    TimelineEvent(t=15,event_type=EventType.SEQUENCE_END,params={},label="Closed"),
])
TIMELINE_REGISTRY: Dict[str,TimelineDefinition]={"cast_sync_60":CAST_SYNC_60,"interview_setup":INTERVIEW_SETUP,"show_close":SHOW_CLOSE}

def create_timeline_router(player: TimelinePlayer, data_dir: Path) -> APIRouter:
    router=APIRouter(prefix="/api/timeline",tags=["Timeline"])
    td_dir=data_dir/"timelines"; td_dir.mkdir(parents=True,exist_ok=True)
    @router.get("/sequences")
    async def list_seq():
        custom=[];
        for f in td_dir.glob("*.json"):
            try: t=TimelineDefinition.load(f); custom.append({"name":t.name,"duration":t.duration,"events":len(t.events),"source":"custom"})
            except Exception as exc:
                logger.warning("Skipping invalid custom timeline %s: %s", f.name, exc)
        built=[{"name":n,"duration":t.duration,"events":len(t.events),"source":"built-in"} for n,t in TIMELINE_REGISTRY.items()]
        return {"sequences":built+custom}
    @router.post("/load/{name}")
    async def load_seq(name:str, identity: Dict[str, Any] = Depends(require_role("mod"))):
        td=TIMELINE_REGISTRY.get(name)
        if not td:
            p=td_dir/f"{name}.json"
            if p.exists(): td=TimelineDefinition.load(p)
        if not td: raise HTTPException(404,f"'{name}' not found")
        issues=player.load_timeline(td)
        if issues: raise HTTPException(400,str(issues))
        return {"ok":True,"name":td.name,"duration":td.duration}
    @router.post("/start")
    async def start(identity: Dict[str, Any] = Depends(require_role("mod"))):
        ok=await player.start()
        if not ok: raise HTTPException(400,"Cannot start")
        return {"ok":True,"state":player.state.value}
    @router.post("/stop")
    async def stop(identity: Dict[str, Any] = Depends(require_role("mod"))): await player.stop(); return {"ok":True}
    @router.post("/pause")
    async def pause(identity: Dict[str, Any] = Depends(require_role("mod"))): await player.pause(); return {"ok":True,"state":player.state.value}
    @router.post("/resume")
    async def resume(identity: Dict[str, Any] = Depends(require_role("mod"))): await player.resume(); return {"ok":True,"state":player.state.value}
    @router.get("/status")
    async def status(): return player.status()
    @router.get("/log")
    async def log(): return player.get_log()
    @router.post("/save")
    async def save(request:Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body=await request.json()
        try: td=TimelineDefinition.from_dict(body)
        except Exception as e: raise HTTPException(400,str(e))
        issues=td.validate()
        if issues: raise HTTPException(400,str(issues))
        td.save(td_dir/f"{td.name}.json"); return {"ok":True,"name":td.name}

    @router.get("/scene-state")
    async def scene_state():
        return player.scene_state()
    return router
