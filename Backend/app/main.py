from fastapi import FastAPI

from app.modules.scraping.router import router as scraping_router

app = FastAPI(title="DataPeers ORBIT Agent")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


app.include_router(scraping_router, prefix="/api/v1")