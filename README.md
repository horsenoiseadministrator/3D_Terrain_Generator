<h1>3D Terrain Mapping Powered by NASA/Esri data - using free APIs</h1>
Aiming to make beautiful 3D topography accessible.
<br><br>
Draw a box on a map, get a zoom/turntable-able rendering back.
<br><br>

<img width="937" height="527" alt="Screenshot 2026-10-25 215520" src="https://github.com/user-attachments/assets/4b644e13-2253-45ef-89ef-3c16519dfea7" />

<br><br>
You  only need a free API key from <a href='https://opentopography.org/'>https://opentopography.org</a> to get started.
<br><br>

<img width="607" height="332" alt="Screenshot 2026-10-26 083129" src="https://github.com/user-attachments/assets/b6e8f34d-89c3-4017-8d5e-ba7b88190f3b" />

<br><br>


<h3>One-shot Install/Run</h3>

```bash
git clone https://github.com/horsenoiseadministrator/3D_Terrain_Generator.git
cd 3D_Terrain_Generator
pip install -r requirements.txt

echo "🚀 Starting FastAPI server..."
uvicorn server:app --reload &

echo "⏳ Waiting for the server to spin up..."
until curl -s http://localhost:8000 > /dev/null; do
    sleep 0.5
done

echo "🌐 Server is live! Launching your default browser..."
python -c "import webbrowser; webbrowser.open('http://localhost:8000')"
```


<br><br>

NASA provide the elevation data:
<br><br>
<img width="918" height="482" alt="Screenshot 2026-10-25 103410" src="https://github.com/user-attachments/assets/b63f4028-d387-4fb0-b82d-bbd0a90154ca" />

<br><br>

Esri the satellite imagery (to make it beautiful!):
<br><br>
<img width="958" height="539" alt="Screenshot 2026-10-25 215740" src="https://github.com/user-attachments/assets/9a2fa369-c1f6-47c9-883c-34462a1d7d6a" />
<br>
<img width="944" height="535" alt="Screenshot 2026-10-25 222204" src="https://github.com/user-attachments/assets/23611fa5-edb2-4513-b7a0-e733dd564f80" />
<br>
<img width="926" height="529" alt="Screenshot 2026-10-26 083259" src="https://github.com/user-attachments/assets/06c02331-7ebc-4687-9155-d6fe8b8c62d3" />
<br>
<img width="955" height="500" alt="Screenshot 2026-10-25 183427" src="https://github.com/user-attachments/assets/1bdd55a0-48cf-4fe2-9773-af9854cc6943" />
<br>
<img width="953" height="499" alt="Screenshot 2026-10-25 181314" src="https://github.com/user-attachments/assets/0f018f17-2d1c-4f27-aef1-e3e01c364895" />
<br>
<img width="929" height="539" alt="image" src="https://github.com/user-attachments/assets/039e05ba-4287-49b0-9ae4-8d2a9a4c9593" />

<br><br>


### The Architecture Stack<br>
The application is split into a lightweight browser frontend and a heavy-lifting numerical backend.<br>
* **Frontend:** HTML, CSS, and vanilla JavaScript. Leaflet.js handles the 2D interactive map and bounding box selection, while Three.js provides the 3D viewport and camera controls to render the final model.<br>
* **Backend:** FastAPI orchestrates the API. Because generating 3D meshes is heavily CPU-bound, the generation pipeline is offloaded to a worker thread using `asyncio.to_thread()`, keeping the web server responsive.<br>
* **Data Processing:** Rasterio reads the raw elevation files, NumPy handles the matrix math, and PyVista constructs the 3D geometry and handles the GLTF export.<br><br>

### The Geospatial Pipeline<br>
When a user selects a region and clicks "Generate," the backend kicks off a precise six-step pipeline. The biggest challenge in this build was ensuring mathematical harmony between the elevation vertices and the texture pixels.<br><br>

**1. Acquiring Elevation Data (NASA DEM)**<br>
The app queries the OpenTopography API to fetch NASADEM data. This returns a raw GeoTIFF file representing the exact elevation values (in meters) for the requested bounding box.<br><br>

**2. Mesh Array Processing**<br>
Using Rasterio, the GeoTIFF is read into a NumPy array. NASA DEM data often contains extreme negative values (like `-32768`) to represent voids or ocean water. The pipeline masks these out, replacing them with the lowest valid nearby land elevation to ensure flat coastlines rather than massive spikes pointing to the center of the earth. We also extract the exact snapped `dem_bounds` here, which is critical for the next step.<br><br>

**3. Fetching Photorealistic Textures (Esri API)**<br>
To texture the mesh, the app pings the Esri ArcGIS REST Export Map API. A major hurdle here is aspect ratio. If you request a perfect 2048x2048 square from Esri, but your geographic selection is a rectangle, Esri silently pads the geographic area to fit the square. This causes the satellite image to drift out of alignment with the physical mountains. To fix this, the app dynamically calculates a proportional resolution lock based on the DEM's dimensions, ensuring the texture maps 1:1 with the physical bounds.<br><br>

**4. Building the 3D Geometry**<br>
The spatial math happens entirely in NumPy. Arrays for X (longitude) and Y (latitude) are generated. The X-axis is multiplied by the cosine of the center latitude to mathematically compress the grid, mimicking real-world spherical distances on a flat plane. Crucially, `indexing='ij'` is forced on the NumPy `meshgrid` and the elevation matrix is transposed (`.T`). This prevents PyVista from silently swapping the X and Y axes and rendering the landscape 90 degrees out of phase.<br><br>

**5. Perfect UV Mapping**<br>
Instead of relying on auto-projection algorithms (which often try to guess the "best fit" plane and end up projecting textures diagonally against steep mountains), the UV coordinates are strictly locked to the array indices. The U and V arrays are cast specifically to `dtype=np.float32`. The GLTF 2.0 specification strictly requires 32-bit floats for textures; if fed standard 64-bit NumPy floats, the exporter silently drops the texture entirely. The UV coordinates are flattened using Fortran order (`order="F"`) to perfectly synchronize with how PyVista constructs its internal point lists, eliminating "barcode streaking" artifacts.<br><br>

**6. GLB Export and Delivery**<br>
The final PyVista `StructuredGrid` is extracted into a surface mesh. The texture is applied natively via PyVista's plotter with `lighting=False`. This forces the GLTF exporter to treat the satellite imagery as an "unlit" material, meaning the texture displays perfectly bright using its raw image colors regardless of the web viewer's lighting setup. The file is served back to the Three.js frontend.<br><br>
Building reliable pipelines for geospatial data requires navigating a minefield of coordinate systems, indexing orders, and data types. Seeing raw data transform from a flat array of numbers into a fully explorable 3D landscape right in the browser makes the mathematical wrestling entirely worth it!



<br><br><br>

Any Qs: jlambourne94@gmail.com



