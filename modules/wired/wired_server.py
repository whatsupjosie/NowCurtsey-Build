"""
WIRED FASTAPI SERVER
Complete HTTP/WebSocket application with all systems integrated.

Integrates:
- unified_runtime_boot.py (EQ, Memory, Persistence)
- wired_orchestrator.py (Agent scheduling)
- Real-time WebSocket communication
- REST API for management
"""

from fastapi import FastAPI, WebSocket, HTTPException, UploadFile, File, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import logging
import json
from pathlib import Path
from typing import Dict, Optional, List, Any
from datetime import datetime
import uuid

# Import our unified systems
from unified_runtime_boot import (
    RuntimeConfig, 
    UnifiedRuntime,
    StructuredLogger,
)
from wired_orchestrator import (
    WiredOrchestrator,
    AgentRegistry,
    CareLevel,
)

# ============================================================================
# GLOBAL STATE
# ============================================================================

class AppState:
    """Application state holder"""
    runtime: Optional[UnifiedRuntime] = None
    orchestrator: Optional[WiredOrchestrator] = None
    logger: Optional[logging.Logger] = None
    active_websockets: Dict[str, List[WebSocket]] = {}

app_state = AppState()

# ============================================================================
# FASTAPI SETUP
# ============================================================================

app = FastAPI(
    title="PubCast AI Virtual Production Studio",
    description="Feic Mo Chroí - See My Heart",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Boot all systems on startup"""
    # Create runtime
    app_state.runtime = UnifiedRuntime(config_path=Path("runtime.config.json"))
    app_state.logger = app_state.runtime.logger
    
    # Bootstrap
    await app_state.runtime.bootstrap()
    
    # Create orchestrator with runtime systems
    registry = AgentRegistry(app_state.logger)
    app_state.orchestrator = WiredOrchestrator(
        registry=registry,
        eq_engine=app_state.runtime.eq,
        memory_system=app_state.runtime.memory,
        logger=app_state.logger,
        max_agents_per_turn=app_state.runtime.config.orchestrator.max_agents_per_turn,
        max_context_messages=app_state.runtime.config.orchestrator.max_context_messages,
        agent_timeout=app_state.runtime.config.orchestrator.agent_timeout,
        max_concurrent_agents=app_state.runtime.config.orchestrator.max_concurrent_agents,
    )
    
    # Initialize default room
    app_state.orchestrator.create_room("studio", "Main Studio")
    app_state.orchestrator.add_agents("studio", ["pete", "sheila", "horace"])
    
    app_state.logger.info("✅ FastAPI server ready")

@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown"""
    if app_state.runtime:
        await app_state.runtime.shutdown()

# ============================================================================
# REST ENDPOINTS
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve simple UI"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>PubCast AI - Virtual Production Studio</title>
        <style>
            body { font-family: Arial; max-width: 800px; margin: 50px auto; }
            h1 { color: #333; }
            .status { padding: 10px; background: #f0f0f0; border-radius: 5px; }
            input { width: 100%; padding: 8px; margin: 5px 0; }
            button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; border-radius: 3px; }
            button:hover { background: #0056b3; }
            #messages { border: 1px solid #ddd; padding: 10px; height: 300px; overflow-y: auto; margin: 10px 0; }
            .message { margin: 5px 0; padding: 5px; background: #f9f9f9; border-left: 3px solid #007bff; }
            .agent { color: #28a745; font-weight: bold; }
            .user { color: #007bff; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>🎭 PubCast AI Virtual Production Studio</h1>
        <p><em>Feic Mo Chroí - See My Heart</em></p>
        
        <div class="status">
            <p><strong>Status:</strong> <span id="status">Connecting...</span></p>
            <p><strong>Care Level:</strong> <span id="care">--</span></p>
            <p><strong>Active Agents:</strong> <span id="agents">--</span></p>
        </div>
        
        <h2>Chat with the Studio</h2>
        <div id="messages"></div>
        
        <input type="text" id="messageInput" placeholder="Type a message..." />
        <button onclick="sendMessage()">Send</button>
        <button onclick="clearChat()">Clear</button>
        
        <h2>System</h2>
        <button onclick="getHealth()">Get Health</button>
        <button onclick="getRoomStats()">Get Room Stats</button>
        
        <script>
            const ws = new WebSocket("ws://localhost:8000/ws/studio");
            
            ws.onopen = function(e) {
                console.log("Connected to studio");
                document.getElementById("status").textContent = "Connected";
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                addMessage(data);
            };
            
            ws.onerror = function(e) {
                console.error("WebSocket error:", e);
                document.getElementById("status").textContent = "Error";
            };
            
            ws.onclose = function(e) {
                console.log("Disconnected");
                document.getElementById("status").textContent = "Disconnected";
            };
            
            function sendMessage() {
                const input = document.getElementById("messageInput");
                const text = input.value.trim();
                if (!text) return;
                
                ws.send(JSON.stringify({
                    type: "chat",
                    text: text,
                    user_id: "user1"
                }));
                
                input.value = "";
            }
            
            function addMessage(data) {
                const messages = document.getElementById("messages");
                const msg = document.createElement("div");
                msg.className = "message";
                
                if (data.type === "chat" && data.role === "user") {
                    msg.innerHTML = `<span class="user">You:</span> ${data.text}`;
                    document.getElementById("care").textContent = data.care_name || "AMBIENT";
                } else if (data.type === "chat" && data.role === "agent") {
                    msg.innerHTML = `<span class="agent">${data.sender_id}:</span> ${data.text}`;
                } else if (data.type === "stream_chunk") {
                    const last = messages.lastChild;
                    if (last) {
                        last.textContent += data.text;
                    } else {
                        msg.innerHTML = `<span class="agent">${data.agent_id}:</span> ${data.text}`;
                        messages.appendChild(msg);
                    }
                    return;
                }
                
                messages.appendChild(msg);
                messages.scrollTop = messages.scrollHeight;
            }
            
            function clearChat() {
                document.getElementById("messages").innerHTML = "";
            }
            
            async function getHealth() {
                const resp = await fetch("/api/health");
                const data = await resp.json();
                alert(JSON.stringify(data, null, 2));
            }
            
            async function getRoomStats() {
                const resp = await fetch("/api/rooms/stats/studio");
                const data = await resp.json();
                alert(JSON.stringify(data, null, 2));
            }
        </script>
    </body>
    </html>
    """

@app.get("/api/health")
async def get_health():
    """System health endpoint"""
    if not app_state.runtime:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    
    return {
        **app_state.runtime.get_health(),
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/api/rooms")
async def list_rooms():
    """List all rooms"""
    if not app_state.orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    return {
        "rooms": [
            {
                "room_id": room_id,
                "room_name": info.get("room_name", room_id),
                "agents": info.get("agent_ids", []),
            }
            for room_id, info in app_state.orchestrator.rooms.items()
        ]
    }

@app.post("/api/rooms/create")
async def create_room(request: Dict[str, str]):
    """Create a new room"""
    room_id = request.get("room_id", str(uuid.uuid4())[:8])
    room_name = request.get("room_name", room_id)
    
    if room_id in app_state.orchestrator.rooms:
        raise HTTPException(status_code=409, detail="Room already exists")
    
    app_state.orchestrator.create_room(room_id, room_name)
    return {"success": True, "room_id": room_id}

@app.post("/api/rooms/{room_id}/agents")
async def add_agents(room_id: str, request: Dict[str, List[str]]):
    """Add agents to a room"""
    if room_id not in app_state.orchestrator.rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    agent_ids = request.get("agent_ids", [])
    app_state.orchestrator.add_agents(room_id, agent_ids)
    
    return {
        "success": True,
        "room_id": room_id,
        "agents": app_state.orchestrator.rooms[room_id]["agent_ids"],
    }

@app.get("/api/rooms/{room_id}/stats")
async def get_room_stats(room_id: str):
    """Get statistics for a room"""
    if room_id not in app_state.orchestrator.rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    return app_state.orchestrator.get_room_stats(room_id)

@app.get("/api/agents")
async def list_agents():
    """List available agents"""
    agents = app_state.orchestrator.registry.get_all_agents()
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "priority": a.priority,
                "specialties": a.specialties,
            }
            for a in agents
        ]
    }

@app.post("/api/user/memory")
async def store_memory(request: Dict[str, str]):
    """Store user memory"""
    from unified_runtime_boot import Memory
    import uuid
    
    user_id = request.get("user_id", "anon")
    memory_type = request.get("type", "episodic")
    content = request.get("content", "")
    
    memory = Memory(
        id=str(uuid.uuid4()),
        type=memory_type,
        content=content,
        user_id=user_id,
    )
    
    app_state.runtime.memory.store(user_id, memory)
    
    return {"success": True, "memory_id": memory.id}

@app.get("/api/user/{user_id}/memories")
async def get_memories(user_id: str, query: str = ""):
    """Recall user memories"""
    memories = app_state.runtime.memory.recall(user_id, query)
    return {
        "user_id": user_id,
        "memories": [
            {
                "id": m.id,
                "type": m.type,
                "content": m.content,
                "timestamp": m.timestamp,
            }
            for m in memories
        ]
    }

@app.post("/api/recording/start")
async def start_recording(request: Dict[str, str]):
    """Start recording session"""
    session_id = str(uuid.uuid4())[:8]
    
    return {
        "success": True,
        "session_id": session_id,
        "message": "Recording started",
    }

@app.post("/api/recording/stop")
async def stop_recording(request: Dict[str, str]):
    """Stop recording session"""
    return {
        "success": True,
        "message": "Recording stopped",
    }

# ============================================================================
# WEBSOCKET HANDLER
# ============================================================================

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint for real-time communication.
    Handles chat, streaming, and presence.
    """
    user_id = str(uuid.uuid4())[:8]
    
    await websocket.accept()
    app_state.logger.info(f"User {user_id} connected to room {room_id}")
    
    # Track connection
    if room_id not in app_state.active_websockets:
        app_state.active_websockets[room_id] = []
    app_state.active_websockets[room_id].append(websocket)
    
    # Send welcome
    await websocket.send_json({
        "type": "system",
        "message": f"Welcome to {room_id}",
        "user_id": user_id,
    })
    
    try:
        while True:
            # Receive message
            raw = await websocket.receive_text()
            data = json.loads(raw)
            
            msg_type = data.get("type", "chat")
            
            if msg_type == "chat":
                text = data.get("text", "")
                if not text:
                    continue
                
                # Broadcast user message to room
                user_msg = {
                    "type": "chat",
                    "role": "user",
                    "user_id": user_id,
                    "sender_id": user_id,
                    "text": text,
                    "care_name": "AMBIENT",
                }
                
                for ws in app_state.active_websockets.get(room_id, []):
                    try:
                        await ws.send_json(user_msg)
                    except Exception as e:
                        app_state.logger.error(f"Send failed: {e}")
                
                # Process through orchestrator
                async def on_chunk(data):
                    """Stream chunk callback"""
                    try:
                        for ws in app_state.active_websockets.get(room_id, []):
                            await ws.send_json({
                                "type": "stream_chunk",
                                "agent_id": data["agent_id"],
                                "text": data["delta"],
                            })
                    except Exception as e:
                        app_state.logger.error(f"Stream send failed: {e}")
                
                async def on_done(data):
                    """Agent done callback"""
                    try:
                        agent_msg = {
                            "type": "chat",
                            "role": "agent",
                            "sender_id": data["agent_id"],
                            "text": data["text"],
                        }
                        for ws in app_state.active_websockets.get(room_id, []):
                            await ws.send_json(agent_msg)
                    except Exception as e:
                        app_state.logger.error(f"Done send failed: {e}")
                
                # Handle through orchestrator
                await app_state.orchestrator.handle_user_message(
                    room_id=room_id,
                    user_id=user_id,
                    text=text,
                    on_chunk=on_chunk,
                    on_done=on_done,
                )
            
            elif msg_type == "presence":
                # User presence message
                presence = {
                    "type": "presence",
                    "user_id": user_id,
                    "action": data.get("action", "online"),
                }
                
                for ws in app_state.active_websockets.get(room_id, []):
                    try:
                        await ws.send_json(presence)
                    except:
                        pass
    
    except Exception as e:
        app_state.logger.error(f"WebSocket error: {e}")
    
    finally:
        # Cleanup
        if room_id in app_state.active_websockets:
            app_state.active_websockets[room_id] = [
                ws for ws in app_state.active_websockets[room_id]
                if ws != websocket
            ]
        
        app_state.logger.info(f"User {user_id} disconnected from room {room_id}")

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Catch-all error handler"""
    app_state.logger.error(f"Unhandled exception: {exc}")
    return {
        "error": str(exc),
        "type": type(exc).__name__,
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
