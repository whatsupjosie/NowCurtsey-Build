from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import floor, sqrt
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other: 'Vec3') -> 'Vec3': return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)
    def __sub__(self, other: 'Vec3') -> 'Vec3': return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)
    def __mul__(self, k: float) -> 'Vec3': return Vec3(self.x * k, self.y * k, self.z * k)
    def __truediv__(self, k: float) -> 'Vec3':
        if k == 0: raise ZeroDivisionError('Vec3 division by zero')
        return Vec3(self.x / k, self.y / k, self.z / k)
    def dot(self, other: 'Vec3') -> float: return self.x * other.x + self.y * other.y + self.z * other.z
    def length(self) -> float: return sqrt(self.dot(self))
    def distance_to(self, other: 'Vec3') -> float: return (self - other).length()
    def normalized(self) -> 'Vec3':
        l = self.length()
        return Vec3(0, 0, 0) if l == 0 else self / l
    def as_tuple(self) -> Tuple[float, float, float]: return (self.x, self.y, self.z)


@dataclass(frozen=True, slots=True)
class AABB:
    min: Vec3
    max: Vec3

    def __post_init__(self) -> None:
        if self.max.x < self.min.x or self.max.y < self.min.y or self.max.z < self.min.z:
            raise ValueError('AABB max must be >= min on every axis')

    @property
    def center(self) -> Vec3:
        return Vec3((self.min.x + self.max.x) / 2, (self.min.y + self.max.y) / 2, (self.min.z + self.max.z) / 2)

    @property
    def size(self) -> Vec3:
        return Vec3(self.max.x - self.min.x, self.max.y - self.min.y, self.max.z - self.min.z)

    @property
    def volume(self) -> float:
        s = self.size
        return max(0.0, s.x) * max(0.0, s.y) * max(0.0, s.z)

    @classmethod
    def from_center_size(cls, center: Vec3, size: Vec3) -> 'AABB':
        half = size * 0.5
        return cls(center - half, center + half)

    @classmethod
    def from_center_radius(cls, center: Vec3, radius: float) -> 'AABB':
        r = max(0.0, radius)
        return cls.from_center_size(center, Vec3(r * 2, r * 2, r * 2))

    def intersects(self, other: 'AABB') -> bool:
        return not (
            self.max.x <= other.min.x or self.min.x >= other.max.x or
            self.max.y <= other.min.y or self.min.y >= other.max.y or
            self.max.z <= other.min.z or self.min.z >= other.max.z
        )

    def intersection(self, other: 'AABB') -> Optional['AABB']:
        if not self.intersects(other): return None
        return AABB(
            Vec3(max(self.min.x, other.min.x), max(self.min.y, other.min.y), max(self.min.z, other.min.z)),
            Vec3(min(self.max.x, other.max.x), min(self.max.y, other.max.y), min(self.max.z, other.max.z)),
        )

    def translated(self, delta: Vec3) -> 'AABB':
        return AABB(self.min + delta, self.max + delta)


@dataclass(frozen=True, slots=True)
class BubbleAddress:
    levels: Tuple[Tuple[int, int, int], ...] = ()
    def child(self, idx: Tuple[int, int, int]) -> 'BubbleAddress': return BubbleAddress(self.levels + (idx,))
    def parent(self) -> Optional['BubbleAddress']: return None if not self.levels else BubbleAddress(self.levels[:-1])
    @property
    def depth(self) -> int: return len(self.levels)
    @property
    def root_index(self) -> Optional[Tuple[int, int, int]]: return self.levels[0] if self.levels else None
    def __str__(self) -> str: return 'root' if not self.levels else '/'.join(f'({x},{y},{z})' for x, y, z in self.levels)


class BubbleState(str, Enum):
    STABLE = 'stable'
    WATCHING = 'watching'
    REFINING = 'refining'
    COOLING = 'cooling'


class OrderEventType(str, Enum):
    OBJECT_ENTRY = 'object_entry'
    OBJECT_EXIT = 'object_exit'
    MOTION = 'motion'
    VOLATILE_MOTION = 'volatile_motion'
    VELOCITY_CHANGE = 'velocity_change'
    BOUNDARY_CROSSING = 'boundary_crossing'
    SURFACE_CONTACT = 'surface_contact'
    STRUCTURAL_REORDER = 'structural_reorder'
    SEMANTIC_ATTENTION = 'semantic_attention'
    CAMERA_ATTENTION = 'camera_attention'
    SPEECH = 'speech'
    TRANSFER = 'kinetic_transfer'


@dataclass(slots=True)
class OrderEvent:
    event_type: OrderEventType
    origin: Vec3
    intensity: float
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    direction: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    radius: float = 0.0
    depth_hint: Optional[int] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SurfaceContact:
    bubble_address: str
    object_id: str
    axis: str
    side: str
    penetration_fraction: float
    proximity: float


@dataclass(slots=True)
class OccupancyRecord:
    object_id: str
    bubble_address: str
    fraction_of_object: float
    fraction_of_bubble: float
    intersection_volume: float
    local_center: Tuple[float, float, float]
    nucleus_distance: float
    contacts: List[SurfaceContact] = field(default_factory=list)


@dataclass(slots=True)
class SpatialObject:
    object_id: str
    bounds: AABB
    semantic_tags: Tuple[str, ...] = ()
    velocity: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    previous_velocity: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))

    @property
    def center(self) -> Vec3: return self.bounds.center


@dataclass(slots=True)
class BubbleConfig:
    root_bubble_size: float = 1.0
    subdivision_factor: int = 3
    max_depth: int = 6
    min_child_size: float = 0.002
    refine_threshold: float = 1.0
    collapse_threshold: float = 0.22
    decay_per_second: float = 0.55
    neighbor_transfer_radius: int = 1
    spatial_transfer_decay: float = 0.46
    semantic_transfer_decay: float = 0.62
    occupancy_scan_limit: int = 20000
    max_active_bubbles: int = 4000
    motion_threshold_fraction: float = 0.015
    volatile_motion_fraction: float = 0.22
    velocity_change_threshold_fraction: float = 0.08
    contact_tolerance_fraction: float = 0.035
    max_joule_load: float = 100.0
    order_change_weight: float = 1.0
    contact_weight: float = 0.35
    target_frame_seconds: float = 1.0 / 30.0

    def __post_init__(self) -> None:
        if self.root_bubble_size <= 0: raise ValueError('root_bubble_size must be positive')
        if self.subdivision_factor < 2: raise ValueError('subdivision_factor must be >= 2')
        if self.max_depth < 1: raise ValueError('max_depth must be >= 1')


@dataclass(slots=True)
class Bubble:
    address: BubbleAddress
    origin: Vec3
    size: float
    state: BubbleState = BubbleState.STABLE
    joule_load: float = 0.0
    order_signature: Tuple[Tuple[str, float, Tuple[float, float, float]], ...] = ()
    last_touched_at: float = 0.0
    children: Dict[Tuple[int, int, int], 'Bubble'] = field(default_factory=dict)
    occupancy: Dict[str, OccupancyRecord] = field(default_factory=dict)

    @property
    def bounds(self) -> AABB: return AABB(self.origin, Vec3(self.origin.x + self.size, self.origin.y + self.size, self.origin.z + self.size))
    @property
    def center(self) -> Vec3:
        h = self.size / 2
        return Vec3(self.origin.x + h, self.origin.y + h, self.origin.z + h)

    def local_position(self, point: Vec3) -> Vec3:
        h = self.size / 2
        c = self.center
        return Vec3((point.x - c.x) / h, (point.y - c.y) / h, (point.z - c.z) / h)

    def nucleus_distance(self, point: Vec3) -> float:
        h = self.size / 2
        return 0.0 if h <= 0 else self.center.distance_to(point) / h

    def child_index_for(self, point: Vec3, factor: int) -> Tuple[int, int, int]:
        rel = point - self.origin
        child_size = self.size / factor
        return (
            min(factor - 1, max(0, floor(rel.x / child_size))),
            min(factor - 1, max(0, floor(rel.y / child_size))),
            min(factor - 1, max(0, floor(rel.z / child_size))),
        )

    def child_bounds(self, idx: Tuple[int, int, int], factor: int) -> AABB:
        s = self.size / factor
        o = Vec3(self.origin.x + idx[0] * s, self.origin.y + idx[1] * s, self.origin.z + idx[2] * s)
        return AABB(o, Vec3(o.x + s, o.y + s, o.z + s))

    def get_or_create_child(self, idx: Tuple[int, int, int], factor: int) -> 'Bubble':
        if idx not in self.children:
            b = self.child_bounds(idx, factor)
            self.children[idx] = Bubble(self.address.child(idx), b.min, b.max.x - b.min.x)
        return self.children[idx]

    def get_or_create_child_for(self, point: Vec3, factor: int) -> 'Bubble':
        return self.get_or_create_child(self.child_index_for(point, factor), factor)

    def iter_descendants(self) -> Iterable['Bubble']:
        for child in self.children.values():
            yield child
            yield from child.iter_descendants()

    def recompute_order_signature(self) -> Tuple[Tuple[str, float, Tuple[float, float, float]], ...]:
        return tuple(sorted(
            (oid, round(rec.fraction_of_bubble, 4), tuple(round(v, 3) for v in rec.local_center))
            for oid, rec in self.occupancy.items()
        ))


@dataclass(slots=True)
class BubbleStack:
    config: BubbleConfig
    roots: Dict[Tuple[int, int, int], Bubble] = field(default_factory=dict)

    def root_index_for(self, p: Vec3) -> Tuple[int, int, int]:
        s = self.config.root_bubble_size
        return (floor(p.x / s), floor(p.y / s), floor(p.z / s))

    def root_bounds_for_index(self, idx: Tuple[int, int, int]) -> AABB:
        s = self.config.root_bubble_size
        o = Vec3(idx[0] * s, idx[1] * s, idx[2] * s)
        return AABB(o, Vec3(o.x + s, o.y + s, o.z + s))

    def get_or_create_root(self, idx: Tuple[int, int, int]) -> Bubble:
        if idx not in self.roots:
            b = self.root_bounds_for_index(idx)
            self.roots[idx] = Bubble(BubbleAddress((idx,)), b.min, self.config.root_bubble_size)
        return self.roots[idx]

    def get_or_create_root_for(self, p: Vec3) -> Bubble:
        return self.get_or_create_root(self.root_index_for(p))

    def root_indices_for_bounds(self, bounds: AABB) -> List[Tuple[int, int, int]]:
        eps = 1e-12
        mn = self.root_index_for(bounds.min)
        mx = self.root_index_for(Vec3(bounds.max.x - eps, bounds.max.y - eps, bounds.max.z - eps))
        out: List[Tuple[int, int, int]] = []
        for x in range(mn[0], mx[0] + 1):
            for y in range(mn[1], mx[1] + 1):
                for z in range(mn[2], mx[2] + 1): out.append((x, y, z))
        if len(out) > self.config.occupancy_scan_limit:
            raise RuntimeError('occupancy spans too many roots')
        return out

    def all_bubbles(self) -> Iterable[Bubble]:
        for root in self.roots.values():
            yield root
            yield from root.iter_descendants()

    def active_count(self) -> int:
        return sum(1 for _ in self.all_bubbles())

