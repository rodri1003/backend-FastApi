from fastapi import FastAPI
from app.db.session import Base, engine
from app.models.user import User

from app.api.users import router as users_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(users_router)
app.include_router(auth_router)
app.include_router(admin_router)

@app.get("/")
def root():
    return {"message": "Backend funcionando correctamente"}
