"""
Ethereal Avatar 3D Model Generator for PubCast AI
Creates beautiful translucent, glowing avatar models inspired by ethereal energy beings.

Produces male and female avatar models with:
- Translucent, glowing blue aesthetic
- Smooth, flowing geometry
- Proper UV mapping for energy effects
- Compatible with standard PubCast skeleton
- Optimized for real-time WebGL rendering
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import base64


class Vector3:
    """Simple 3D vector for model generation"""
    def __init__(self, x: float = 0, y: float = 0, z: float = 0):
        self.x, self.y, self.z = x, y, z
    
    def __add__(self, other):
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __mul__(self, scalar):
        return Vector3(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def normalize(self):
        length = math.sqrt(self.x**2 + self.y**2 + self.z**2)
        if length > 0:
            return Vector3(self.x/length, self.y/length, self.z/length)
        return Vector3(0, 0, 0)
    
    def to_list(self) -> List[float]:
        return [self.x, self.y, self.z]


class EtherealAvatar:
    """
    Generator for ethereal avatar 3D models with translucent, glowing aesthetic.
    
    Creates humanoid figures with:
    - Smooth, organic topology
    - Proper skeletal binding
    - UV coordinates for energy effects
    - Optimized for real-time rendering
    """
    
    def __init__(self):
        self.vertices: List[Vector3] = []
        self.normals: List[Vector3] = []
        self.uvs: List[Tuple[float, float]] = []
        self.faces: List[Tuple[int, int, int]] = []
        self.joint_weights: Dict[int, Dict[str, float]] = {}  # vertex_index -> {joint_name: weight}
        
    def create_ethereal_male(self) -> Dict:
        """Generate ethereal male avatar with masculine proportions"""
        self._clear_data()
        
        # Body proportions (slightly broader shoulders, narrower hips)
        torso_width = 0.22
        hip_width = 0.18
        height = 1.75
        
        # Generate body segments
        self._create_head(height * 0.97, 0.08, gender="male")
        self._create_torso(height * 0.55, height * 0.85, torso_width, hip_width, gender="male") 
        self._create_arms(height * 0.8, 0.28, gender="male")
        self._create_legs(height * 0.52, hip_width, gender="male")
        
        return self._export_model_data("ethereal_male")
    
    def create_ethereal_female(self) -> Dict:
        """Generate ethereal female avatar with feminine proportions"""
        self._clear_data()
        
        # Body proportions (narrower shoulders, wider hips, curves)
        torso_width = 0.19
        hip_width = 0.21
        height = 1.68
        
        # Generate body segments
        self._create_head(height * 0.97, 0.075, gender="female")
        self._create_torso(height * 0.55, height * 0.85, torso_width, hip_width, gender="female")
        self._create_arms(height * 0.78, 0.25, gender="female")
        self._create_legs(height * 0.52, hip_width, gender="female")
        
        return self._export_model_data("ethereal_female")
    
    def _clear_data(self):
        """Reset model data for new avatar"""
        self.vertices.clear()
        self.normals.clear()
        self.uvs.clear()
        self.faces.clear()
        self.joint_weights.clear()
    
    def _create_head(self, y_pos: float, radius: float, gender: str):
        """Create ethereal head with smooth geometry"""
        segments = 16
        rings = 12
        
        for ring in range(rings + 1):
            v_angle = math.pi * ring / rings  # 0 to π
            ring_y = y_pos + radius * math.cos(v_angle)
            ring_radius = radius * math.sin(v_angle)
            
            # Slight gender differences in head shape
            if gender == "female" and 0.2 < (ring / rings) < 0.8:
                ring_radius *= 0.95  # Slightly more delicate features
            
            for segment in range(segments):
                h_angle = 2 * math.pi * segment / segments  # 0 to 2π
                
                x = ring_radius * math.cos(h_angle)
                z = ring_radius * math.sin(h_angle)
                
                vertex = Vector3(x, ring_y, z)
                normal = vertex.normalize()
                
                self.vertices.append(vertex)
                self.normals.append(normal)
                
                # UV mapping for energy effects
                u = segment / segments
                v = ring / rings
                self.uvs.append((u, v))
                
                # Bind to head joints
                vertex_idx = len(self.vertices) - 1
                self.joint_weights[vertex_idx] = {"head": 0.8, "neck": 0.2}
        
        # Create faces
        self._create_sphere_faces(segments, rings)
    
    def _create_torso(self, y_bottom: float, y_top: float, width_top: float, width_bottom: float, gender: str):
        """Create ethereal torso with gender-appropriate curves"""
        segments = 12
        height_segments = 8
        
        for h_seg in range(height_segments + 1):
            h_ratio = h_seg / height_segments
            y = y_bottom + (y_top - y_bottom) * h_ratio
            
            # Create curves based on gender
            if gender == "female":
                # Feminine curves - narrower waist, wider at bust and hips
                if h_ratio < 0.3:  # Hip area
                    width = width_bottom
                elif h_ratio < 0.6:  # Waist
                    width = width_bottom * 0.75
                else:  # Bust area
                    width = width_top * 1.1
            else:
                # Masculine - straighter, broader shoulders
                width = width_bottom + (width_top - width_bottom) * (h_ratio * 0.8 + 0.2)
            
            for segment in range(segments):
                angle = 2 * math.pi * segment / segments
                x = width * math.cos(angle)
                z = width * math.sin(angle)
                
                vertex = Vector3(x, y, z)
                normal = Vector3(math.cos(angle), 0, math.sin(angle))
                
                self.vertices.append(vertex)
                self.normals.append(normal)
                self.uvs.append((segment / segments, h_ratio))
                
                # Skeletal binding based on height
                vertex_idx = len(self.vertices) - 1
                if h_ratio > 0.8:
                    self.joint_weights[vertex_idx] = {"chest": 0.7, "spine_03": 0.3}
                elif h_ratio > 0.6:
                    self.joint_weights[vertex_idx] = {"spine_03": 0.6, "spine_02": 0.4}
                elif h_ratio > 0.4:
                    self.joint_weights[vertex_idx] = {"spine_02": 0.6, "spine_01": 0.4}
                else:
                    self.joint_weights[vertex_idx] = {"spine_01": 0.5, "hips": 0.5}
        
        # Create torso faces
        self._create_cylinder_faces(segments, height_segments)
    
    def _create_arms(self, shoulder_height: float, arm_length: float, gender: str):
        """Create ethereal arms with proper proportions"""
        segments = 8
        
        # Arm thickness varies by gender
        upper_radius = 0.035 if gender == "female" else 0.04
        lower_radius = 0.028 if gender == "female" else 0.032
        
        for side in ["left", "right"]:
            side_mult = -1 if side == "left" else 1
            
            # Upper arm
            start_pos = Vector3(side_mult * 0.17, shoulder_height, 0)
            mid_pos = Vector3(side_mult * 0.45, shoulder_height, 0)
            end_pos = Vector3(side_mult * 0.7, shoulder_height, 0)
            
            # Create arm segments
            self._create_arm_segment(start_pos, mid_pos, upper_radius, segments, f"upperarm_{side[0]}")
            self._create_arm_segment(mid_pos, end_pos, lower_radius, segments, f"lowerarm_{side[0]}")
            
            # Hand (simplified for ethereal effect)
            hand_pos = Vector3(side_mult * 0.75, shoulder_height, 0)
            self._create_hand(hand_pos, side[0], gender)
    
    def _create_legs(self, hip_height: float, hip_width: float, gender: str):
        """Create ethereal legs with proper proportions"""
        segments = 8
        
        # Leg thickness varies by gender
        upper_radius = 0.055 if gender == "female" else 0.06
        lower_radius = 0.04 if gender == "female" else 0.045
        
        for side in ["left", "right"]:
            side_mult = -1 if side == "left" else 1
            
            # Hip to knee
            hip_pos = Vector3(side_mult * hip_width/2, hip_height, 0)
            knee_pos = Vector3(side_mult * hip_width/2, hip_height * 0.5, 0)
            ankle_pos = Vector3(side_mult * hip_width/2, 0.08, 0)
            
            # Create leg segments
            self._create_arm_segment(hip_pos, knee_pos, upper_radius, segments, f"thigh_{side[0]}")
            self._create_arm_segment(knee_pos, ankle_pos, lower_radius, segments, f"calf_{side[0]}")
            
            # Foot (simplified)
            foot_pos = Vector3(side_mult * hip_width/2, 0.0, 0.1)
            self._create_foot(foot_pos, side[0], gender)
    
    def _create_arm_segment(self, start: Vector3, end: Vector3, radius: float, segments: int, joint_name: str):
        """Create cylindrical arm/leg segment"""
        direction = (end + start * -1).normalize()
        
        # Create rings at start and end
        for t in [0, 1]:
            pos = start + (end + start * -1) * t
            
            for segment in range(segments):
                angle = 2 * math.pi * segment / segments
                
                # Create perpendicular vectors for cylinder
                if abs(direction.y) < 0.9:
                    right = Vector3(direction.z, 0, -direction.x).normalize()
                else:
                    right = Vector3(1, 0, 0)
                
                up = Vector3(
                    direction.y * right.z - direction.z * right.y,
                    direction.z * right.x - direction.x * right.z,
                    direction.x * right.y - direction.y * right.x
                )
                
                x = pos.x + radius * (right.x * math.cos(angle) + up.x * math.sin(angle))
                y = pos.y + radius * (right.y * math.cos(angle) + up.y * math.sin(angle))
                z = pos.z + radius * (right.z * math.cos(angle) + up.z * math.sin(angle))
                
                vertex = Vector3(x, y, z)
                normal = Vector3(x - pos.x, 0, z - pos.z).normalize()  # Radial normal
                
                self.vertices.append(vertex)
                self.normals.append(normal)
                self.uvs.append((segment / segments, t))
                
                # Bind to appropriate joint
                vertex_idx = len(self.vertices) - 1
                self.joint_weights[vertex_idx] = {joint_name: 1.0}
    
    def _create_hand(self, pos: Vector3, side: str, gender: str):
        """Create simplified ethereal hand"""
        # Just a small sphere for ethereal effect
        radius = 0.025 if gender == "female" else 0.028
        segments = 8
        
        for ring in range(3):
            for segment in range(segments):
                angle = 2 * math.pi * segment / segments
                x = pos.x + radius * math.cos(angle) * (1 - ring * 0.3)
                y = pos.y
                z = pos.z + radius * math.sin(angle) * (1 - ring * 0.3)
                
                vertex = Vector3(x, y, z)
                normal = Vector3(math.cos(angle), 0, math.sin(angle))
                
                self.vertices.append(vertex)
                self.normals.append(normal)
                self.uvs.append((segment / segments, ring / 2))
                
                vertex_idx = len(self.vertices) - 1
                self.joint_weights[vertex_idx] = {f"hand_{side}": 1.0}
    
    def _create_foot(self, pos: Vector3, side: str, gender: str):
        """Create simplified ethereal foot"""
        # Elongated sphere for foot shape
        radius = 0.03
        segments = 6
        
        for ring in range(4):
            for segment in range(segments):
                angle = 2 * math.pi * segment / segments
                x = pos.x + radius * math.cos(angle) * 0.8
                y = pos.y + radius * 0.3 * ring
                z = pos.z + radius * math.sin(angle) * 1.5
                
                vertex = Vector3(x, y, z)
                normal = Vector3(math.cos(angle), 0, math.sin(angle))
                
                self.vertices.append(vertex)
                self.normals.append(normal)
                self.uvs.append((segment / segments, ring / 3))
                
                vertex_idx = len(self.vertices) - 1
                self.joint_weights[vertex_idx] = {f"foot_{side}": 1.0}
    
    def _create_sphere_faces(self, segments: int, rings: int):
        """Create triangular faces for sphere geometry"""
        for ring in range(rings):
            for segment in range(segments):
                # Current ring vertices
                current = ring * segments + segment
                next_segment = ring * segments + ((segment + 1) % segments)
                
                # Next ring vertices
                next_ring = (ring + 1) * segments + segment
                next_ring_next = (ring + 1) * segments + ((segment + 1) % segments)
                
                if ring < rings:  # Not the last ring
                    # Create two triangles per quad
                    self.faces.append((current, next_ring, next_segment))
                    self.faces.append((next_segment, next_ring, next_ring_next))
    
    def _create_cylinder_faces(self, segments: int, height_segments: int):
        """Create triangular faces for cylindrical geometry"""
        for h in range(height_segments):
            for s in range(segments):
                # Current vertices
                current = h * segments + s
                next_s = h * segments + ((s + 1) % segments)
                next_h = (h + 1) * segments + s
                next_h_s = (h + 1) * segments + ((s + 1) % segments)
                
                # Create two triangles per quad
                self.faces.append((current, next_h, next_s))
                self.faces.append((next_s, next_h, next_h_s))
    
    def _export_model_data(self, name: str) -> Dict:
        """Export model data in GLB-compatible format"""
        
        # Convert to flat arrays
        positions = []
        normals = []
        uvs = []
        
        for vertex in self.vertices:
            positions.extend(vertex.to_list())
            
        for normal in self.normals:
            normals.extend(normal.to_list())
            
        for uv in self.uvs:
            uvs.extend([uv[0], uv[1]])
        
        # Convert faces to indices
        indices = []
        for face in self.faces:
            indices.extend([face[0], face[1], face[2]])
        
        return {
            "name": name,
            "vertex_count": len(self.vertices),
            "face_count": len(self.faces),
            "positions": positions,
            "normals": normals,
            "uvs": uvs,
            "indices": indices,
            "joint_weights": self.joint_weights,
            "material": {
                "name": "ethereal_glow",
                "base_color": [0.2, 0.8, 1.0, 0.7],  # Translucent blue
                "emissive": [0.1, 0.4, 0.8],
                "metallic": 0.0,
                "roughness": 0.2,
                "alpha_mode": "BLEND",
                "double_sided": True
            }
        }


class EtherealGLBExporter:
    """Export ethereal avatars to GLB format for PubCast"""
    
    @staticmethod
    def create_glb_manifest(models: Dict[str, Dict]) -> Dict:
        """Create avatar asset manifest for PubCast"""
        manifest = {
            "packs": []
        }
        
        for model_name, model_data in models.items():
            pack = {
                "pack_id": model_name,
                "label": model_name.replace('_', ' ').title(),
                "description": f"Ethereal {model_name.split('_')[1]} avatar with translucent blue glow effect",
                "glb": f"assets/avatar/{model_name}.glb",
                "viseme_map": {
                    "neutral": "neutral",
                    "A": "mouth_a", 
                    "E": "mouth_e",
                    "I": "mouth_i",
                    "O": "mouth_o",
                    "U": "mouth_u"
                },
                "idle_animation": "idle_float",
                "animations": {
                    "idle_float": "gentle floating motion",
                    "gesture": "graceful arm movements", 
                    "speak": "subtle mouth movements"
                }
            }
            manifest["packs"].append(pack)
        
        return manifest


def generate_ethereal_avatars():
    """Generate both male and female ethereal avatars"""
    generator = EtherealAvatar()
    
    # Generate models
    male_model = generator.create_ethereal_male()
    female_model = generator.create_ethereal_female()
    
    models = {
        "ethereal_male": male_model,
        "ethereal_female": female_model
    }
    
    # Create manifest
    exporter = EtherealGLBExporter()
    manifest = exporter.create_glb_manifest(models)
    
    return models, manifest


if __name__ == "__main__":
    models, manifest = generate_ethereal_avatars()
    
    # Save model data
    for name, data in models.items():
        with open(f"{name}_data.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"Generated {name}: {data['vertex_count']} vertices, {data['face_count']} faces")
    
    # Save manifest
    with open("avatar_assets.json", "w") as f:
        json.dump(manifest, f, indent=2)
    
    print("\nEthereal avatar models generated successfully!")
    print("- ethereal_male_data.json")  
    print("- ethereal_female_data.json")
    print("- avatar_assets.json (manifest)")
