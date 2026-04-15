# Main application entry point
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.users import router as users_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.rooms import router as rooms_router
from app.api.reservations import router as reservations_router
from app.api.payments import router as payments_router
from app.api.webhooks import router as webhooks_router
from app.core.initial_data import init_rbac_data
from app.core.cloudinary import init_cloudinary

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
    init_cloudinary()


app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(rooms_router)
app.include_router(reservations_router)
app.include_router(payments_router)
app.include_router(webhooks_router)


@app.get("/")
def root():
    return {"message": "Backend funcionando correctamente"}
