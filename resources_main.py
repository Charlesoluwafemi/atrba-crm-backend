"""
ATRBA Resources Hub — FastAPI Application Entry Point
Standalone service running on port 8001.
"""

import os
import sys


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client

import storage as storage_svc
import auth as auth_svc
import resources_db as db_svc

from public import router as public_router
from admin import router as admin_router


# ─────────────────────────────────────────────
# Load env FIRST
# ─────────────────────────────────────────────
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("❌ Missing Supabase credentials")


# ─────────────────────────────────────────────
# FIX: safer HTTP client for Supabase
# ─────────────────────────────────────────────



# ─────────────────────────────────────────────
# Supabase Client
# ─────────────────────────────────────────────
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    
)


# ─────────────────────────────────────────────
# Init services
# ─────────────────────────────────────────────
storage_svc.init_storage(supabase)
auth_svc.init_auth(supabase)
db_svc.init_db(supabase)


# ─────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────
app = FastAPI(
    title="ATRBA Resources Hub API",
    version="1.0.0",
)


# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
app.include_router(public_router)
app.include_router(admin_router)


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────
@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "resources",
        "port": 8001
    }


# ─────────────────────────────────────────────
# Run server
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "resources_main:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )