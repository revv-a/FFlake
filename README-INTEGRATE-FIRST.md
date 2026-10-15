# FFlake GraphHacks integration pack

This is an **additive overlay** for `C:\Users\Saloni\FFlake`. It does not replace `backend/main.py`, your existing frontend, or Docker configuration.

## Extract correctly
Extract this ZIP into the root of your existing FFlake folder, so its `backend` directory merges with your existing `backend` directory.

Expected path: `C:\Users\Saloni\FFlake\backend\fflake_graph\...`

Do not extract it into the `backend` directory itself, or you will create an unwanted `backend\backend` folder.

## 1. Install dependency
```powershell
cd C:\Users\Saloni\FFlake\backend
python -m pip install -r requirements-fflake-graph.txt
```
This is a separate dependency file so your existing requirements file is not overwritten.

## 2. Add router to your existing FastAPI app
In `backend\main.py`, add this import alongside existing imports:
```python
from fflake_graph.router import router as graph_hacks_router
```
After `app = FastAPI(...)` is created, add:
```python
app.include_router(graph_hacks_router, prefix="/api")
```
Do not replace `main.py`. Adapt `app` only if your FastAPI variable has another name.

## 3. Connection settings (optional)
Defaults are `localhost:6379` and graph name `fflake`.
```powershell
$env:FALKORDB_HOST = "localhost"
$env:FALKORDB_PORT = "6379"
$env:FALKORDB_GRAPH = "fflake"
# Set only if your instance requires a password:
# $env:FALKORDB_PASSWORD = "your-password"
```

## 4. Start and test
Make sure the existing FalkorDB container is running, then use your usual backend command:
```powershell
cd C:\Users\Saloni\FFlake\backend
uvicorn main:app --reload
```
Open `http://127.0.0.1:8000/docs`.

Try:
1. `POST /api/graph-hacks/demo/seed`
2. `GET /api/graph-hacks/paths?source=external-bot&target=prod-secrets`
3. `POST /api/graph-hacks/analyze` with:
   ```json
   {"source":"external-bot","target":"prod-secrets"}
   ```
4. Copy a suggested `edge_id`, then call `POST /api/graph-hacks/verify`:
   ```json
   {"source":"external-bot","target":"prod-secrets","cut_edge_id":"PASTE_SUGGESTED_EDGE_ID"}
   ```

## Endpoints
- `GET /api/graph-hacks/health`
- `POST /api/graph-hacks/demo/seed`
- `GET /api/graph-hacks/paths`
- `POST /api/graph-hacks/analyze`
- `POST /api/graph-hacks/verify`

## Honest scope
The fictional demo identifies **capability paths for investigation**, not confirmed vulnerabilities. The verify endpoint excludes a candidate relationship from path search; it does not delete or mutate that relationship. Apply a real approved change and rerun verification against the updated graph before claiming remediation.

This pack does not replace the frontend, autonomously execute fixes, or add MCP yet. Those are deliberate next increments.
