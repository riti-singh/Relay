from fastapi import FastAPI

from relay.api.routes import router


def create_app() -> FastAPI:
    application = FastAPI(
        title="Relay", version="0.1.0", description="Agentic network incident response"
    )
    application.include_router(router)
    return application


app = create_app()
