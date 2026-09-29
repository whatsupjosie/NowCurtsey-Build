# Spark Assignment — PubCast Tooling Evaluation

Work ONLY inside SPARK_ASSIGNMENT unless explicitly authorized otherwise. The files under source/ are copies made for experimentation. Do not modify canonical files elsewhere on this branch.

Goal: test consequential open-source tooling developments against PubCast without broad refactors or dependency churn.

First map what the supplied code actually implements: Godot/runtime rendering, Blender/GLB assets, avatars/skeletons, MediaPipe/body/face tracking, retargeting, lip sync/visemes, audio/voice timing, replayable performance, 2.5D/3D scenes, voxel/world rendering, cameras, and event/performance recording. Classify each as working, incomplete, documented-only, obsolete, or missing.

Core principle:
CAPTURE -> CANONICAL TIMESTAMPED PERFORMANCE DATA -> RETARGETING/INTERPRETATION -> AVATAR -> LIVE RENDER.
A recording should ideally replay through different avatars, cameras, sets and render quality without rewriting capture data.

Experiments:
1. Performance portability: determine whether one recorded performance can drive two differently rigged GLB avatars without rewriting the recording. Identify avatar-specific coupling and prototype only the smallest adapter needed.
2. MediaPipe/FreeMoCap interchange: do not replace MediaPipe. Determine whether current FreeMoCap output can map into PubCast's existing/canonical performance representation. Compare skeleton mapping, coordinates, timing, jitter, foot sliding, occlusion, CPU/RAM and preprocessing.
3. Avatar Foundry/facial standardization: evaluate MediaPipe facial blendshapes and ARKit-style 52 blendshape vocabulary on ONE disposable avatar. Test record on A -> unchanged recording -> replay on B.
4. Low-cost remote face capture: if practical, prototype phone/browser local face tracking -> lightweight network packets -> PubCast input/recording. Measure latency, bandwidth, dropped packets, host CPU and audio sync.
5. Godot renderer benchmark: isolated fixture only; do not migrate canonical PubCast. Compare current configuration with relevant Compatibility/Mobile paths using a representative studio and measure FPS/frame time, RAM/VRAM, load time and visual/feature differences.
6. Blender/GLB pipeline: isolated asset only. Test current Blender 5.2 LTS workflow for armatures, bone names, animation, shape keys, materials, textures, GLB export/Godot import, morph preservation, scale/orientation and script/API compatibility.

Hardware rule: inexpensive hardware remains a first-class target. Do not assume a discrete GPU, large VRAM, workstation CPU, cloud inference, paid APIs, or expensive mocap equipment. Prefer deterministic animation, parameterized faces, lightweight tracking, offline preprocessing and graceful degradation.

Safety: no broad refactors, no canonical dependency upgrades, no unrelated fixes, no deleting legacy code, no silent cloud dependencies. Every experimental change must be easy to remove.

Deliverable: existing-system map; experiment results (PASS/PARTIAL/FAIL/NOT PRACTICAL, measurements, files changed, risks); tooling verdicts TEST NOW/WATCH/IGNORE FOR NOW; coupling findings; smallest evidence-supported next change; and preserved scripts/adapters/benchmarks/sample packets.

Evidence beats novelty. If existing PubCast performs better, say so and leave it alone.
