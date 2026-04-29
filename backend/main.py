import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.database import create_tables, upgrade_schema
from backend.middleware import AuditMiddleware
from backend.routers import auth, accounts, categories, recurring, forecast, transactions, budget, credit_cards, spending
from backend.routers import admin as admin_router_module
from backend.routers import imports as imports_router_module

app = FastAPI(
    title="OfflineBudget",
    description="Forecasting-first personal budget tracker",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(recurring.router)
app.include_router(forecast.router)
app.include_router(transactions.router)
app.include_router(budget.router)
app.include_router(credit_cards.router)
app.include_router(spending.router)
app.include_router(admin_router_module.router)
app.include_router(imports_router_module.router)


@app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    create_tables()
    upgrade_schema()


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
