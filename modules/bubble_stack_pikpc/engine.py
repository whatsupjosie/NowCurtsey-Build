from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .core import (
    AABB, Bubble, BubbleConfig, BubbleStack, BubbleState, OccupancyRecord,
    OrderEvent, OrderEventType, SpatialObject, SurfaceContact, Vec3,
)
from .performance import PerformanceConsequence, build_performance_consequence

EVENT_WEIGHTS: Dict[OrderEventType, float] = {
    OrderEventType.OBJECT_ENTRY: 0.9,
    OrderEventType.OBJECT_EXIT: 0.75,
    OrderEventType.MOTION: 0.65,
    OrderEventType.VOLATILE_MOTION: 1.65,
    OrderEventType.VELOCITY_CHANGE: 1.25,
    OrderEventType.BOUNDARY_CROSSING: 1.4,
    OrderEventType.SURFACE_CONTACT: 1.8,
    OrderEventType.STRUCTURAL_REORDER: 1.35,
    OrderEventType.SEMANTIC_ATTENTION: 1.1,
    OrderEventType.CAMERA_ATTENTION: 1.2,
    OrderEventType.SPEECH: 0.8,
    OrderEventType.TRANSFER: 0.7,
}

@dataclass(slots=True)
class FrameObject:
    object_id: str
    bounds: AABB
    semantic_tags: Tuple[str, ...] = ()

@dataclass(slots=True)
class TransferPulse:
    origin_address: str
    target_address: str
    joules: float
    kind: str
    source_id: Optional[str] = None
    reason: str = ''

@dataclass(slots=True)
class BubbleSnapshot:
    address: str
    depth: int
    size: float
    state: str
    joule_load: float
    child_count: int
    occupancy_count: int
    occupants: List[str]

@dataclass(slots=True)
class ObjectReport:
    object_id: str
    center: Tuple[float, float, float]
    velocity: Tuple[float, float, float]
    occupied_bubbles: List[OccupancyRecord]
    contacts: List[SurfaceContact]
    deepest_depth: int

@dataclass(slots=True)
class StepResult:
    time_seconds: float
    dt: float
    events: List[OrderEvent]
    transfer_pulses: List[TransferPulse]
    refined: List[str]
    collapsed: List[str]
    object_reports: Dict[str, ObjectReport]
    active_bubbles: int
    performance_consequences: List[PerformanceConsequence] = field(default_factory=list)
    trace: Optional['FrameTrace'] = None

@dataclass(slots=True)
class EngineInvariantReport:
    ok: bool
    errors: List[str]
    active_bubbles: int
    observed_roots: int
    max_depth_seen: int

@dataclass(slots=True)
class FrameTrace:
    object_count: int
    entry_count: int
    exit_count: int
    motion_event_count: int
    order_event_count: int
    transfer_count: int
    refined_count: int
    collapsed_count: int
    budget_limited: bool

class SemanticGraph:
    def __init__(self) -> None:
        self.edges: Dict[str, Dict[str, float]] = {}
    def connect(self, a: str, b: str, weight: float = 1.0, bidirectional: bool = True) -> None:
        w = max(0.0, weight)
        self.edges.setdefault(a, {})[b] = w
        if bidirectional: self.edges.setdefault(b, {})[a] = w
    def neighbors(self, node: str) -> Dict[str, float]: return dict(self.edges.get(node, {}))

class BubbleStackEngine:
    """Working minimal Bubble Stack engine.

    This is intentionally not a renderer or physics engine. It is the spatial
    attention engine that sits above raw geometry. Every frame it:
      1. ingests object volumes;
      2. records persistent coarse occupancy;
      3. compares order state to the previous frame;
      4. emits order events;
      5. converts events into Joule Load;
      6. propagates Kinetic Backlash spatially and semantically;
      7. refines hot regions and collapses cooled fine regions.
    """
    def __init__(self, config: Optional[BubbleConfig] = None) -> None:
        self.stack = BubbleStack(config or BubbleConfig())
        self.objects: Dict[str, SpatialObject] = {}
        self.semantic_graph = SemanticGraph()
        self.time_seconds = 0.0
        self.last_events: List[OrderEvent] = []
        self.last_transfers: List[TransferPulse] = []

    @property
    def config(self) -> BubbleConfig: return self.stack.config

    def connect_objects(self, a: str, b: str, weight: float = 1.0, bidirectional: bool = True) -> None:
        self.semantic_graph.connect(a, b, weight, bidirectional)

    def step(self, frame_objects: Iterable[FrameObject], dt: Optional[float] = None) -> StepResult:
        dt = self.config.target_frame_seconds if dt is None else max(1e-9, dt)
        self.time_seconds += dt
        events: List[OrderEvent] = []
        transfers: List[TransferPulse] = []
        event_joules: Dict[int, float] = {}
        refined: List[str] = []
        collapsed: List[str] = []

        incoming = {fo.object_id: fo for fo in frame_objects}
        previous_ids = set(self.objects.keys())
        current_ids = set(incoming.keys())

        # Remove vanished objects first. Coarse roots remain observed; occupancy changes become order events.
        for oid in sorted(previous_ids - current_ids):
            obj = self.objects.pop(oid)
            self._clear_occupancy(oid)
            events.append(OrderEvent(OrderEventType.OBJECT_EXIT, obj.center, 0.8, source_id=oid))

        # Clear current occupants before rebuilding the frame's order state.
        for oid in current_ids:
            self._clear_occupancy(oid)

        reports: Dict[str, ObjectReport] = {}
        for oid, fo in incoming.items():
            prev = self.objects.get(oid)
            if prev is None:
                obj = SpatialObject(oid, fo.bounds, fo.semantic_tags)
                self.objects[oid] = obj
                events.append(OrderEvent(OrderEventType.OBJECT_ENTRY, obj.center, 0.9, source_id=oid))
            else:
                center_delta = fo.bounds.center - prev.center
                velocity = center_delta / dt
                prev_velocity = prev.velocity
                obj = SpatialObject(oid, fo.bounds, fo.semantic_tags or prev.semantic_tags, velocity=velocity, previous_velocity=prev_velocity)
                self.objects[oid] = obj
                events.extend(self._motion_events(obj, prev, dt))
            report = self._record_object(obj)
            reports[oid] = report
            # Bubble boundary contacts are useful spatial evidence, but a stable
            # object merely resting near a bubble face must not emit a new impact
            # every frame. Surface-contact Order Events are emitted only when the
            # object is actually moving enough for the contact to be meaningful.
            moving_contact = obj.velocity.length() * dt / self.config.root_bubble_size >= self.config.motion_threshold_fraction
            if report.contacts and moving_contact:
                events.append(OrderEvent(
                    OrderEventType.SURFACE_CONTACT, obj.center,
                    self.config.contact_weight * len(report.contacts), source_id=oid,
                    direction=obj.velocity.normalized(), metadata={'contact_count': len(report.contacts), 'moving_contact_only': True}
                ))

        # Compare before/after order signatures across all touched bubbles.
        events.extend(self._order_state_events())

        # Decay before new energy so stable regions actually cool.
        self._decay(dt)

        # Apply event energy and immediate path refinement.
        for event in events:
            deepest, applied_joules = self._apply_event(event, transfers)
            event_joules[id(event)] = applied_joules
            if str(deepest.address) not in refined and deepest.address.depth > 1:
                refined.append(str(deepest.address))

        # After refinement, active children need current occupancy, not stale emptiness.
        self._refresh_all_active_occupancy()

        collapsed = self._homeostasis_collapse()
        before_budget_count = self.stack.active_count()
        self._enforce_budget(collapsed)
        budget_limited = before_budget_count > self.config.max_active_bubbles

        self.last_events = events
        self.last_transfers = transfers
        trace = FrameTrace(
            object_count=len(incoming),
            entry_count=sum(1 for e in events if e.event_type == OrderEventType.OBJECT_ENTRY),
            exit_count=sum(1 for e in events if e.event_type == OrderEventType.OBJECT_EXIT),
            motion_event_count=sum(1 for e in events if e.event_type in {OrderEventType.MOTION, OrderEventType.VOLATILE_MOTION, OrderEventType.VELOCITY_CHANGE}),
            order_event_count=len(events),
            transfer_count=len(transfers),
            refined_count=len(refined),
            collapsed_count=len(collapsed),
            budget_limited=budget_limited,
        )
        consequences = self._performance_consequences(events, event_joules)
        return StepResult(self.time_seconds, dt, events, transfers, refined, collapsed, reports, self.stack.active_count(), consequences, trace)

    def apply_external_event(self, event: OrderEvent) -> StepResult:
        """Inject a non-geometry event without deleting current tracked objects.

        Use this for camera focus, speech, user attention, AI attention, or
        control-room events. It intentionally does not call step([]), because
        an empty frame means 'no objects are visible' in a real frame ingest.
        """
        return self._external_event_result(event)

    def _external_event_result(self, event: OrderEvent) -> StepResult:
        self.time_seconds += self.config.target_frame_seconds
        transfers: List[TransferPulse] = []
        deepest, applied_joules = self._apply_event(event, transfers)
        self._refresh_all_active_occupancy()
        collapsed = self._homeostasis_collapse()
        self._enforce_budget(collapsed)
        self.last_events = [event]
        self.last_transfers = transfers
        trace = FrameTrace(0, 0, 0, 0, 1, len(transfers), 1 if deepest.address.depth > 1 else 0, len(collapsed), self.stack.active_count() > self.config.max_active_bubbles)
        consequences = self._performance_consequences([event], {id(event): applied_joules})
        return StepResult(self.time_seconds, self.config.target_frame_seconds, [event], transfers, [str(deepest.address)] if deepest.address.depth > 1 else [], collapsed, {}, self.stack.active_count(), consequences, trace)

    def query_point(self, point: Vec3) -> Dict[str, object]:
        root = self.stack.get_or_create_root_for(point)
        path = [root]
        cur = root
        while cur.children:
            child = cur.children.get(cur.child_index_for(point, self.config.subdivision_factor))
            if child is None: break
            path.append(child); cur = child
        local = cur.local_position(point)
        return {
            'coarse_address': str(root.address), 'deepest_address': str(cur.address), 'depth': cur.address.depth,
            'bubble_size': cur.size, 'local_position': local.as_tuple(), 'nucleus_distance': cur.nucleus_distance(point),
            'joule_load': round(cur.joule_load, 5), 'state': cur.state.value,
            'occupants': sorted(cur.occupancy.keys()), 'path': [str(b.address) for b in path],
        }

    def snapshots(self, active_only: bool = True) -> List[BubbleSnapshot]:
        out: List[BubbleSnapshot] = []
        for b in self.stack.all_bubbles():
            if active_only and not (b.joule_load > 0 or b.children or b.occupancy): continue
            out.append(BubbleSnapshot(str(b.address), b.address.depth, b.size, b.state.value, round(b.joule_load, 5), len(b.children), len(b.occupancy), sorted(b.occupancy.keys())))
        return sorted(out, key=lambda s: (s.depth, s.address))

    def jeremy_room_summary(self) -> Dict[str, object]:
        top = sorted(self.snapshots(), key=lambda s: s.joule_load, reverse=True)[:12]
        return {
            'time_seconds': round(self.time_seconds, 3),
            'active_bubble_count': self.stack.active_count(),
            'observed_root_count': len(self.stack.roots),
            'top_joule_regions': [asdict(s) for s in top],
            'recent_order_events': [self._event_dict(e) for e in self.last_events[-12:]],
            'recent_kinetic_backlash': [asdict(t) for t in self.last_transfers[-12:]],
            'performance_continuity': [asdict(c) for c in getattr(self, 'last_performance_consequences', [])[-8:]],
        }

    def validate_invariants(self) -> EngineInvariantReport:
        errors: List[str] = []
        active = self.stack.active_count()
        max_depth_seen = 0

        if active > self.config.max_active_bubbles:
            errors.append(f'active bubble count {active} exceeds budget {self.config.max_active_bubbles}')

        for idx, root in self.stack.roots.items():
            if root.address.depth != 1:
                errors.append(f'root {idx} has invalid depth {root.address.depth}')
            if root.address.root_index != idx:
                errors.append(f'root key/address mismatch: key={idx} address={root.address}')

        for bubble in self.stack.all_bubbles():
            max_depth_seen = max(max_depth_seen, bubble.address.depth)
            if bubble.size <= 0:
                errors.append(f'bubble {bubble.address} has non-positive size')
            if bubble.address.depth > self.config.max_depth:
                errors.append(f'bubble {bubble.address} exceeds max_depth')
            if bubble.joule_load < -1e-9:
                errors.append(f'bubble {bubble.address} has negative joule load')
            for oid, rec in bubble.occupancy.items():
                if rec.object_id != oid:
                    errors.append(f'bubble {bubble.address} occupancy key mismatch for {oid}')
                if not (0.0 <= rec.fraction_of_object <= 1.0 + 1e-6):
                    errors.append(f'bubble {bubble.address} invalid object fraction {rec.fraction_of_object}')
                if rec.intersection_volume < -1e-9:
                    errors.append(f'bubble {bubble.address} negative intersection volume')
            for idx, child in bubble.children.items():
                expected = bubble.child_bounds(idx, self.config.subdivision_factor)
                if child.origin != expected.min or abs(child.size - (expected.max.x - expected.min.x)) > 1e-9:
                    errors.append(f'child {child.address} bounds do not match parent index')

        return EngineInvariantReport(not errors, errors, active, len(self.stack.roots), max_depth_seen)

    def _performance_consequences(self, events: List[OrderEvent], event_joules: Dict[int, float]) -> List[PerformanceConsequence]:
        out: List[PerformanceConsequence] = []
        for i, event in enumerate(events):
            consequence = build_performance_consequence(
                event, event_index=i, applied_joules=event_joules.get(id(event), max(0.0, event.intensity)), objects=self.objects
            )
            if consequence is not None:
                out.append(consequence)
        self.last_performance_consequences = out
        return out

    def _event_dict(self, e: OrderEvent) -> Dict[str, object]:
        return {'type': e.event_type.value, 'origin': e.origin.as_tuple(), 'intensity': round(e.intensity, 5), 'source_id': e.source_id, 'target_id': e.target_id, 'direction': e.direction.as_tuple()}

    def _clear_occupancy(self, object_id: str) -> None:
        for b in self.stack.all_bubbles(): b.occupancy.pop(object_id, None)

    def _record_object(self, obj: SpatialObject) -> ObjectReport:
        recs: List[OccupancyRecord] = []
        contacts: List[SurfaceContact] = []
        for idx in self.stack.root_indices_for_bounds(obj.bounds):
            root = self.stack.get_or_create_root(idx)
            self._record_recursive(root, obj, recs, contacts)
        deepest = max([r.bubble_address.count('/') + 1 for r in recs], default=1)
        return ObjectReport(obj.object_id, obj.center.as_tuple(), obj.velocity.as_tuple(), recs, contacts, deepest)

    def _record_recursive(self, bubble: Bubble, obj: SpatialObject, recs: List[OccupancyRecord], contacts: List[SurfaceContact]) -> None:
        rec = self._occupancy_record(bubble, obj)
        if not rec: return
        bubble.occupancy[obj.object_id] = rec
        recs.append(rec); contacts.extend(rec.contacts)
        for child in bubble.children.values(): self._record_recursive(child, obj, recs, contacts)

    def _occupancy_record(self, bubble: Bubble, obj: SpatialObject) -> Optional[OccupancyRecord]:
        inter = obj.bounds.intersection(bubble.bounds)
        if inter is None: return None
        object_vol = max(obj.bounds.volume, 1e-12)
        bubble_vol = max(bubble.bounds.volume, 1e-12)
        local = bubble.local_position(inter.center)
        rec = OccupancyRecord(
            obj.object_id, str(bubble.address), inter.volume / object_vol, inter.volume / bubble_vol, inter.volume,
            local.as_tuple(), bubble.nucleus_distance(inter.center), []
        )
        rec.contacts = self._surface_contacts(bubble, obj.object_id, obj.bounds)
        return rec

    def _surface_contacts(self, bubble: Bubble, oid: str, bounds: AABB) -> List[SurfaceContact]:
        tol = bubble.size * self.config.contact_tolerance_fraction
        faces = [
            ('x','-', bounds.min.x - bubble.origin.x), ('x','+', bubble.origin.x + bubble.size - bounds.max.x),
            ('y','-', bounds.min.y - bubble.origin.y), ('y','+', bubble.origin.y + bubble.size - bounds.max.y),
            ('z','-', bounds.min.z - bubble.origin.z), ('z','+', bubble.origin.z + bubble.size - bounds.max.z),
        ]
        out: List[SurfaceContact] = []
        for axis, side, signed_gap in faces:
            if abs(signed_gap) <= tol:
                prox = 1.0 - abs(signed_gap) / max(tol, 1e-12)
                penetration = max(0.0, -signed_gap) / max(bubble.size, 1e-12)
                out.append(SurfaceContact(str(bubble.address), oid, axis, side, round(penetration, 5), round(prox, 5)))
        return out

    def _motion_events(self, obj: SpatialObject, prev: SpatialObject, dt: float) -> List[OrderEvent]:
        out: List[OrderEvent] = []
        dist = obj.center.distance_to(prev.center)
        normalized_dist = dist / self.config.root_bubble_size
        direction = (obj.center - prev.center).normalized()
        if normalized_dist >= self.config.motion_threshold_fraction:
            typ = OrderEventType.VOLATILE_MOTION if normalized_dist >= self.config.volatile_motion_fraction else OrderEventType.MOTION
            out.append(OrderEvent(typ, obj.center, normalized_dist, source_id=obj.object_id, direction=direction))
        dv = (obj.velocity - prev.velocity).length() * dt / self.config.root_bubble_size
        if dv >= self.config.velocity_change_threshold_fraction:
            out.append(OrderEvent(OrderEventType.VELOCITY_CHANGE, obj.center, dv, source_id=obj.object_id, direction=direction))
        old_roots = {str(self.stack.get_or_create_root(idx).address) for idx in self.stack.root_indices_for_bounds(prev.bounds)}
        new_roots = {str(self.stack.get_or_create_root(idx).address) for idx in self.stack.root_indices_for_bounds(obj.bounds)}
        if old_roots != new_roots:
            out.append(OrderEvent(OrderEventType.BOUNDARY_CROSSING, obj.center, 1.0, source_id=obj.object_id, direction=direction, metadata={'from': sorted(old_roots), 'to': sorted(new_roots)}))
        return out

    def _order_state_events(self) -> List[OrderEvent]:
        out: List[OrderEvent] = []
        for bubble in self.stack.all_bubbles():
            new_sig = bubble.recompute_order_signature()
            if bubble.order_signature and bubble.order_signature != new_sig:
                # Difference size is deliberately simple and deterministic. More advanced scoring can plug in here.
                old_set, new_set = set(bubble.order_signature), set(new_sig)
                change = len(old_set.symmetric_difference(new_set)) / max(1, len(old_set | new_set))
                out.append(OrderEvent(OrderEventType.STRUCTURAL_REORDER, bubble.center, change * self.config.order_change_weight, metadata={'bubble': str(bubble.address)}))
            bubble.order_signature = new_sig
        return out

    def _decay(self, dt: float) -> None:
        for b in self.stack.all_bubbles():
            b.joule_load = max(0.0, b.joule_load - self.config.decay_per_second * dt)
            if b.joule_load <= self.config.collapse_threshold and b.children: b.state = BubbleState.COOLING
            elif b.joule_load <= self.config.collapse_threshold: b.state = BubbleState.STABLE

    def _apply_event(self, event: OrderEvent, transfers: List[TransferPulse]) -> Tuple[Bubble, float]:
        root = self.stack.get_or_create_root_for(event.origin)
        joules = max(0.0, event.intensity) * EVENT_WEIGHTS.get(event.event_type, 1.0)
        self._energize(root, joules)
        deepest = self._refine_around(root, event.origin, joules, event.depth_hint)
        self._spatial_transfer(root, event, joules, transfers)
        self._semantic_transfer(event, joules, transfers)
        return deepest, joules

    def _energize(self, bubble: Bubble, joules: float) -> None:
        if joules <= 0: return
        bubble.joule_load = min(self.config.max_joule_load, bubble.joule_load + joules)
        bubble.last_touched_at = self.time_seconds
        bubble.state = BubbleState.REFINING if bubble.joule_load >= self.config.refine_threshold else BubbleState.WATCHING

    def _refine_around(self, bubble: Bubble, point: Vec3, joules: float, depth_hint: Optional[int] = None) -> Bubble:
        cur = bubble
        desired_depth = depth_hint or self.config.max_depth
        while (
            cur.address.depth < min(desired_depth, self.config.max_depth)
            and cur.size / self.config.subdivision_factor >= self.config.min_child_size
            and cur.joule_load >= self.config.refine_threshold
            and self.stack.active_count() < self.config.max_active_bubbles
        ):
            child = cur.get_or_create_child_for(point, self.config.subdivision_factor)
            # Refinement receives a damped copy of the event energy. It must
            # not recursively amplify parent Joule Load into runaway numbers.
            self._energize(child, joules * (0.72 ** cur.address.depth))
            cur = child
        return cur

    def _spatial_transfer(self, root: Bubble, event: OrderEvent, joules: float, transfers: List[TransferPulse]) -> None:
        if joules <= 0: return
        if event.event_type not in {OrderEventType.VOLATILE_MOTION, OrderEventType.VELOCITY_CHANGE, OrderEventType.BOUNDARY_CROSSING, OrderEventType.SURFACE_CONTACT, OrderEventType.STRUCTURAL_REORDER, OrderEventType.TRANSFER}:
            return
        root_idx = root.address.root_index
        if root_idx is None: return
        r = self.config.neighbor_transfer_radius
        direction = event.direction.normalized()
        for dx, dy, dz in product(range(-r, r + 1), repeat=3):
            if dx == dy == dz == 0: continue
            offset = Vec3(dx, dy, dz)
            manhattan = abs(dx) + abs(dy) + abs(dz)
            if manhattan > r + 1: continue
            # Bias transfer in direction of motion but still allow local shock spread.
            directional_bias = 1.0 + max(0.0, direction.dot(offset.normalized())) if direction.length() else 1.0
            amount = joules * self.config.spatial_transfer_decay * directional_bias / max(1, manhattan)
            if amount <= self.config.collapse_threshold: continue
            idx = (root_idx[0] + dx, root_idx[1] + dy, root_idx[2] + dz)
            # Kinetic Backlash may pre-warm adjacent coarse bubbles, but it must not
            # blow the budget by inventing an infinite halo. Existing observed roots
            # can receive energy; new roots are created only while budget remains.
            if idx not in self.stack.roots and self.stack.active_count() + 1 > self.config.max_active_bubbles:
                continue
            nb = self.stack.get_or_create_root(idx)
            self._energize(nb, amount)
            transfers.append(TransferPulse(str(root.address), str(nb.address), round(amount, 5), 'spatial', event.source_id, event.event_type.value))

    def _semantic_transfer(self, event: OrderEvent, joules: float, transfers: List[TransferPulse]) -> None:
        if not event.source_id or joules <= 0: return
        src_obj = self.objects.get(event.source_id)
        src_addr = str(self.stack.get_or_create_root_for(src_obj.center).address) if src_obj else 'unknown'
        for target_id, weight in self.semantic_graph.neighbors(event.source_id).items():
            target = self.objects.get(target_id)
            if not target: continue
            amount = joules * self.config.semantic_transfer_decay * max(0.0, weight)
            root = self.stack.get_or_create_root_for(target.center)
            self._energize(root, amount)
            self._refine_around(root, target.center, amount, event.depth_hint)
            transfers.append(TransferPulse(src_addr, str(root.address), round(amount, 5), 'semantic', event.source_id, f'{event.source_id}->{target_id}'))

    def _refresh_all_active_occupancy(self) -> None:
        # Clear only active child occupancy and rebuild; roots already rebuilt during frame ingestion, but this is safe.
        for b in self.stack.all_bubbles(): b.occupancy.clear()
        for obj in self.objects.values(): self._record_object(obj)

    def _homeostasis_collapse(self) -> List[str]:
        collapsed: List[str] = []
        for root in self.stack.roots.values(): self._collapse_children(root, collapsed)
        return collapsed

    def _collapse_children(self, bubble: Bubble, collapsed: List[str]) -> None:
        for idx, child in list(bubble.children.items()):
            self._collapse_children(child, collapsed)
            if child.joule_load <= self.config.collapse_threshold and not child.children:
                collapsed.append(str(child.address)); del bubble.children[idx]
            elif child.joule_load <= self.config.collapse_threshold:
                child.state = BubbleState.COOLING

    def _enforce_budget(self, collapsed: List[str]) -> None:
        while self.stack.active_count() > self.config.max_active_bubbles:
            leaves: List[Tuple[float, Bubble, Tuple[int, int, int]]] = []
            for parent in self.stack.all_bubbles():
                for idx, child in parent.children.items():
                    if not child.children:
                        leaves.append((child.joule_load, parent, idx))
            if leaves:
                _, parent, idx = min(leaves, key=lambda x: x[0])
                collapsed.append(str(parent.children[idx].address)); del parent.children[idx]
                continue

            # Last-resort root pruning. The persistent coarse layer means roots
            # are not removed during ordinary refinement/collapse, but a hard
            # budget is still a hard budget. Only empty, childless, cold roots
            # can be discarded, preserving any root that currently contains
            # tracked matter or active detail.
            root_candidates = [
                (root.joule_load, idx) for idx, root in self.stack.roots.items()
                if not root.children and not root.occupancy
            ]
            if not root_candidates:
                break
            _, idx = min(root_candidates, key=lambda x: x[0])
            collapsed.append(str(self.stack.roots[idx].address)); del self.stack.roots[idx]

