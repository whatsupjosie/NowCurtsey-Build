"""
modules/recording_pipeline.py — Server-Side Recording Pipeline
Rear View Foresight LLC — Feic Mo Chroí — 2026-03-25
"""
from __future__ import annotations
import atexit, json, logging, time, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.recording_pipeline")

@dataclass
class RecordingEvent:
    timestamp: float; event_type: str; data: Dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {"t":self.timestamp,"type":self.event_type,"data":self.data}

class ServerRecordingSession:
    def __init__(self, session_id: str, output_dir: Path):
        self.session_id=session_id; self.output_dir=output_dir/session_id
        self.output_dir.mkdir(parents=True,exist_ok=True)
        self._events: List[RecordingEvent]=[]; self._cameras: List[Dict]=[]; self._markers: List[Dict]=[]
        self._chat: List[Dict]=[]; self._timeline_snaps: List[Dict]=[]
        self._started_at=time.time(); self._stopped_at: Optional[float]=None; self._is_recording=True
        self._lock=threading.Lock()
        self._flush_thread=threading.Thread(target=self._flush_loop,daemon=True,name=f"flush_{session_id}")
        self._flush_thread.start()
        atexit.register(self._flush_to_disk)
    @property
    def duration(self): return (self._stopped_at or time.time())-self._started_at
    @property
    def is_recording(self): return self._is_recording
    def record_event(self,etype,data=None):
        if not self._is_recording: return
        with self._lock: self._events.append(RecordingEvent(time.time()-self._started_at,etype,data or {}))
    def record_camera_switch(self,from_cam,to_cam,transition="cut"):
        if not self._is_recording: return
        with self._lock: self._cameras.append({"t":time.time()-self._started_at,"from":from_cam,"to":to_cam,"transition":transition})
    def record_chat(self,user,text,user_id=""):
        if not self._is_recording: return
        with self._lock: self._chat.append({"t":time.time()-self._started_at,"user":user,"user_id":user_id,"text":text})
    def record_marker(self,label,operator=""):
        if not self._is_recording: return
        with self._lock: self._markers.append({"t":time.time()-self._started_at,"label":label,"operator":operator})
    def snapshot_timeline(self,status):
        if not self._is_recording: return
        with self._lock: self._timeline_snaps.append({"t":time.time()-self._started_at,**status})
    def stop(self):
        self._is_recording=False; self._stopped_at=time.time()
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.5)
        self._flush_to_disk()
        logger.info("Recording %s stopped (%.1fs)",self.session_id,self.duration); return self.summary()
    def summary(self):
        return {"session_id":self.session_id,"duration":round(self.duration,2),"events":len(self._events),
                "camera_switches":len(self._cameras),"chat_messages":len(self._chat),
                "markers":len(self._markers),"output_dir":str(self.output_dir)}
    def export_edl(self):
        lines=["TITLE: PubCast Recording","FCM: NON-DROP FRAME",""]
        for i,sw in enumerate(self._cameras):
            tc=self._stc(sw["t"]); lines.append(f"{i+1:03d}  {sw['to']:12s} V     C        {tc} {tc} {tc} {tc}")
        return "\n".join(lines)
    def _stc(self,s):
        h=int(s//3600);m=int((s%3600)//60);sec=int(s%60);f=int((s%1)*30)
        return f"{h:02d}:{m:02d}:{sec:02d}:{f:02d}"
    def _flush_to_disk(self):
        with self._lock:
            data={"session_id":self.session_id,"started_at":self._started_at,"stopped_at":self._stopped_at,
                  "duration":self.duration,"events":[e.to_dict() for e in self._events],
                  "cameras":list(self._cameras),"chat":list(self._chat),"markers":list(self._markers)}
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
        path=self.output_dir/"session.json"; tmp=path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as e: logger.error("Flush failed: %s",e); tmp.unlink(missing_ok=True)
        try:
            (self.output_dir / "edit_list.edl").write_text(self.export_edl(), encoding="utf-8")
        except Exception as exc:
            logger.warning("EDL write failed for %s: %s", self.session_id, exc)
    def _flush_loop(self):
        while self._is_recording:
            time.sleep(2)
            if self._is_recording: self._flush_to_disk()

class RecordingPipeline:
    def __init__(self, data_dir: Path):
        self._data_dir=data_dir/"server_recordings"; self._data_dir.mkdir(parents=True,exist_ok=True)
        self._sessions: Dict[str,ServerRecordingSession]={}; self._active: Optional[str]=None
    def start_session(self,session_id=None):
        sid=session_id or f"srec_{int(time.time())}"
        if sid in self._sessions: raise ValueError(f"Session {sid} exists")
        s=ServerRecordingSession(sid,self._data_dir); self._sessions[sid]=s; self._active=sid; return s
    def stop_session(self,session_id=None):
        sid=session_id or self._active
        if not sid or sid not in self._sessions: return {"error":"No session"}
        summary=self._sessions[sid].stop()
        if self._active==sid: self._active=None
        return summary
    def get_active(self): return self._sessions.get(self._active) if self._active else None
    def list_sessions(self): return [s.summary() for s in self._sessions.values()]
    def on_chat_message(self,payload):
        s=self.get_active()
        if s: s.record_chat(payload.get("user",""),payload.get("text",""),payload.get("user_id",""))
    def on_camera_switch(self,from_cam,to_cam):
        s=self.get_active()
        if s: s.record_camera_switch(from_cam,to_cam)
