import os
import uuid
import asyncio
import requests
import rasterio
import numpy as np
import pyvista as pv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import math

app = FastAPI(title="Terrain 3D API")

# Ensure a directory exists to store the generated 3D models
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

class BoundingBox(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    z_exaggeration: float = 2.0
    api_key: str

def process_terrain_pipeline(bbox: BoundingBox) -> str:
    """CPU-bound and Blocking I/O function to be run in a thread"""
    job_id = str(uuid.uuid4())
    tif_path = f"static/{job_id}.tif"
    tex_path = f"static/{job_id}_tex.png"
    glb_path = f"static/{job_id}.glb"

    # 1. Download DEM
    dem_url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": "NASADEM",
        "south": bbox.min_lat, "north": bbox.max_lat,
        "west": bbox.min_lon, "east": bbox.max_lon,
        "outputFormat": "GTiff",
        "API_Key": bbox.api_key  # <-- Replace hardcoded key
    }
    res = requests.get(dem_url, params=params)
    if res.status_code != 200:
        raise ValueError(f"Failed to fetch DEM: {res.text}")
    
    with open(tif_path, 'wb') as f:
        f.write(res.content)

    # 2. Process Mesh Array & Get Exact DEM Bounds
    with rasterio.open(tif_path) as src:
        elevation = src.read(1)
        dem_bounds = src.bounds 
        
        valid_mask = elevation > -500
        min_val = elevation[valid_mask].min() if valid_mask.any() else 0.0
        elevation = np.where(valid_mask, elevation, min_val)

    width = elevation.shape[1]
    height = elevation.shape[0]

    # 3. Download Satellite Imagery (With Aspect-Ratio Lock!)
    # Force the high-res texture to match the exact aspect ratio of the DEM.
    # This stops Esri from silently padding the bounding box and causing texture drift!
    max_res = 2048
    if width >= height:
        tex_w = max_res
        tex_h = int(max_res * (height / width))
    else:
        tex_h = max_res
        tex_w = int(max_res * (width / height))

    esri_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
    esri_params = {
        "bbox": f"{dem_bounds.left},{dem_bounds.bottom},{dem_bounds.right},{dem_bounds.top}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{tex_w},{tex_h}",  # Dynamically calculated proportional resolution
        "format": "png",
        "f": "image"
    }
    res_tex = requests.get(esri_url, params=esri_params)
    if res_tex.status_code != 200:
        raise ValueError(f"Failed to fetch satellite imagery: {res_tex.text}")
    
    with open(tex_path, 'wb') as f:
        f.write(res_tex.content)

    # 4. Build 3D Mesh Geometry (Restoring stable local coordinates for the camera)
    x = np.linspace(0, width, width)
    # Map Y from height down to 0 so +Y points North
    y = np.linspace(height, 0, height)
    
    lat = (bbox.min_lat + bbox.max_lat) / 2.0
    x = x * math.cos(math.radians(lat))
    
    # Force 'ij' indexing to prevent PyVista from transposing axes
    x, y = np.meshgrid(x, y, indexing='ij')
    
    # Transpose the elevation array to match the 'ij' coordinates
    elevation_T = elevation.T
    normalized_elevation = ((elevation_T + 1000 - min_val) / 30.0) * bbox.z_exaggeration
    
    grid = pv.StructuredGrid(x, y, normalized_elevation)
    
    # 5. Lock UVs 1:1 with Array Indices
    u = np.linspace(0.0, 1.0, width, dtype=np.float32)
    v = np.linspace(1.0, 0.0, height, dtype=np.float32)
    
    # Use matching 'ij' indexing for the UV grid
    uu, vv = np.meshgrid(u, v, indexing='ij')
    
    # Flatten using Fortran order ("F") to synchronize with PyVista's point generation
    uvs = np.column_stack((uu.ravel(order="F"), vv.ravel(order="F")))
    grid.active_texture_coordinates = uvs
    
    # Extract Surface
    mesh = grid.extract_surface(algorithm='dataset_surface')
    
    # Tag the safe UVs for the GLTF Exporter
    mesh.point_data["TEXCOORD_0"] = mesh.active_texture_coordinates
    
    
    # ================= DEBUG OUTPUT =================
    print(f"\n--- DEBUG: {job_id} ---")
    print(f"1. DEM Dimensions: {width}x{height} (Expected Points: {width * height})")
    
    tex_size = os.path.getsize(tex_path)
    print(f"2. Texture Size: {tex_size} bytes")
    if tex_size < 5000:
        print("   -> WARNING: Texture is suspiciously small. Esri may have returned a dummy/error PNG.")
        
    print(f"3. Grid Points (Before extract): {grid.n_points}")
    uv_grid = grid.active_texture_coordinates
    print(f"   Grid UVs shape: {uv_grid.shape if uv_grid is not None else 'NONE'}")
    
    print(f"4. Mesh Points (After extract): {mesh.n_points}")
    uv_mesh = mesh.active_texture_coordinates
    print(f"   Mesh UVs shape: {uv_mesh.shape if uv_mesh is not None else 'NONE'}")
    
    if "TEXCOORD_0" in mesh.point_data:
        print(f"5. TEXCOORD_0 Shape: {mesh.point_data['TEXCOORD_0'].shape}")
    else:
        print("5. CRITICAL: TEXCOORD_0 is completely missing!")
    print("================================================\n")
    
    

    # 6. Export to GLB
    tex = pv.Texture(tex_path)
    plotter = pv.Plotter(off_screen=True)
    
    plotter.add_mesh(
        mesh, 
        texture=tex, 
        color="white", 
        show_scalar_bar=False, 
        lighting=False
    )
    plotter.export_gltf(glb_path)
    
    # Clean up
    os.remove(tif_path)
    os.remove(tex_path)
    
    return f"/static/{job_id}.glb"
    

@app.post("/generate")
async def generate_terrain(bbox: BoundingBox):
    try:
        # Offload the crunching to a worker thread
        glb_url = await asyncio.to_thread(process_terrain_pipeline, bbox)
        return {"status": "success", "glb_url": glb_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def serve_frontend():
    return FileResponse("index.html")




