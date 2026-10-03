from fastapi import FastAPI

import routes

app = FastAPI(
    title="Llamalla Analytics Engine",
    version="2.0.0"
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


for module in routes.feature_modules():
    router = getattr(module, "router", None)
    if router is not None:
        app.include_router(router)