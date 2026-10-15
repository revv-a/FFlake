from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fflake_graph.router import router as graph_hacks_router
app = FastAPI(title="FFlake API")
app.include_router(graph_hacks_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "FFlake API is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}