#!/usr/bin/env python3
"""
MINIMAL NUDGE INTEGRATION
Copy this code into your main.py

This shows the BARE MINIMUM to wire nudge into your system.
Change your imports and initialization, that's it.
"""

# ==============================================================================
# STEP 1: Import the nudge system
# ==============================================================================

from wired_system import (
    NudgeQueue,
    NudgeConsumer,
    JeremyCricket,
    BotManager,
    WiredOrchestrator,
)


# ==============================================================================
# STEP 2: Update your FastAPI startup
# ==============================================================================

# @app.on_event("startup")
async def startup():
    """
    Initialize the nudge system at server startup.
    
    BEFORE:
        bot_manager = BotManager(...)
        jeremy = JeremyCricket(bot_manager=bot_manager)
    
    AFTER (add these lines):
    """
    
    # Create nudge queue
    nudge_q = NudgeQueue(maxsize=64)
    
    # Create Jeremy with QUEUE (not bot_manager directly)
    jeremy = JeremyCricket(
        bot_manager=nudge_q,  # ← Pass queue here
        nudge_cooldown_seconds=5.0,
    )
    
    # Create bot manager
    bot_manager = BotManager()
    
    # Create and start consumer
    consumer = NudgeConsumer(nudge_q, bot_manager, max_age=30.0)
    consumer_task = asyncio.create_task(consumer.run())
    
    # Create orchestrator
    orchestrator = WiredOrchestrator(jeremy, bot_manager)
    
    # Store globally so WebSocket handler can access
    globals()['orchestrator'] = orchestrator
    globals()['consumer_task'] = consumer_task
    globals()['consumer'] = consumer
    
    print("✅ Nudge system initialized")


# ==============================================================================
# STEP 3: Update your WebSocket handler
# ==============================================================================

# @app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    """
    Handle WebSocket messages.
    
    CHANGE: Use orchestrator instead of calling jeremy/bot_manager directly
    """
    
    await websocket.accept()
    user_id = websocket.query_params.get("user_id", "anonymous")
    
    try:
        while True:
            # Receive message from user
            message = await websocket.receive_text()
            
            # CHANGE: Use orchestrator.handle_message()
            result = await orchestrator.handle_message(
                room_id=room_id,
                user_id=user_id,
                message=message,
                history=[],
            )
            
            # Send back emotional state
            await websocket.send_json(result)
            
            # If care level escalated, nudge was automatically queued
            # (you don't need to do anything else)
            
    except WebSocketDisconnect:
        print(f"User {user_id} disconnected from {room_id}")


# ==============================================================================
# STEP 4: Update your shutdown
# ==============================================================================

# @app.on_event("shutdown")
async def shutdown():
    """
    Stop the nudge consumer gracefully.
    
    ADD these lines:
    """
    
    # Stop consumer
    consumer.stop()
    await asyncio.sleep(0.5)
    
    # Cancel its task
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    
    print("✅ Nudge system shut down")


# ==============================================================================
# THAT'S IT!
# ==============================================================================

# Now when a user sends an emotional message:
# 1. orchestrator.handle_message() is called
# 2. Jeremy analyzes emotional state
# 3. If escalation detected, nudge is queued (IMMEDIATELY returns)
# 4. Consumer picks up nudge in background
# 5. Actually calls bot_manager.nudge()
# 6. Bots respond when ready

# The key insight:
# - Jeremy never blocks waiting for bot responses
# - User I/O is never delayed
# - Bots get nudged asynchronously
# - Queue acts as a health checkpoint


# ==============================================================================
# EXAMPLE: Full minimal main.py
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    
    app = FastAPI()
    
    # Global state
    orchestrator = None
    consumer = None
    consumer_task = None
    
    @app.on_event("startup")
    async def startup():
        global orchestrator, consumer, consumer_task
        
        # Initialize nudge system
        nudge_q = NudgeQueue(maxsize=64)
        jeremy = JeremyCricket(bot_manager=nudge_q, nudge_cooldown_seconds=5.0)
        bot_manager = BotManager()
        consumer = NudgeConsumer(nudge_q, bot_manager, max_age=30.0)
        orchestrator = WiredOrchestrator(jeremy, bot_manager)
        
        # Start consumer
        consumer_task = asyncio.create_task(consumer.run())
        
        print("✅ System started")
    
    @app.on_event("shutdown")
    async def shutdown_event():
        global consumer, consumer_task
        consumer.stop()
        await asyncio.sleep(0.5)
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return """
        <h1>Chat</h1>
        <input id="msg" placeholder="Type message...">
        <button onclick="send()">Send</button>
        <div id="output"></div>
        
        <script>
        const ws = new WebSocket("ws://localhost:8000/ws/test-room?user_id=user1");
        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            document.getElementById('output').innerHTML += 
                '<p>' + data.emotional_state.care_name + '</p>';
        };
        function send() {
            ws.send(JSON.stringify({
                type: "chat",
                text: document.getElementById('msg').value
            }));
        }
        </script>
        """
    
    @app.websocket("/ws/{room_id}")
    async def websocket_endpoint(websocket: WebSocket, room_id: str):
        await websocket.accept()
        user_id = websocket.query_params.get("user_id", "anon")
        
        try:
            while True:
                message = await websocket.receive_text()
                result = await orchestrator.handle_message(
                    room_id=room_id,
                    user_id=user_id,
                    message=message,
                )
                await websocket.send_json(result)
        except WebSocketDisconnect:
            pass
    
    # Run it
    # uvicorn.run(app, host="0.0.0.0", port=8000)


# ==============================================================================
# CHECKLIST
# ==============================================================================

CHECKLIST = """
✅ Step 1: Imported NudgeQueue, NudgeConsumer, JeremyCricket, etc.
✅ Step 2: Modified startup() to create nudge_q and pass to Jeremy
✅ Step 3: Created consumer and started it with asyncio.create_task()
✅ Step 4: Created orchestrator with Jeremy and BotManager
✅ Step 5: Modified WebSocket handler to use orchestrator
✅ Step 6: Modified shutdown() to stop consumer gracefully
✅ Step 7: Passed room_id to jeremy.process_message() so it can nudge
✅ Step 8: No circular dependencies anymore!

Now when care level escalates:
1. Jeremy detects it automatically
2. Nudge is queued (returns immediately)
3. Consumer picks it up
4. Bot manager receives actual nudge
5. Bots respond

The user never waits for bot startup. It's all asynchronous.
"""

print(CHECKLIST)
