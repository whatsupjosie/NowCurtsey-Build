"""Bubble Stack: A Physics-Informed Kinetic Performance Continuity System."""

from .core import AABB, BubbleConfig, OrderEvent, OrderEventType, Vec3
from .engine import BubbleStackEngine, FrameObject, StepResult
from .performance import PerformanceConsequence, KineticEstimate, MotionCorrection, ConsequenceType
from .sandbox import (
    ActorPhysicalProfile,
    EnvironmentConfig,
    PubBlockSandbox,
    SandboxAction,
    SandboxOutcome,
    run_pub_block_demo,
    run_pub_block_option_demo,
)

__all__ = [
    "AABB", "BubbleConfig", "OrderEvent", "OrderEventType", "Vec3",
    "BubbleStackEngine", "FrameObject", "StepResult",
    "PerformanceConsequence", "KineticEstimate", "MotionCorrection", "ConsequenceType",
    "PubBlockSandbox", "SandboxAction", "SandboxOutcome", "run_pub_block_demo", "run_pub_block_option_demo",
    "ActorPhysicalProfile", "EnvironmentConfig",
]

