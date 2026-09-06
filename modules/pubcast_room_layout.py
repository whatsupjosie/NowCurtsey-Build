"""
pubcast_room_layout.py — Canonical spatial layout for PubCast Alpha
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™

Defines the room graph, navigation connections, avatar rendering rules,
and background specifications for every room in the Belle Époque Studios
2.5D world.

GREEN ROOM is the hub. All doors are visible from here. It connects
directly to: Dressing Room, Writers Room, Studio, Control Room, Bar,
and the Hallway that leads to the Lobby and Palace Theater.

AVATARS are glowing ethereal SVG energy figures — translucent, graceful,
luminous. NOT sprites. NOT pixel art. NOT cel-shaded. Each character has
a signature glow color, radial gradient body, and a foot-glow pool.
Pete is teal. RePete is cool blue. Purfluous is purple. The user's
color is configurable.

Navigation is 2.5D side-scroll with E to enter doors. Rooms transition
via parallax pan with lighting shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════════
# ROOM DEFINITIONS
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RoomDef:
    room_id: str
    display_name: str
    description: str
    connects_to: List[str]
    spawn_point: bool = False
    background_style: str = ""
    ambient_sound: str = ""
    lighting_mood: str = ""
    narrative_note: str = ""


ROOMS: Dict[str, RoomDef] = {
    # ── THE HUB ──────────────────────────────────────────────────────────
    "green_room": RoomDef(
        room_id="green_room",
        display_name="Green Room",
        description=(
            "The hub. All doors are visible from here. A large, comfortable "
            "space with faded velvet couches, old film posters on wood-paneled "
            "walls, half-lit chandeliers, and the smell of dust and nostalgia. "
            "This is the crossroads — every room in the studio is one door "
            "away. The floor has a worn path between the most-used doors."
        ),
        connects_to=[
            "dressing_room", "writers_room", "studio", "control_room",
            "bar", "hallway",
        ],
        background_style="art-deco decay, velvet and dust, post-glamour elegance",
        ambient_sound="distant hum of old power lines, muffled conversation",
        lighting_mood="warm tungsten, half-lit chandeliers, amber sconces",
        narrative_note="The ghost of the golden age. Stepping into someone's memory.",
    ),

    # ── PRIVATE ROOMS ────────────────────────────────────────────────────
    "dressing_room": RoomDef(
        room_id="dressing_room",
        display_name="Dressing Room",
        description=(
            "Player spawn point. Private per user. Mirror, corkboard of "
            "goals, wardrobe rack, old radio humming Purfluous's archived "
            "advice. This is where you start every session and where you "
            "get ready for the work ahead."
        ),
        connects_to=["green_room"],
        spawn_point=True,
        background_style="intimate, personal, warm mirror lighting",
        ambient_sound="old radio static, fabric rustle",
        lighting_mood="single warm lamp, mirror reflections",
        narrative_note="Your private space. The only room that is truly yours.",
    ),

    # ── CREATIVE ROOMS ───────────────────────────────────────────────────
    "writers_room": RoomDef(
        room_id="writers_room",
        display_name="Writers Room",
        description=(
            "Long oval table, cold coffee cups, old whiteboard covered in "
            "marker ghosts. This is where brainstorming happens — the "
            "dartboard ceremony, script rewrites, and AI-assisted ideation. "
            "The corkboard remembers every past brainstorm."
        ),
        connects_to=["green_room"],
        background_style="functional creative chaos, whiteboard and post-its",
        ambient_sound="marker on whiteboard, coffee mug clinks",
        lighting_mood="overhead fluorescent mixed with desk lamps",
        narrative_note="Where constraints become creativity.",
    ),

    "studio": RoomDef(
        room_id="studio",
        display_name="Studio Stage",
        description=(
            "The main production floor. Full of mismatched sets, props, "
            "and scattered lighting rigs. Belle Époque arched walls with "
            "brass pilasters, wall sconces glowing amber, and a lighting "
            "rig hanging above the stage. Purfluous runs it like a theater. "
            "Pete runs it like a factory. The truth is somewhere between."
        ),
        connects_to=["green_room", "control_room", "foley_room"],
        background_style=(
            "Neo-Deco Analog Luxe — 360° SVG panoramic with arched panels, "
            "brass trim, wall sconces, teal control-room glass, hanging "
            "practical lights. See stage_panoramic.html for canonical "
            "background rendering."
        ),
        ambient_sound="electrical hum, distant fan, light fixture buzz",
        lighting_mood=(
            "tungsten key lights from above, sconce warmth at walls, "
            "teal glow from control room glass"
        ),
        narrative_note="Where the magic happens. Or doesn't. Depends on the day.",
    ),

    "control_room": RoomDef(
        room_id="control_room",
        display_name="Control Room",
        description=(
            "Technical HQ. Edit video, balance sound, set up lighting "
            "grids, mix inputs for live shoots. Monitors everywhere — "
            "some old CRT shells hiding modern workstations, some analog "
            "meters still glowing. Pete's domain. The hidden computer in "
            "the vacuum tube TV husk lives here."
        ),
        connects_to=["green_room", "studio"],
        background_style=(
            "hybrid analog-digital: brass piping around modern monitors, "
            "analog meters beside digital waveforms, blue LED cutting "
            "through amber tungsten"
        ),
        ambient_sound="monitor hum, cooling fans, signal static",
        lighting_mood="blue LED mixed with tungsten, monitor glow",
        narrative_note="Where Pete quietly dragged the place into the 21st century.",
    ),

    "foley_room": RoomDef(
        room_id="foley_room",
        display_name="Foley Room",
        description=(
            "Sound effects studio. Microphones everywhere, coconut halves, "
            "wooden floor sections, a prop guitar, a door on hinges for "
            "slamming. This is where you bang coconuts for horse hooves "
            "and Pints gets his big moment."
        ),
        connects_to=["studio"],
        background_style="acoustic panels, hanging mics, scattered props",
        ambient_sound="room tone, dead silence with occasional creak",
        lighting_mood="overhead practical, dim and focused",
        narrative_note="Where Pete tells you they've had computers for this since 1974.",
    ),

    # ── THE PUB ──────────────────────────────────────────────────────────
    "bar": RoomDef(
        room_id="bar",
        display_name="The Pub",
        description=(
            "Old English pub — Purfluous's sanctuary. The one thing in "
            "the building that worked when he got there. Rich mahogany, "
            "brass fixtures, hand-painted signage. Barely keeps the "
            "lights on. Photos on the wall chronicle the studio's rise "
            "and fall. Pints the cat lives here. Stage Door Joe sleeps "
            "outside."
        ),
        connects_to=["green_room", "bar_stage", "bar_bathroom"],
        background_style=(
            "Old English pub, unchanged. Rich wood, brass fixtures, "
            "amber tungsten, stained-glass reflections, worn bar top"
        ),
        ambient_sound=(
            "ceiling fan hum, ice clinking, faint vinyl crackle, "
            "one stool squeaking"
        ),
        lighting_mood="sparse tungsten amber, one neon beer sign, sconce glow",
        narrative_note=(
            "The heart that still works. Purfluous's definition of 'real.' "
            "Everything outside is performance. In here, it runs on "
            "feeling and habit."
        ),
    ),

    "bar_stage": RoomDef(
        room_id="bar_stage",
        display_name="Bar Stage",
        description=(
            "Small raised corner stage with frayed red velvet curtains, "
            "a single spotlight, and a vintage mic stand. Open mic nights, "
            "karaoke, and Purfluous's impromptu monologues happen here."
        ),
        connects_to=["bar"],
        background_style="cabaret, red velvet, single spotlight haze",
        ambient_sound="amp hum on standby, distant bar murmur",
        lighting_mood="harsh single spot, rest in darkness",
        narrative_note="Where pretending still feels sacred.",
    ),

    "bar_bathroom": RoomDef(
        room_id="bar_bathroom",
        display_name="Pub Bathroom",
        description=(
            "Behind a sign that says 'Not the Men's Room.' Graffiti-covered "
            "door, oddly elegant inside — green and white tile, marble sink, "
            "brass fixtures. Almost too nice for the rest of the bar."
        ),
        connects_to=["bar"],
        background_style="art-deco washroom, green tile, brass, marble",
        ambient_sound="dripping faucet, muffled bar noise",
        lighting_mood="pale tungsten, mirror reflections",
        narrative_note="Where Purfluous says too much.",
    ),

    # ── THE HALLWAY & THEATER ────────────────────────────────────────────
    "hallway": RoomDef(
        room_id="hallway",
        display_name="Hallway",
        description=(
            "The corridor connecting the studio to the outside world. "
            "Old movie posters in dusty frames. The sound of the pub "
            "fades behind you like a dying heartbeat. Leads to the "
            "lobby and the palace theater."
        ),
        connects_to=["green_room", "lobby"],
        background_style="wood paneling, dusty poster frames, dim sconces",
        ambient_sound="footsteps echo, distant electrical hum",
        lighting_mood="dim amber, shadows between frames",
        narrative_note="The border between the real and the performative.",
    ),

    "lobby": RoomDef(
        room_id="lobby",
        display_name="Lobby",
        description=(
            "Abandoned theater lobby. Fading gold leaf, cracked marble "
            "floor, a ticket booth with no one inside. The marquee "
            "outside has half its letters burned out. Heals as creators "
            "arrive — the more work you do, the more this space comes "
            "back to life."
        ),
        connects_to=["hallway", "palace_theater"],
        background_style="abandoned grandeur, gold leaf, cracked marble",
        ambient_sound="wind through broken glass, distant traffic",
        lighting_mood="cold daylight through dirty windows",
        narrative_note="The abandoned theater that heals as creators arrive.",
    ),

    "palace_theater": RoomDef(
        room_id="palace_theater",
        display_name="Palace Theater",
        description=(
            "The dirty, dingy, old beat-up movie palace. Fading gold leaf "
            "on the ceiling, velvet seats that smell like fifty years of "
            "dust, a screen that has seen better days. This is where the "
            "premiere happens. Gold light seeps under the locked door "
            "until you earn your way in."
        ),
        connects_to=["lobby"],
        background_style=(
            "decayed grandeur — gold leaf, velvet, dust in projector beams, "
            "art-deco sconces, massive stained screen"
        ),
        ambient_sound="projector hum, seat creaking, dust settling",
        lighting_mood="projector beam through haze, amber wall sconces",
        narrative_note=(
            "Locked. Gold light under the door. You earn your way in by "
            "completing the story. This is where the double feature plays."
        ),
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# AVATAR RENDERING RULES
#
# CRITICAL: Avatars are GLOWING ETHEREAL SVG ENERGY FIGURES.
# NOT sprites. NOT pixel art. NOT cel-shaded. NOT photorealistic.
#
# Each character is a translucent, luminous figure made of radial gradients
# with soft edges, drop-shadow glow filters, and a glowing pool of light
# at their feet. They look like beings made of warm light and color —
# graceful, beautiful, otherworldly.
#
# The canonical rendering is in stage_panoramic.html.
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AvatarStyle:
    character_id: str
    glow_color_rgba: str
    glow_color_hex: str
    gradient_bright: str
    gradient_dim: str
    body_description: str
    signature_detail: str = ""


AVATAR_STYLES: Dict[str, AvatarStyle] = {
    "pete": AvatarStyle(
        character_id="pete",
        glow_color_rgba="rgba(109,214,199,0.45)",
        glow_color_hex="#6dd6c7",
        gradient_bright="#7de8d8",
        gradient_dim="#3aaa98",
        body_description=(
            "Teal energy. Work clothes silhouette — slightly tapered torso. "
            "Relaxed left arm, right arm slightly raised in camera-operator "
            "gesture. Confident, grounded posture."
        ),
        signature_detail="Wedding ring on middle finger of left hand (gold circle stroke)",
    ),

    "repeat": AvatarStyle(
        character_id="repeat",
        glow_color_rgba="rgba(180,200,240,0.38)",
        glow_color_hex="#b4c8f8",
        gradient_bright="#b4c8f8",
        gradient_dim="#6080c0",
        body_description=(
            "Cool blue energy. Slim, younger build. Arms slightly tentative, "
            "nervous energy. Smaller than Pete. Babyface — slightly rounder "
            "head. Earnest posture, leaning slightly forward."
        ),
        signature_detail="Slightly shorter and slimmer than other characters",
    ),

    "sir_purfluous": AvatarStyle(
        character_id="sir_purfluous",
        glow_color_rgba="rgba(192,120,224,0.45)",
        glow_color_hex="#c078e0",
        gradient_bright="#d088f0",
        gradient_dim="#7830a8",
        body_description=(
            "Purple energy. Broader, older, theatrical bearing. Wide coat "
            "body with coat tails trailing. One arm raised in declaration, "
            "hand suggestion at top. Larger head — strong brow. The most "
            "physically imposing avatar."
        ),
        signature_detail="Coat tails flowing, one arm raised theatrically",
    ),

    "user_default": AvatarStyle(
        character_id="user_default",
        glow_color_rgba="rgba(0,255,255,0.4)",
        glow_color_hex="#00FFFF",
        gradient_bright="#00FFFF",
        gradient_dim="#007777",
        body_description=(
            "Cyan energy by default. User-configurable color. Medium build. "
            "Neutral posture. The player's presence in the world."
        ),
        signature_detail="Color configurable via avatar settings",
    ),
}

AVATAR_RENDERING_RULES: Dict[str, str] = {
    "technology": "Pure SVG with radial gradients, NO raster sprites",
    "body_construction": (
        "Translucent radial-gradient fills on path/ellipse/rect elements. "
        "Opacity ranges 0.45-0.9. Body parts: legs (rect), torso (path), "
        "arms (stroke path), neck (rect), head (ellipse)."
    ),
    "glow_system": (
        "CSS filter: drop-shadow with character's glow color. Foot-glow "
        "radial-gradient ellipse beneath feet. Floor shadow via separate div."
    ),
    "animation": (
        "Gentle idle sway via CSS animation. Breathing implied through "
        "subtle scale oscillation. No frame-by-frame animation."
    ),
    "interaction": (
        "Characters face the camera direction, positioned in world-space "
        "coordinates mapped to the panoramic strip percentage."
    ),
    "forbidden": (
        "NO pixel art. NO sprite sheets. NO cel shading. NO hard edges. "
        "NO photorealism. NO bitmap textures on characters. These are "
        "beings made of light, not drawings of people."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# NAVIGATION RULES
# ════════════════════════════════════════════════════════════════════════════

NAVIGATION: Dict[str, str] = {
    "style": "2.5D side-scroll with parallax layering",
    "interaction": "E key to enter doors / interact",
    "transition": "Parallax pan with lighting shift between rooms",
    "spawn": "Dressing Room (private per user)",
    "hub": "Green Room — all doors visible, all rooms one door away",
    "locked_rooms": (
        "Palace Theater starts locked with gold light under the door. "
        "Unlocked by completing the main story arc."
    ),
    "camera": (
        "Side-scroll with depth parallax. Foreground objects (camera "
        "tripods, light stands) pass in front of the character. Background "
        "architecture moves slower. Characters walk behind solid objects."
    ),
}


# ════════════════════════════════════════════════════════════════════════════
# CONVENIENCE
# ════════════════════════════════════════════════════════════════════════════

def get_room(room_id: str) -> Optional[RoomDef]:
    return ROOMS.get(room_id)


def get_connections(room_id: str) -> List[str]:
    room = ROOMS.get(room_id)
    return list(room.connects_to) if room else []


def get_avatar_style(character_id: str) -> Optional[AvatarStyle]:
    return AVATAR_STYLES.get(character_id)


def get_all_room_ids() -> List[str]:
    return list(ROOMS.keys())


def validate_room_graph() -> List[str]:
    """Check that all room connections are bidirectional and valid."""
    issues = []
    for room_id, room in ROOMS.items():
        for target in room.connects_to:
            if target not in ROOMS:
                issues.append(f"{room_id} connects to {target} which does not exist")
            elif room_id not in ROOMS[target].connects_to:
                issues.append(
                    f"{room_id} -> {target} but {target} does not connect back"
                )
    return issues
