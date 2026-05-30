"""
ATRBA Resources Hub — Admin Routes
All endpoints require a valid Bearer token from POST /resources/admin/login.
"""

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException
from typing import Optional
import re
import uuid
from pydantic import BaseModel

import resources_db as db
import storage as storage
from auth import get_admin_session, verify_password, create_session, get_client as auth_db
from schemas import ResourceCreate, ResourceUpdate, AdminLogin

router = APIRouter(prefix="/resources/admin", tags=["Resources - Admin"])


# ─────────────────────────────────────────────
# SLUG GENERATOR (FIXED)
# ─────────────────────────────────────────────
def generate_slug(title: str) -> str:
    base = re.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')
    return f"{base}-{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
@router.post("/login")
def admin_login(credentials: AdminLogin):
    result = auth_db().table("admin_users").select("*") \
        .eq("username", credentials.username).single().execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(credentials.password, result.data["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = result.data
    session = create_session(user["id"])

    return {
        "token": session["token"],
        "expires_at": session["expires_at"],
        "admin": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
        },
    }


@router.post("/logout")
def admin_logout(session=Depends(get_admin_session)):
    auth_db().table("admin_sessions").delete().eq("id", session["id"]).execute()
    return {"message": "Logged out successfully"}


# ─────────────────────────────────────────────
# LIST RESOURCES
# ─────────────────────────────────────────────
@router.get("/")
def list_all_resources(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    search: Optional[str] = None,
    published: Optional[bool] = None,
    session=Depends(get_admin_session),
):
    return db.admin_list_resources(
        page=page,
        per_page=per_page,
        category=category,
        search=search,
        published=published,
    )


# ─────────────────────────────────────────────
# CREATE RESOURCE (FIXED COMPLETELY)
# ─────────────────────────────────────────────

@router.post("/")
async def create_resource(
    file: UploadFile = File(...),
    thumbnail: Optional[UploadFile] = File(None),

    title: str = Form(...),
    description: Optional[str] = Form(None),
    category: str = Form("general"),
    tags: str = Form(""),
    featured: bool = Form(False),
    published: bool = Form(False),
    author: str = Form("ATRBA Team"),

    session=Depends(get_admin_session),
):
    try:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]

        slug = generate_slug(title)

        meta_in = ResourceCreate(
            title=title,
            description=description,
            category=category,
            tags=tag_list,
            featured=featured,
            published=published,
            author=author,
            slug=slug,   # REQUIRED FIX
        )

        file_meta = await storage.upload_resource_file(file)

        thumb_meta = None
        if thumbnail and thumbnail.filename:
            try:
                thumb_meta = await storage.upload_thumbnail(thumbnail)
            except Exception as e:
                print("⚠️ Thumbnail upload failed, continuing without it:", e)
                thumb_meta = None

        return db.create_resource(meta_in, file_meta, thumb_meta)

    except Exception as e:
        import traceback
        print("🔥 CREATE RESOURCE FAILED:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
# ─────────────────────────────────────────────
# GET SINGLE RESOURCE
# ─────────────────────────────────────────────
@router.get("/{resource_id}")
def get_resource(resource_id: str, session=Depends(get_admin_session)):
    return db.get_resource_by_id(resource_id, admin=True)


# ─────────────────────────────────────────────
# UPDATE RESOURCE
# ─────────────────────────────────────────────
@router.put("/{resource_id}")
async def update_resource(
    resource_id: str,
    thumbnail: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    featured: Optional[bool] = Form(None),
    published: Optional[bool] = Form(None),
    author: Optional[str] = Form(None),

    session=Depends(get_admin_session),
):
    tag_list = None
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]

    data = ResourceUpdate(
        title=title,
        description=description,
        category=category,
        tags=tag_list,
        featured=featured,
        published=published,
        author=author,
    )

    thumb_meta = None
    if thumbnail and thumbnail.filename:
        existing = db.get_resource_by_id(resource_id, admin=True)
        if existing.get("thumbnail_path"):
            storage.delete_thumbnail(existing["thumbnail_path"])

        thumb_meta = await storage.upload_thumbnail(thumbnail)

    return db.update_resource(resource_id, data, thumb_meta)


# ─────────────────────────────────────────────
# DELETE
# ─────────────────────────────────────────────
@router.delete("/{resource_id}")
def delete_resource(resource_id: str, session=Depends(get_admin_session)):
    deleted = db.delete_resource_record(resource_id)

    if deleted.get("file_path"):
        storage.delete_resource_file(deleted["file_path"])

    if deleted.get("thumbnail_path"):
        storage.delete_thumbnail(deleted["thumbnail_path"])

    return {"message": "Resource deleted successfully", "id": resource_id}


# ─────────────────────────────────────────────
# TOGGLES
# ─────────────────────────────────────────────
class PublishToggle(BaseModel):
    published: bool


@router.patch("/{resource_id}/publish")
def toggle_publish(
    resource_id: str,
    payload: PublishToggle,
    session=Depends(get_admin_session),
):
    return db.update_resource(
        resource_id,
        ResourceUpdate(published=payload.published)
    )

@router.patch("/{resource_id}/featured")
def toggle_featured(
    resource_id: str,
    featured: bool = Query(...),
    session=Depends(get_admin_session),
):
    return db.update_resource(resource_id, ResourceUpdate(featured=featured))


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────
@router.get("/{resource_id}/analytics")
def get_analytics(resource_id: str, session=Depends(get_admin_session)):
    return db.get_download_analytics(resource_id)