import os
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import httpx 



BACKEND_SERVICE_HOST = os.getenv("BACKEND_SERVICE_HOST", "backend") 
BACKEND_SERVICE_PORT = os.getenv("BACKEND_SERVICE_PORT", "9567")
BACKEND_URL = f"http://{BACKEND_SERVICE_HOST}:{BACKEND_SERVICE_PORT}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

templates = Jinja2Templates(directory="templates")

client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=10.0)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main HTML page."""
    logger.info("Rendering index.html")
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

@app.get("/api/search/{query}")
async def proxy_search(query: str):
    """Proxies the search request to the backend service."""
    try:
        logger.info(f"Proxying search request for query: '{query}' to {BACKEND_URL}/search/{query}")
        response = await client.get(f"/search/{query}") 

        content = await response.aread()
        return JSONResponse(content=content.decode('utf-8'), status_code=response.status_code)


    except httpx.RequestError as exc:
        logger.error(f"HTTPX RequestError while contacting backend for search: {exc}")
        raise HTTPException(status_code=503, detail=f"Could not connect to backend service: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error in search proxy: {exc}")
        raise HTTPException(status_code=500, detail=f"Internal proxy error: {exc}")

@app.post("/api/insert")
async def proxy_insert(request: Request):
    """Proxies the insert request to the backend service."""
    try:
        request_body = await request.json()
        logger.info(f"Proxying insert request to {BACKEND_URL}/insert with body: {request_body}")

        response = await client.post("/insert", json=request_body) 

        content = await response.aread()
        return JSONResponse(content=content.decode('utf-8'), status_code=response.status_code)

    except httpx.RequestError as exc:
        logger.error(f"HTTPX RequestError while contacting backend for insert: {exc}")
        raise HTTPException(status_code=503, detail=f"Could not connect to backend service: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error in insert proxy: {exc}")
        raise HTTPException(status_code=500, detail=f"Internal proxy error: {exc}")

@app.on_event("shutdown")
async def shutdown_event():
    await client.aclose() 
    logger.info("Frontend service shutting down.")


@app.get("/ping")
async def ping():
    return {"message": "Frontend is running"}