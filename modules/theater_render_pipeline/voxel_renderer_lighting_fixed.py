"""
voxel_renderer.py — Production voxel → mesh → lighting pipeline
Converts sparse voxel grids to GPU-ready meshes with LOD and cinematic lighting.

Core pipeline:
  1. Load voxel model (MagicaVoxel or synthetic)
  2. Generate smooth mesh (Marching Cubes simplified)
  3. Apply per-vertex lighting (key/fill/rim)
  4. Select LOD based on distance
  5. Serialize to bytes for network transmission
"""

import struct
import numpy as np
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# MESH REPRESENTATION
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Mesh:
    """Triangle mesh with positions, normals, colors"""
    vertices: np.ndarray  # Shape: (N, 3), dtype=float32
    normals: np.ndarray   # Shape: (N, 3), dtype=float32
    indices: np.ndarray   # Shape: (M, 3), dtype=uint32
    colors: Optional[np.ndarray] = None  # Shape: (N, 3), dtype=uint8
    
    def triangle_count(self) -> int:
        return len(self.indices)
    
    def vertex_count(self) -> int:
        return len(self.vertices)
    
    def to_bytes(self) -> bytes:
        """Serialize mesh to bytes for network transmission"""
        if self.vertex_count() == 0:
            # Empty mesh marker
            return struct.pack('<I I B', 0, 0, 0)
        
        data = bytearray()
        
        # Header: vertex_count, triangle_count, has_colors
        data.extend(struct.pack('<I', self.vertex_count()))
        data.extend(struct.pack('<I', self.triangle_count()))
        data.extend(struct.pack('B', 1 if self.colors is not None else 0))
        
        # Vertex positions (3 float32 each)
        data.extend(self.vertices.astype(np.float32).tobytes())
        
        # Vertex normals (3 float32 each)
        data.extend(self.normals.astype(np.float32).tobytes())
        
        # Triangle indices (3 uint32 each)
        data.extend(self.indices.astype(np.uint32).tobytes())
        
        # Colors (optional, 3 uint8 each)
        if self.colors is not None:
            data.extend(self.colors.astype(np.uint8).tobytes())
        
        return bytes(data)
    
    @staticmethod
    def from_bytes(data: bytes) -> 'Mesh':
        """Deserialize mesh from bytes"""
        offset = 0
        
        # Read header
        vertex_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        triangle_count = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        has_colors = struct.unpack_from('B', data, offset)[0]
        offset += 1
        
        if vertex_count == 0:
            return Mesh(
                vertices=np.zeros((0, 3), dtype=np.float32),
                normals=np.zeros((0, 3), dtype=np.float32),
                indices=np.zeros((0, 3), dtype=np.uint32)
            )
        
        # Read vertices
        vertices = np.frombuffer(data, dtype=np.float32, count=vertex_count*3, offset=offset).reshape(-1, 3).copy()
        offset += vertex_count * 3 * 4
        
        # Read normals
        normals = np.frombuffer(data, dtype=np.float32, count=vertex_count*3, offset=offset).reshape(-1, 3).copy()
        offset += vertex_count * 3 * 4
        
        # Read indices
        indices = np.frombuffer(data, dtype=np.uint32, count=triangle_count*3, offset=offset).reshape(-1, 3).copy()
        offset += triangle_count * 3 * 4
        
        # Read colors (optional)
        colors = None
        if has_colors:
            colors = np.frombuffer(data, dtype=np.uint8, count=vertex_count*3, offset=offset).reshape(-1, 3).copy()
        
        return Mesh(vertices=vertices, normals=normals, indices=indices, colors=colors)

# ═════════════════════════════════════════════════════════════════════════════
# VOXEL MODEL
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class VoxelModel:
    """Sparse voxel grid representation"""
    model_id: str
    width: int
    height: int
    depth: int
    voxels: np.ndarray  # Shape: (W, H, D), dtype=uint8
    palette: List[Tuple[int, int, int]] = None
    
    def get_voxel(self, x: int, y: int, z: int) -> int:
        """Get voxel value (with bounds check)"""
        if 0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.depth:
            return int(self.voxels[x, y, z])
        return 0
    
    @classmethod
    def create_test_model(cls, model_id: str = "test_cube") -> 'VoxelModel':
        """Create a simple test cube"""
        size = 16
        voxels = np.zeros((size, size, size), dtype=np.uint8)
        # Hollow cube
        voxels[2:size-2, 2:size-2, 2:size-2] = 0
        voxels[2:size-2, 2:size-2, 2:4] = 1
        voxels[2:size-2, 2:size-2, size-4:size-2] = 1
        voxels[2:4, 2:size-2, 2:size-2] = 1
        voxels[size-4:size-2, 2:size-2, 2:size-2] = 1
        voxels[2:size-2, 2:4, 2:size-2] = 1
        voxels[2:size-2, size-4:size-2, 2:size-2] = 1
        
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        return cls(
            model_id=model_id,
            width=size,
            height=size,
            depth=size,
            voxels=voxels,
            palette=palette
        )

# ═════════════════════════════════════════════════════════════════════════════
# MESH GENERATION (SIMPLIFIED MARCHING CUBES)
# ═════════════════════════════════════════════════════════════════════════════

class MeshGenerator:
    """Convert voxel grid to smooth triangle mesh"""
    
    # Marching cubes edge table (simplified)
    EDGE_TABLE = [
        0x0, 0x109, 0x203, 0x30a, 0x406, 0x50f, 0x605, 0x70c,
        0x80c, 0x905, 0xa0f, 0xb06, 0xc0a, 0xd03, 0xe09, 0xf00,
    ]
    
    def __init__(self, voxel_model: VoxelModel):
        self.model = voxel_model
    
    def generate_mesh(self) -> Mesh:
        """Generate mesh from voxel grid using greedy surface extraction"""
        vertices = []
        indices = []
        normals = []
        vertex_map = {}  # (x, y, z) -> vertex index
        
        # Identify surface voxels and create vertices
        for x in range(self.model.width):
            for y in range(self.model.height):
                for z in range(self.model.depth):
                    if self._is_surface_voxel(x, y, z):
                        v_idx = len(vertices)
                        vertices.append([x + 0.5, y + 0.5, z + 0.5])
                        
                        # Compute normal from gradient
                        normal = self._compute_normal(x, y, z)
                        normals.append(normal)
                        
                        vertex_map[(x, y, z)] = v_idx
        
        # Generate triangles from surface voxels
        for (x, y, z), v_idx in vertex_map.items():
            # Create quads for each exposed face
            neighbors = [
                ((x+1, y, z), 'x+'),
                ((x-1, y, z), 'x-'),
                ((x, y+1, z), 'y+'),
                ((x, y-1, z), 'y-'),
                ((x, y, z+1), 'z+'),
                ((x, y, z-1), 'z-'),
            ]
            
            for (nx, ny, nz), face_dir in neighbors:
                # If neighbor is empty, create triangle
                if self.model.get_voxel(nx, ny, nz) == 0:
                    # Find two adjacent surface vertices to form triangle
                    # (simplified: just use current vertex + offsets)
                    if face_dir == 'x+':
                        v1 = (x, y, z)
                        v2 = (x, y+1, z)
                        v3 = (x, y, z+1)
                    elif face_dir == 'x-':
                        v1 = (x, y, z)
                        v2 = (x, y, z+1)
                        v3 = (x, y+1, z)
                    elif face_dir == 'y+':
                        v1 = (x, y, z)
                        v2 = (x+1, y, z)
                        v3 = (x, y, z+1)
                    elif face_dir == 'y-':
                        v1 = (x, y, z)
                        v2 = (x, y, z+1)
                        v3 = (x+1, y, z)
                    elif face_dir == 'z+':
                        v1 = (x, y, z)
                        v2 = (x, y+1, z)
                        v3 = (x+1, y, z)
                    else:  # z-
                        v1 = (x, y, z)
                        v2 = (x+1, y, z)
                        v3 = (x, y+1, z)
                    
                    # Only create if all vertices are in map
                    if v1 in vertex_map and v2 in vertex_map and v3 in vertex_map:
                        idx1, idx2, idx3 = vertex_map[v1], vertex_map[v2], vertex_map[v3]
                        if idx1 != idx2 and idx2 != idx3 and idx1 != idx3:
                            indices.append([idx1, idx2, idx3])
        
        # Convert to numpy arrays
        if not vertices:
            return Mesh(
                vertices=np.zeros((0, 3), dtype=np.float32),
                normals=np.zeros((0, 3), dtype=np.float32),
                indices=np.zeros((0, 3), dtype=np.uint32)
            )
        
        verts = np.array(vertices, dtype=np.float32)
        norms = np.array(normals, dtype=np.float32) if normals else np.zeros_like(verts)
        inds = np.array(indices, dtype=np.uint32) if indices else np.zeros((0, 3), dtype=np.uint32)
        
        # Ensure normals are normalized
        norms = norms / (np.linalg.norm(norms, axis=1, keepdims=True) + 1e-6)
        
        return Mesh(vertices=verts, normals=norms, indices=inds)
    
    def _is_surface_voxel(self, x: int, y: int, z: int) -> bool:
        """Check if voxel is on surface (filled with empty neighbor)"""
        filled = self.model.get_voxel(x, y, z) > 0
        
        if not filled:
            return False
        
        # Check 6 neighbors
        neighbors = [
            self.model.get_voxel(x+1, y, z) > 0,
            self.model.get_voxel(x-1, y, z) > 0,
            self.model.get_voxel(x, y+1, z) > 0,
            self.model.get_voxel(x, y-1, z) > 0,
            self.model.get_voxel(x, y, z+1) > 0,
            self.model.get_voxel(x, y, z-1) > 0,
        ]
        
        # Surface if has at least one empty neighbor
        return not all(neighbors)
    
    def _compute_normal(self, x: int, y: int, z: int) -> np.ndarray:
        """Compute vertex normal from voxel density gradient"""
        gx = (self.model.get_voxel(x+1, y, z) - self.model.get_voxel(x-1, y, z)) / 2.0
        gy = (self.model.get_voxel(x, y+1, z) - self.model.get_voxel(x, y-1, z)) / 2.0
        gz = (self.model.get_voxel(x, y, z+1) - self.model.get_voxel(x, y, z-1)) / 2.0
        
        normal = np.array([gx, gy, gz], dtype=np.float32)
        norm = np.linalg.norm(normal)
        
        if norm < 1e-6:
            return np.array([0, 1, 0], dtype=np.float32)
        
        return normal / norm

# ═════════════════════════════════════════════════════════════════════════════
# LOD SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

class LODSelector:
    """Select mesh quality based on camera distance"""
    
    THRESHOLDS = {
        "LOD0": 2.0,
        "LOD1": 6.0,
        "LOD2": 15.0,
        "LOD3": float('inf'),
    }
    
    BUDGETS = {
        "LOD0": 8000,
        "LOD1": 2000,
        "LOD2": 500,
        "LOD3": 2,
    }
    
    @staticmethod
    def select_lod(camera_distance: float) -> str:
        """Select LOD based on distance"""
        for lod in ["LOD0", "LOD1", "LOD2", "LOD3"]:
            if camera_distance < LODSelector.THRESHOLDS[lod]:
                return lod
        return "LOD3"
    
    @staticmethod
    def decimate_mesh(mesh: Mesh, target_triangles: int) -> Mesh:
        """Reduce triangle count via random sampling"""
        if mesh.triangle_count() <= target_triangles:
            return mesh
        
        # Randomly sample triangles
        ratio = target_triangles / max(1, mesh.triangle_count())
        mask = np.random.rand(mesh.triangle_count()) < ratio
        kept_indices = np.where(mask)[0]
        
        if len(kept_indices) == 0:
            return Mesh(
                vertices=mesh.vertices[:1],
                normals=mesh.normals[:1],
                indices=np.array([[0, 0, 0]], dtype=np.uint32)
            )
        
        # Get kept triangles
        new_indices = mesh.indices[kept_indices]
        
        # Remap vertex indices (only keep referenced vertices)
        unique_verts = np.unique(new_indices.flatten())
        vert_remap = {old: new for new, old in enumerate(unique_verts)}
        
        remapped = np.array([
            [vert_remap[new_indices[i, 0]], 
             vert_remap[new_indices[i, 1]], 
             vert_remap[new_indices[i, 2]]]
            for i in range(len(new_indices))
        ], dtype=np.uint32)
        
        return Mesh(
            vertices=mesh.vertices[unique_verts],
            normals=mesh.normals[unique_verts],
            indices=remapped,
            colors=mesh.colors[unique_verts] if mesh.colors is not None else None
        )

# ═════════════════════════════════════════════════════════════════════════════
# LIGHTING
# ═════════════════════════════════════════════════════════════════════════════

class LightingApplier:
    """Apply cinematic lighting to vertices"""
    
    def __init__(self, light_state: Dict[str, Any]):
        self.light_state = light_state or {}
    
    def apply_lighting(self, mesh: Mesh) -> Mesh:
        """Apply per-vertex lighting based on normals"""
        # BUG FIX: this previously computed a grayscale lighting intensity
        # and wrote it directly as R=G=B, discarding the mesh's actual base
        # material color entirely (a brown wood block and a red wall block
        # both ended up the identical shade of gray). The base color needs
        # to be multiplied by the light intensity, not replaced by it.
        if mesh.colors is not None:
            base_colors = mesh.colors.astype(np.float32) / 255.0
        else:
            base_colors = np.ones((len(mesh.vertices), 3), dtype=np.float32)

        vertex_colors = np.ones((len(mesh.vertices), 3), dtype=np.float32)
        
        for i, normal in enumerate(mesh.normals):
            # Key light
            key_dir = self._direction_from_spherical(
                self.light_state.get('key_azimuth', -45),
                self.light_state.get('key_elevation', 35)
            )
            key_contrib = np.clip(np.dot(normal, key_dir), 0, 1) * self.light_state.get('key_intensity', 1.0)
            
            # Fill light (always visible, softer)
            fill_dir = self._direction_from_spherical(
                self.light_state.get('fill_azimuth', 60),
                self.light_state.get('fill_elevation', 20)
            )
            fill_contrib = (np.dot(normal, fill_dir) * 0.5 + 0.5) * self.light_state.get('fill_intensity', 0.35)
            
            # Rim light (backlit highlight)
            rim_dir = -key_dir
            rim_contrib = np.clip(np.dot(normal, rim_dir), 0, 1) * self.light_state.get('rim_intensity', 0.6)
            
            # Ambient
            ambient = self.light_state.get('ambient_intensity', 0.25)
            
            # Combine lights
            total = ambient + key_contrib + fill_contrib + rim_contrib
            total = np.clip(total, 0.0, 1.0)
            
            vertex_colors[i] = base_colors[i] * total
        
        # Apply color grading
        saturation = self.light_state.get('saturation', 1.0)
        contrast = self.light_state.get('contrast', 1.0)
        exposure = self.light_state.get('exposure', 0.0)
        
        # Desaturate
        gray = np.mean(vertex_colors, axis=1, keepdims=True)
        vertex_colors = gray + (vertex_colors - gray) * saturation
        
        # Contrast
        vertex_colors = (vertex_colors - 0.5) * contrast + 0.5
        
        # Exposure
        vertex_colors = vertex_colors * np.power(2.0, exposure)
        
        # Clamp and convert to uint8
        vertex_colors = np.clip(vertex_colors * 255, 0, 255).astype(np.uint8)
        
        mesh.colors = vertex_colors
        return mesh
    
    @staticmethod
    def _direction_from_spherical(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
        """Convert azimuth/elevation angles to direction vector"""
        az_rad = np.radians(azimuth_deg)
        el_rad = np.radians(elevation_deg)
        
        x = np.cos(el_rad) * np.sin(az_rad)
        y = np.sin(el_rad)
        z = np.cos(el_rad) * np.cos(az_rad)
        
        direction = np.array([x, y, z], dtype=np.float32)
        norm = np.linalg.norm(direction)
        return direction / (norm + 1e-6) if norm > 1e-6 else np.array([0, 1, 0], dtype=np.float32)

# ═════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL VOXEL RENDERER
# ═════════════════════════════════════════════════════════════════════════════

class VoxelRenderer:
    """Production voxel rendering orchestrator"""
    
    def __init__(self):
        self._model_cache: Dict[str, VoxelModel] = {}
        self._mesh_cache: Dict[Tuple[str, str], Mesh] = {}
    
    def register_model(self, model: VoxelModel) -> None:
        """Register a voxel model"""
        self._model_cache[model.model_id] = model
    
    def render(self,
               model_id: str,
               camera_distance: float,
               light_state: Optional[Dict[str, Any]] = None,
               force_reload: bool = False) -> bytes:
        """
        Render a voxel character to mesh bytes
        
        Args:
            model_id: Character identifier
            camera_distance: Distance from camera (for LOD selection)
            light_state: Lighting parameters (from lighting_engine)
            force_reload: Bypass cache
        
        Returns:
            Serialized mesh bytes
        """
        try:
            # Load voxel model
            if model_id not in self._model_cache or force_reload:
                # Try to load from file system (not implemented yet)
                # For now, create a test model
                logger.warning(f"Model {model_id} not found, using test model")
                self._model_cache[model_id] = VoxelModel.create_test_model(model_id)
            
            voxel_model = self._model_cache[model_id]
            
            # Select LOD
            lod = LODSelector.select_lod(camera_distance)
            
            # Check cache
            cache_key = (model_id, lod)
            if cache_key not in self._mesh_cache or force_reload:
                # Generate mesh
                generator = MeshGenerator(voxel_model)
                mesh = generator.generate_mesh()
                
                # Decimate if needed
                target_triangles = LODSelector.BUDGETS[lod]
                if mesh.triangle_count() > target_triangles:
                    mesh = LODSelector.decimate_mesh(mesh, target_triangles)
                
                # Cache it
                self._mesh_cache[cache_key] = mesh
            
            mesh = self._mesh_cache[cache_key]
            
            # Apply lighting
            light_state = light_state or {}
            applier = LightingApplier(light_state)
            lit_mesh = applier.apply_lighting(mesh)
            
            # Serialize and return
            return lit_mesh.to_bytes()
        
        except Exception as e:
            logger.error(f"Voxel render error: {e}", exc_info=True)
            # Return empty mesh on error (graceful degradation)
            empty = Mesh(
                vertices=np.zeros((0, 3), dtype=np.float32),
                normals=np.zeros((0, 3), dtype=np.float32),
                indices=np.zeros((0, 3), dtype=np.uint32)
            )
            return empty.to_bytes()

# Global renderer instance
_renderer: Optional[VoxelRenderer] = None

def get_renderer() -> VoxelRenderer:
    """Get or create global renderer instance"""
    global _renderer
    if _renderer is None:
        _renderer = VoxelRenderer()
    return _renderer

def render_voxel(model_id: str,
                 camera_distance: float,
                 light_state: Optional[Dict[str, Any]] = None) -> bytes:
    """Convenience function for rendering"""
    return get_renderer().render(model_id, camera_distance, light_state)
