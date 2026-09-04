from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from relay.api.routes import router


def create_app() -> FastAPI:
    application = FastAPI(
        title="Relay", version="0.1.0", description="Agentic network incident response"
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()
