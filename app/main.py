from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.users import router as users_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.core.initial_data import init_rbac_data

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_rbac_data()


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {"message": "Backend funcionando correctamente"}
