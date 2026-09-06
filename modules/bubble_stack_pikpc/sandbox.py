from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .core import AABB, BubbleConfig, OrderEvent, OrderEventType, Vec3
from .engine import BubbleStackEngine, FrameObject, StepResult


class SandboxAction(str, Enum):
    LOAD = "load"
    WAIT = "wait"
    WALK_TO_TABLE = "walk_to_table"
    ACTIVATE_CUP_HOTSPOT = "activate_cup_hotspot"
    PICK_UP_CUP = "pick_up_cup"
    DRINK_FROM_CUP = "drink_from_cup"
    SET_CUP_DOWN = "set_cup_down"
    SLAM_CUP_DOWN = "slam_cup_down"
    PUSH_CUP_AWAY = "push_cup_away"
    THROW_CUP = "throw_cup"


class SandboxOutcome(str, Enum):
    NONE = "none"
    CUP_MOVED = "cup_moved"
    CUP_HIT_TABLE = "cup_hit_table"
    CUP_HIT_VASE = "cup_hit_vase"
    CUP_HIT_CHAIR = "cup_hit_chair"
    CUP_HIT_FLOOR = "cup_hit_floor"
    CUP_HIT_WALL = "cup_hit_wall"
    VASE_JIGGLED = "vase_jiggled"
    VASE_SHIFTED = "vase_shifted"
    VASE_TIPPED = "vase_tipped"
    VASE_FELL = "vase_fell"
    VASE_SHATTERED = "vase_shattered"
    TABLE_SHIFTED = "table_shifted"
    CHAIR_SHIFTED = "chair_shifted"




@dataclass(slots=True)
class EnvironmentConfig:
    """Physical assumptions for the sandbox.

    Earth gravity is explicit because Bubble Stack/PIKPC should never smuggle
    planetary assumptions into consequence resolution. Future demos can change
    this value for moon, Mars, underwater, or stylized worlds without changing
    the consequence rules.
    """

    gravity_m_s2: float = 9.80665
    air_drag: float = 0.02
    table_surface_y: float = 1.10
    floor_y: float = 0.0


@dataclass(frozen=True, slots=True)
class ActorPhysicalProfile:
    """Configurable demo assumptions for a performer/avatar body.

    These are not asserted as population facts. They are sandbox defaults used so
    Bubble Stack can reason about approximate mass, height, and strength output
    instead of treating every actor as a weightless animation puppet, because
    apparently digital bodies need to be reminded that gravity has opinions.
    """

    profile_id: str
    label: str
    mass_kg: float
    height_m: float
    max_hand_force_n: float
    max_throw_force_n: float
    grip_force_n: float

    @staticmethod
    def pounds_to_kg(pounds: float) -> float:
        return pounds * 0.45359237

    @staticmethod
    def inches_to_m(inches: float) -> float:
        return inches * 0.0254

    @classmethod
    def demo_adult_male(cls) -> "ActorPhysicalProfile":
        mass = cls.pounds_to_kg(170.0)
        height = cls.inches_to_m(72.0)
        return cls.from_mass_height("demo_adult_male_170lb_6ft", "Demo adult male, 170 lb, 6 ft", mass, height)

    @classmethod
    def demo_adult_female(cls) -> "ActorPhysicalProfile":
        mass = cls.pounds_to_kg(130.0)
        height = cls.inches_to_m(68.0)
        return cls.from_mass_height("demo_adult_female_130lb_5ft8", "Demo adult female, 130 lb, 5 ft 8 in", mass, height)

    @classmethod
    def from_mass_height(cls, profile_id: str, label: str, mass_kg: float, height_m: float) -> "ActorPhysicalProfile":
        if mass_kg <= 0 or height_m <= 0:
            raise ValueError("actor physical profiles require positive mass and height")
        # Conservative demo heuristics only. Swap with real biomechanics later.
        body_weight_n = mass_kg * 9.80665
        return cls(
            profile_id=profile_id,
            label=label,
            mass_kg=mass_kg,
            height_m=height_m,
            max_hand_force_n=body_weight_n * 0.70,
            max_throw_force_n=body_weight_n * 0.48,
            grip_force_n=body_weight_n * 0.42,
        )

    def as_dict(self) -> Dict[str, float | str]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "mass_kg": round(self.mass_kg, 4),
            "height_m": round(self.height_m, 4),
            "max_hand_force_n": round(self.max_hand_force_n, 4),
            "max_throw_force_n": round(self.max_throw_force_n, 4),
            "grip_force_n": round(self.grip_force_n, 4),
        }


@dataclass(slots=True)
class MaterialProfile:
    mass: float
    friction: float
    restitution: float
    stability: float
    fragility: float = 0.0


@dataclass(slots=True)
class SandboxObjectPose:
    object_id: str
    center: Vec3
    size: Vec3
    semantic_tags: Tuple[str, ...]
    material: MaterialProfile = field(default_factory=lambda: MaterialProfile(1.0, 0.45, 0.25, 1.0))
    velocity: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    orientation_tilt: float = 0.0
    broken: bool = False

    @property
    def bounds(self) -> AABB:
        return AABB.from_center_size(self.center, self.size)

    def to_frame_object(self) -> FrameObject:
        return FrameObject(
            object_id=self.object_id,
            bounds=self.bounds,
            semantic_tags=self.semantic_tags,
        )


@dataclass(slots=True)
class SandboxHotspot:
    hotspot_id: str
    object_id: str
    center: Vec3
    radius: float
    action: SandboxAction
    label: str
    active: bool = True

    def contains(self, point: Vec3) -> bool:
        return self.active and self.center.distance_to(point) <= self.radius


@dataclass(slots=True)
class KineticIntent:
    action: SandboxAction
    source_id: str
    target_id: str
    contact_point: Vec3
    force_vector: Vec3
    duration_seconds: float
    description: str

    force_scale_newtons_per_unit: float = 100.0

    @property
    def impulse(self) -> float:
        return self.force_vector.length() * max(0.001, self.duration_seconds)

    @property
    def force_newtons(self) -> float:
        return self.force_vector.length() * self.force_scale_newtons_per_unit

    @property
    def impulse_newton_seconds(self) -> float:
        return self.force_newtons * max(0.001, self.duration_seconds)


@dataclass(slots=True)
class PhysicsResolution:
    intent: KineticIntent
    outcomes: List[SandboxOutcome]
    contacts: List[str]
    affected_objects: List[str]
    notes: List[str]
    cup_final_position: Tuple[float, float, float]
    vase_final_position: Tuple[float, float, float]
    vase_state: str
    table_state: str
    chair_state: str
    environment_gravity_m_s2: float
    actor_profile: Dict[str, float | str]
    applied_force_newtons: float
    applied_impulse_newton_seconds: float


@dataclass(slots=True)
class SandboxFrameSummary:
    frame: int
    action: SandboxAction
    actor_position: Tuple[float, float, float]
    cup_position: Tuple[float, float, float]
    vase_position: Tuple[float, float, float]
    cup_state: str
    vase_state: str
    table_state: str
    chair_state: str
    hotspot_active: bool
    order_events: List[str]
    active_bubbles: int
    top_regions: List[Dict[str, object]]
    consequences: List[str]
    physics_outcomes: List[str] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(slots=True)
class SandboxTrace:
    grid_blocks: Tuple[int, int] = (15, 15)
    root_block_size: float = 1.0
    gravity_m_s2: float = 9.80665
    actor_profile: Dict[str, float | str] = field(default_factory=dict)
    summaries: List[SandboxFrameSummary] = field(default_factory=list)
    physics_resolutions: List[PhysicsResolution] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "grid_blocks": self.grid_blocks,
            "root_block_size": self.root_block_size,
            "gravity_m_s2": self.gravity_m_s2,
            "actor_profile": self.actor_profile,
            "summaries": [asdict(s) for s in self.summaries],
            "physics_resolutions": [asdict(r) for r in self.physics_resolutions],
        }


class PubBlockSandbox:
    """15x15 PubBlock proof scene for Bubble Stack / PIKPC.

    PubCast grid rule: the sandbox uses the same base-ten PubBlock
    subdivision language as PubCast. Root bubbles are PubBlocks. Any active
    PubBlock subdivides by 10 along x/y/z, so child addresses are decimal
    precision rather than a separate toy coordinate system.

    The scene is deliberately small. Its core invariant is also deliberately
    strict: an interaction name never maps directly to an outcome. A brush,
    throw, slam, or gentle placement only creates kinetic conditions. Vase,
    chair, table, floor, wall, and cup consequences occur only through contact,
    propagated table impulse, or physically plausible force transfer.
    """

    def __init__(self, grid_blocks: int = 15, block_size: float = 1.0, environment: Optional[EnvironmentConfig] = None, actor_profile: Optional[ActorPhysicalProfile] = None) -> None:
        if grid_blocks <= 0:
            raise ValueError("grid_blocks must be positive")
        self.grid_blocks = grid_blocks
        self.block_size = block_size
        self.environment = environment or EnvironmentConfig()
        self.actor_profile = actor_profile or ActorPhysicalProfile.demo_adult_male()
        self.frame_index = 0
        self.cup_state = "on_table"
        self.vase_state = "upright"
        self.table_state = "still"
        self.chair_state = "still"
        self.hotspot_was_activated = False
        self.last_resolution: Optional[PhysicsResolution] = None
        self.engine = BubbleStackEngine(BubbleConfig(
            root_bubble_size=block_size,
            subdivision_factor=10,
            max_depth=3,
            min_child_size=block_size / 100,
            refine_threshold=0.65,
            collapse_threshold=0.16,
            decay_per_second=0.48,
            neighbor_transfer_radius=1,
            max_active_bubbles=5000,
            motion_threshold_fraction=0.01,
            volatile_motion_fraction=0.18,
            velocity_change_threshold_fraction=0.06,
            contact_tolerance_fraction=0.045,
            target_frame_seconds=1/30,
        ))
        self.actor = SandboxObjectPose("actor_body", Vec3(2.0, 0.9, 7.0), Vec3(0.65, self.actor_profile.height_m, 0.65), ("actor", "human", "body"), MaterialProfile(self.actor_profile.mass_kg, 0.8, 0.05, 1.0))
        self.actor_hand = SandboxObjectPose("actor_right_hand", Vec3(2.35, 1.25, 7.0), Vec3(0.18, 0.18, 0.18), ("actor", "hand", "limb"), MaterialProfile(4, 0.6, 0.05, 1.0))
        self.table = SandboxObjectPose("table", Vec3(10.0, 0.55, 7.0), Vec3(1.8, 1.1, 1.2), ("prop", "furniture", "table", "static"), MaterialProfile(18, 0.75, 0.08, 2.5))
        self.chair = SandboxObjectPose("chair", Vec3(8.4, 0.5, 8.2), Vec3(0.9, 1.0, 0.9), ("prop", "furniture", "chair"), MaterialProfile(7, 0.55, 0.18, 1.5))
        self.vase = SandboxObjectPose("vase", Vec3(9.45, 1.25, 6.8), Vec3(0.28, 0.7, 0.28), ("prop", "vase", "fragile"), MaterialProfile(1.15, 0.42, 0.18, 0.72, fragility=0.85))
        self.cup = SandboxObjectPose("cup", Vec3(10.55, 1.16, 7.1), Vec3(0.28, 0.36, 0.28), ("prop", "cup", "hotspot", "grabbable"), MaterialProfile(0.38, 0.35, 0.28, 0.55, fragility=0.45))
        self.hotspot = SandboxHotspot("cup_hotspot", "cup", self.cup.center, 0.75, SandboxAction.ACTIVATE_CUP_HOTSPOT, "Interact with cup")
        for a, b, w in [
            ("actor_right_hand", "cup", 1.0),
            ("cup", "table", 0.75),
            ("cup", "vase", 0.35),
            ("cup", "chair", 0.25),
            ("table", "vase", 0.55),
        ]:
            self.engine.connect_objects(a, b, weight=w)

    def frame_objects(self) -> List[FrameObject]:
        return [p.to_frame_object() for p in [self.actor, self.actor_hand, self.table, self.chair, self.vase, self.cup]]

    def load_still(self, settle_frames: int = 6) -> SandboxTrace:
        trace = SandboxTrace((self.grid_blocks, self.grid_blocks), self.block_size, self.environment.gravity_m_s2, self.actor_profile.as_dict())
        for _ in range(settle_frames):
            result = self._step(SandboxAction.LOAD)
            trace.summaries.append(self._summarize(result, SandboxAction.LOAD))
        return trace

    def run_scripted_demo(self) -> SandboxTrace:
        trace = self.load_still(settle_frames=4)
        self._append_walk_to_table(trace)
        trace.summaries.append(self._summarize(self.activate_hotspot(), SandboxAction.ACTIVATE_CUP_HOTSPOT))
        self._append_pickup_drink_setdown(trace)
        self._append_wait(trace, 5)
        return trace

    def run_cup_option_demo(self) -> SandboxTrace:
        trace = self.load_still(settle_frames=4)
        self._append_walk_to_table(trace)
        trace.summaries.append(self._summarize(self.activate_hotspot(), SandboxAction.ACTIVATE_CUP_HOTSPOT))
        for action, force in [
            (SandboxAction.SET_CUP_DOWN, Vec3(0.05, -0.45, 0.02)),
            (SandboxAction.SLAM_CUP_DOWN, Vec3(0.10, -3.2, 0.06)),
            (SandboxAction.PUSH_CUP_AWAY, Vec3(-1.2, 0.0, -0.65)),
            (SandboxAction.THROW_CUP, Vec3(-3.2, 1.25, -1.2)),
        ]:
            self.reset_tabletop_objects()
            resolution = self.perform_cup_interaction(action, force)
            trace.physics_resolutions.append(resolution)
            trace.summaries.append(self._summarize(self._kinetic_event_step(resolution), action, resolution))
            self._append_wait(trace, 2)
        return trace

    def perform_cup_interaction(self, action: SandboxAction, force_vector: Vec3) -> PhysicsResolution:
        if action not in {SandboxAction.SET_CUP_DOWN, SandboxAction.SLAM_CUP_DOWN, SandboxAction.PUSH_CUP_AWAY, SandboxAction.THROW_CUP}:
            raise ValueError(f"{action.value} is not a kinetic cup interaction")
        intent = KineticIntent(
            action=action,
            source_id="actor_right_hand",
            target_id="cup",
            contact_point=self.cup.center,
            force_vector=force_vector,
            duration_seconds={
                SandboxAction.SET_CUP_DOWN: 0.35,
                SandboxAction.SLAM_CUP_DOWN: 0.16,
                SandboxAction.PUSH_CUP_AWAY: 0.22,
                SandboxAction.THROW_CUP: 0.28,
            }[action],
            description=f"{action.value} with force {force_vector.as_tuple()}",
        )
        intent, strength_note = self._apply_actor_strength_limits(intent)
        resolution = self._resolve_cup_intent(intent)
        if strength_note:
            resolution.notes.append(strength_note)
        self.last_resolution = resolution
        return resolution

    def reset_tabletop_objects(self) -> None:
        self.cup.center = Vec3(10.55, 1.16, 7.1)
        self.cup.velocity = Vec3(0, 0, 0)
        self.cup_state = "on_table"
        self.vase.center = Vec3(9.45, 1.25, 6.8)
        self.vase.velocity = Vec3(0, 0, 0)
        self.vase.orientation_tilt = 0.0
        self.vase.broken = False
        self.vase_state = "upright"
        self.table.center = Vec3(10.0, 0.55, 7.0)
        self.table_state = "still"
        self.chair.center = Vec3(8.4, 0.5, 8.2)
        self.chair_state = "still"
        self.hotspot.center = self.cup.center

    def activate_hotspot(self) -> StepResult:
        self.frame_index += 1
        self.hotspot_was_activated = self.hotspot.contains(self.actor_hand.center) or self.hotspot.contains(self.actor.center)
        intensity = 1.15 if self.hotspot_was_activated else 0.35
        event = OrderEvent(
            OrderEventType.SEMANTIC_ATTENTION,
            self.cup.center,
            intensity,
            source_id="actor_right_hand",
            target_id="cup",
            direction=(self.cup.center - self.actor_hand.center).normalized(),
            depth_hint=4,
            metadata={"hotspot_id": self.hotspot.hotspot_id, "action": "cup_hotspot"},
        )
        return self.engine.apply_external_event(event)


    def _apply_actor_strength_limits(self, intent: KineticIntent) -> Tuple[KineticIntent, Optional[str]]:
        limit = self.actor_profile.max_throw_force_n if intent.action == SandboxAction.THROW_CUP else self.actor_profile.max_hand_force_n
        requested = intent.force_newtons
        if requested <= limit or requested <= 0:
            return intent, None
        scale = limit / requested
        limited = KineticIntent(
            action=intent.action,
            source_id=intent.source_id,
            target_id=intent.target_id,
            contact_point=intent.contact_point,
            force_vector=intent.force_vector * scale,
            duration_seconds=intent.duration_seconds,
            description=intent.description + f"; force limited by {self.actor_profile.profile_id}",
            force_scale_newtons_per_unit=intent.force_scale_newtons_per_unit,
        )
        return limited, (
            f"Requested force {requested:.1f} N exceeded {self.actor_profile.profile_id} capacity "
            f"({limit:.1f} N); scaled to preserve physically plausible actor output."
        )

    def _resolve_cup_intent(self, intent: KineticIntent) -> PhysicsResolution:
        outcomes: List[SandboxOutcome] = []
        contacts: List[str] = []
        affected: List[str] = ["cup"]
        notes: List[str] = []
        impulse = intent.impulse
        direction = intent.force_vector.normalized()

        if intent.action == SandboxAction.SET_CUP_DOWN:
            self.cup.center = self.cup.center + Vec3(0.12, 0.0, 0.12)
            self.cup_state = "on_table_shifted"
            outcomes.append(SandboxOutcome.CUP_MOVED)
            notes.append("Gentle set-down moved the cup slightly; no propagated consequence threshold crossed.")
        elif intent.action == SandboxAction.SLAM_CUP_DOWN:
            contacts.append("cup->table")
            affected.append("table")
            outcomes.append(SandboxOutcome.CUP_HIT_TABLE)
            self.cup.center = Vec3(self.cup.center.x + 0.03, 1.13, self.cup.center.z + 0.02)
            self.cup_state = "slammed_on_table"
            if impulse > 0.38:
                self.table_state = "vibrating"
                table_to_vase = self.vase.center.distance_to(self.cup.center)
                vibration = (impulse / max(0.1, table_to_vase)) * 0.22
                if vibration > self.vase.material.stability * 0.18:
                    self.vase.center = self.vase.center + Vec3(0.035, 0.0, -0.015)
                    self.vase.orientation_tilt = min(0.35, vibration)
                    self.vase_state = "jiggled"
                    outcomes.append(SandboxOutcome.VASE_JIGGLED)
                    affected.append("vase")
                    contacts.append("table vibration->vase")
                else:
                    notes.append("Table impulse dissipated before moving the vase.")
            else:
                notes.append("Slam impulse remained below visible table-transfer threshold.")
        elif intent.action in {SandboxAction.PUSH_CUP_AWAY, SandboxAction.THROW_CUP}:
            # The action creates initial kinetic conditions only. Outcomes are
            # resolved by sampling the resulting path under the configured world
            # assumptions. For throws, Earth gravity curves the path downward.
            # For pushes, the cup slides along the tabletop unless it leaves the
            # table or contacts another object.
            speed = impulse / max(0.001, self.cup.material.mass)
            self.cup.velocity = direction * speed
            self.cup_state = "airborne" if intent.action == SandboxAction.THROW_CUP else "sliding"
            outcomes.append(SandboxOutcome.CUP_MOVED)
            hit = self._resolve_cup_path(intent)
            if hit is None:
                # End position is deterministic and still physics-informed: a
                # push ends along its tabletop slide; a throw lands on its sampled
                # ballistic terminal point if it hits nothing else first.
                self.cup.center = self._terminal_cup_position(intent)
                notes.append("Cup path produced no contact with vase, chair, wall, floor, or table edge.")
            else:
                target_id, point = hit
                self.cup.center = point
                contacts.append(f"cup->{target_id}")
                affected.append(target_id)
                if target_id == "vase":
                    outcomes.append(SandboxOutcome.CUP_HIT_VASE)
                    self._apply_vase_impact(intent, point, outcomes, affected, notes)
                elif target_id == "chair":
                    outcomes.append(SandboxOutcome.CUP_HIT_CHAIR)
                    if impulse > 0.2:
                        self.chair.center = self.chair.center + Vec3(direction.x * 0.08, 0, direction.z * 0.08)
                        self.chair_state = "shifted"
                        outcomes.append(SandboxOutcome.CHAIR_SHIFTED)
                elif target_id == "table":
                    outcomes.append(SandboxOutcome.CUP_HIT_TABLE)
                    self.table_state = "rattled"
                elif target_id == "floor":
                    outcomes.append(SandboxOutcome.CUP_HIT_FLOOR)
                    self.cup_state = "on_floor"
                elif target_id == "wall":
                    outcomes.append(SandboxOutcome.CUP_HIT_WALL)
                    self.cup_state = "bounced_from_wall"
        else:
            notes.append("No kinetic resolver for action; no consequence produced.")

        if not outcomes:
            outcomes.append(SandboxOutcome.NONE)
        return PhysicsResolution(
            intent=intent,
            outcomes=outcomes,
            contacts=contacts,
            affected_objects=affected,
            notes=notes,
            cup_final_position=self.cup.center.as_tuple(),
            vase_final_position=self.vase.center.as_tuple(),
            vase_state=self.vase_state,
            table_state=self.table_state,
            chair_state=self.chair_state,
            environment_gravity_m_s2=self.environment.gravity_m_s2,
            actor_profile=self.actor_profile.as_dict(),
            applied_force_newtons=round(intent.force_newtons, 4),
            applied_impulse_newton_seconds=round(intent.impulse_newton_seconds, 4),
        )

    def _apply_vase_impact(self, intent: KineticIntent, point: Vec3, outcomes: List[SandboxOutcome], affected: List[str], notes: List[str]) -> None:
        incoming = intent.impulse / max(0.01, self.vase.material.mass)
        height_factor = max(0.2, (point.y - (self.vase.center.y - self.vase.size.y / 2)) / max(0.01, self.vase.size.y))
        instability = incoming * (0.75 + height_factor) * (1.0 + self.vase.material.fragility * 0.35)
        push = intent.force_vector.normalized()
        if instability < 0.32:
            self.vase.center = self.vase.center + Vec3(push.x * 0.025, 0, push.z * 0.025)
            self.vase.orientation_tilt = 0.08
            self.vase_state = "shifted"
            outcomes.append(SandboxOutcome.VASE_SHIFTED)
            notes.append("Cup touched vase below tip threshold; vase shifted but stayed upright.")
        elif instability < 0.68:
            self.vase.center = self.vase.center + Vec3(push.x * 0.07, 0, push.z * 0.07)
            self.vase.orientation_tilt = 0.42
            self.vase_state = "tipped"
            outcomes.append(SandboxOutcome.VASE_TIPPED)
            notes.append("Cup impact exceeded stability threshold; vase tipped but did not fall.")
        elif instability < 1.05:
            self.vase.center = self.vase.center + Vec3(push.x * 0.16, -0.18, push.z * 0.16)
            self.vase.orientation_tilt = 1.15
            self.vase_state = "fallen"
            outcomes.append(SandboxOutcome.VASE_FELL)
            notes.append("Cup impact drove vase beyond recoverable balance; vase fell.")
        else:
            self.vase.center = self.vase.center + Vec3(push.x * 0.18, -0.22, push.z * 0.18)
            self.vase.orientation_tilt = 1.4
            self.vase.broken = True
            self.vase_state = "shattered"
            outcomes.append(SandboxOutcome.VASE_SHATTERED)
            notes.append("Impact exceeded fragility threshold; vase shattered.")
        affected.append("vase_support_chain")

    def _resolve_cup_path(self, intent: KineticIntent) -> Optional[Tuple[str, Vec3]]:
        if intent.action == SandboxAction.THROW_CUP:
            return self._first_contact_on_projectile_path(intent)
        travel_scale = 1.65
        direction = intent.force_vector.normalized()
        end = self.cup.center + Vec3(direction.x * travel_scale, 0.0, direction.z * travel_scale)
        return self._first_contact_on_path(intent.contact_point, end, include_table=False, keep_tabletop_y=True)

    def _terminal_cup_position(self, intent: KineticIntent) -> Vec3:
        direction = intent.force_vector.normalized()
        if intent.action == SandboxAction.THROW_CUP:
            last = intent.contact_point
            for p in self._projectile_samples(intent):
                last = p
                if p.y <= self.environment.floor_y + self.cup.size.y / 2:
                    return Vec3(p.x, self.environment.floor_y + self.cup.size.y / 2, p.z)
            return last
        return self.cup.center + Vec3(direction.x * 1.65, 0.0, direction.z * 1.65)

    def _projectile_samples(self, intent: KineticIntent, steps: int = 72) -> List[Vec3]:
        # Simple deterministic ballistic path. This is deliberately small,
        # inspectable, and replaceable by a real physics engine later. Earth
        # gravity is explicit via EnvironmentConfig.
        v0 = self._initial_cup_velocity(intent)
        start = intent.contact_point
        duration = 0.92
        samples: List[Vec3] = []
        for i in range(1, steps + 1):
            t = duration * (i / steps)
            drag = max(0.0, 1.0 - self.environment.air_drag * t)
            p = Vec3(
                start.x + v0.x * t * drag,
                start.y + v0.y * t - 0.5 * self.environment.gravity_m_s2 * t * t,
                start.z + v0.z * t * drag,
            )
            samples.append(p)
        return samples

    def _initial_cup_velocity(self, intent: KineticIntent) -> Vec3:
        # Force units in the sandbox are intentionally human-scale control inputs,
        # not a full Newtonian solver. Convert them to an impulse-derived launch
        # velocity using the cup mass so actor strength and duration matter.
        return (intent.force_vector * max(0.001, intent.duration_seconds)) / max(0.001, self.cup.material.mass)

    def _first_contact_on_projectile_path(self, intent: KineticIntent) -> Optional[Tuple[str, Vec3]]:
        obstacles = [self.vase, self.chair, self.table]
        start = intent.contact_point
        start_tabletop = self.environment.table_surface_y + self.cup.size.y / 2
        for p in self._projectile_samples(intent):
            if p.x < 0 or p.z < 0 or p.x > self.grid_blocks or p.z > self.grid_blocks:
                return ("wall", p)
            if p.y <= self.environment.floor_y + self.cup.size.y / 2:
                return ("floor", Vec3(p.x, self.environment.floor_y + self.cup.size.y / 2, p.z))
            cup_probe = AABB.from_center_size(p, self.cup.size)
            for obj in obstacles:
                if obj.object_id == "table":
                    # The table is the launch support for a tabletop throw. Do not
                    # count ordinary overlap with that support as a new collision;
                    # otherwise every throw becomes a fake scripted table hit. A
                    # table result is reserved for downward slams or future edge/
                    # bounce logic that explicitly crosses back into the tabletop.
                    if p.y >= self.environment.table_surface_y - 0.01:
                        continue
                if cup_probe.intersects(obj.bounds):
                    return (obj.object_id, p)
        return None

    def _first_contact_on_path(self, start: Vec3, end: Vec3, *, include_table: bool = True, keep_tabletop_y: bool = False) -> Optional[Tuple[str, Vec3]]:
        # Deterministic segment sampling keeps this demo inspectable. It is not a
        # full continuous collision solver. Its invariant is still correct: no
        # consequence without the sampled path intersecting an object or boundary.
        obstacles = [self.vase, self.chair, self.table]
        steps = 72
        for i in range(1, steps + 1):
            t = i / steps
            p = start + (end - start) * t
            if keep_tabletop_y:
                p = Vec3(p.x, self.cup.center.y, p.z)
            if p.x < 0 or p.z < 0 or p.x > self.grid_blocks or p.z > self.grid_blocks:
                return ("wall", p)
            if p.y < self.environment.floor_y + self.cup.size.y / 2:
                return ("floor", p)
            cup_probe = AABB.from_center_size(p, self.cup.size)
            for obj in obstacles:
                if obj.object_id == "table" and not include_table:
                    continue
                if obj.object_id == "table" and p.y > self.table.bounds.max.y + self.cup.size.y:
                    continue
                if cup_probe.intersects(obj.bounds):
                    return (obj.object_id, p)
        return None

    def _kinetic_event_step(self, resolution: PhysicsResolution) -> StepResult:
        self.frame_index += 1
        intent = resolution.intent
        direction = intent.force_vector.normalized()
        intensity = max(0.15, min(4.5, intent.impulse * 3.0))
        event_type = OrderEventType.SURFACE_CONTACT if resolution.contacts else OrderEventType.VOLATILE_MOTION
        if intent.action == SandboxAction.SET_CUP_DOWN and not resolution.contacts:
            event_type = OrderEventType.MOTION
            intensity = 0.22
        event = OrderEvent(
            event_type,
            intent.contact_point,
            intensity,
            source_id=intent.source_id,
            target_id=intent.target_id,
            direction=direction,
            depth_hint=4 if intensity > 0.5 else 2,
            metadata={
                "sandbox_action": intent.action.value,
                "outcomes": [o.value for o in resolution.outcomes],
                "contacts": resolution.contacts,
                "affected_objects": resolution.affected_objects,
                "rule": "outcomes derive from contact/force/material checks, never action name alone",
            },
        )
        # First ingest the new object positions, then inject the kinetic event so
        # Bubble Stack sees both actual geometry and interpreted consequence.
        self.engine.step(self.frame_objects())
        return self.engine.apply_external_event(event)

    def _append_walk_to_table(self, trace: SandboxTrace) -> None:
        for x in [3.0, 4.3, 5.6, 6.9, 8.1, 9.1, 9.75]:
            self._move_actor(Vec3(x, 0.9, 7.0))
            result = self._step(SandboxAction.WALK_TO_TABLE)
            trace.summaries.append(self._summarize(result, SandboxAction.WALK_TO_TABLE))

    def _append_pickup_drink_setdown(self, trace: SandboxTrace) -> None:
        for hand, cup, action, state in [
            (Vec3(10.25, 1.25, 7.05), Vec3(10.55, 1.16, 7.1), SandboxAction.PICK_UP_CUP, "held"),
            (Vec3(10.45, 1.22, 7.08), Vec3(10.48, 1.2, 7.08), SandboxAction.PICK_UP_CUP, "held"),
            (Vec3(10.35, 1.55, 7.04), Vec3(10.38, 1.51, 7.04), SandboxAction.PICK_UP_CUP, "held"),
            (Vec3(10.18, 1.78, 7.02), Vec3(10.2, 1.76, 7.02), SandboxAction.DRINK_FROM_CUP, "drinking"),
            (Vec3(10.05, 1.86, 7.0), Vec3(10.08, 1.84, 7.0), SandboxAction.DRINK_FROM_CUP, "drinking"),
            (Vec3(10.22, 1.68, 7.05), Vec3(10.24, 1.66, 7.05), SandboxAction.DRINK_FROM_CUP, "drinking"),
        ]:
            self.actor_hand.center = hand
            self.cup.center = cup
            self.cup_state = state
            result = self._step(action)
            trace.summaries.append(self._summarize(result, action))
        resolution = self.perform_cup_interaction(SandboxAction.SET_CUP_DOWN, Vec3(0.05, -0.45, 0.02))
        trace.physics_resolutions.append(resolution)
        trace.summaries.append(self._summarize(self._kinetic_event_step(resolution), SandboxAction.SET_CUP_DOWN, resolution))

    def _append_wait(self, trace: SandboxTrace, frames: int) -> None:
        for _ in range(frames):
            result = self._step(SandboxAction.WAIT)
            trace.summaries.append(self._summarize(result, SandboxAction.WAIT))

    def _move_actor(self, center: Vec3) -> None:
        delta = center - self.actor.center
        self.actor.center = center
        self.actor_hand.center = self.actor_hand.center + delta

    def _step(self, action: SandboxAction) -> StepResult:
        self.frame_index += 1
        return self.engine.step(self.frame_objects())

    def _summarize(self, result: StepResult, action: SandboxAction, resolution: Optional[PhysicsResolution] = None) -> SandboxFrameSummary:
        self.frame_index += 0 if action == SandboxAction.ACTIVATE_CUP_HOTSPOT else 0
        summary = self.engine.jeremy_room_summary()
        top_regions = summary["top_joule_regions"][:5]
        return SandboxFrameSummary(
            frame=self.frame_index,
            action=action,
            actor_position=self.actor.center.as_tuple(),
            cup_position=self.cup.center.as_tuple(),
            vase_position=self.vase.center.as_tuple(),
            cup_state=self.cup_state,
            vase_state=self.vase_state,
            table_state=self.table_state,
            chair_state=self.chair_state,
            hotspot_active=self.hotspot.active,
            order_events=[e.event_type.value for e in result.events],
            active_bubbles=result.active_bubbles,
            top_regions=top_regions,
            consequences=[c.summary for c in result.performance_consequences],
            physics_outcomes=[o.value for o in resolution.outcomes] if resolution else [],
            contacts=resolution.contacts if resolution else [],
            notes=resolution.notes if resolution else [],
        )


def run_pub_block_demo() -> SandboxTrace:
    return PubBlockSandbox().run_scripted_demo()


def run_pub_block_option_demo() -> SandboxTrace:
    return PubBlockSandbox().run_cup_option_demo()

