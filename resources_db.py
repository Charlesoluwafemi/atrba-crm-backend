"""
ATRBA Resources Hub — Resources DB Service
All database operations for resources and download analytics.
"""

import uuid
from typing import Optional, List
from fastapi import HTTPException
from schemas import ResourceCreate, ResourceUpdate, make_slug

_supabase = None


def init_db(supabase_client):
    global _supabase
    _supabase = supabase_client


def get_client():
    if _supabase is None:
        raise RuntimeError("DB service not initialised")
    return _supabase


# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: file_path ADDED (THIS FIXED YOUR CRASH)
# ─────────────────────────────────────────────────────────────────────────────
SELECT_PUBLIC = (
    "id,title,slug,description,category,tags,file_url,file_name,"
    "file_path,file_type,file_extension,file_size_bytes,thumbnail_url,"
    "featured,published,download_count,author,created_at,updated_at"
)

SELECT_ADMIN = SELECT_PUBLIC


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC LIST
# ─────────────────────────────────────────────────────────────────────────────
def get_published_resources(
    page: int = 1,
    per_page: int = 12,
    category: Optional[str] = None,
    search: Optional[str] = None,
    featured_only: bool = False,
    tag: Optional[str] = None,
) -> dict:

    offset = (page - 1) * per_page

    q = get_client().table("resources").select(SELECT_PUBLIC, count="exact")
    q = q.eq("published", True)

    if category and category != "all":
        q = q.eq("category", category)

    if featured_only:
        q = q.eq("featured", True)

    if tag:
        q = q.contains("tags", [tag.lower()])

    if search:
        q = q.or_(f"title.ilike.%{search}%,description.ilike.%{search}%")

    q = q.order("featured", desc=True).order("created_at", desc=True)
    q = q.range(offset, offset + per_page - 1)

    try:
        result = q.execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    total = result.count or 0

    return {
        "items": result.data or [],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE RESOURCE (SLUG)
# ─────────────────────────────────────────────────────────────────────────────
def get_resource_by_slug(slug: str) -> dict:
    result = (
        get_client()
        .table("resources")
        .select(SELECT_PUBLIC)
        .eq("slug", slug)
        .eq("published", True)
        .limit(1)
        .execute()
    )

    data = result.data

    if not data:
        raise HTTPException(status_code=404, detail="Resource not found")

    return data[0]


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE RESOURCE (ID)
# ─────────────────────────────────────────────────────────────────────────────
def get_resource_by_id(resource_id: str, admin: bool = False) -> dict:
    cols = SELECT_ADMIN if admin else SELECT_PUBLIC

    result = (
        get_client()
        .table("resources")
        .select(cols)
        .eq("id", resource_id)
        .limit(1)
        .execute()
    )

    data = result.data

    if not data:
        raise HTTPException(status_code=404, detail="Resource not found")

    return data[0]


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD TRACKING
# ─────────────────────────────────────────────────────────────────────────────
def record_download(resource_id: str, ip: str, user_agent: str, referrer: str):
    try:
        existing = (
            get_client()
            .table("resources")
            .select("download_count")
            .eq("id", resource_id)
            .limit(1)
            .execute()
        )

        current_count = (
            existing.data[0].get("download_count", 0)
            if existing.data
            else 0
        )

        get_client().table("resources").update(
            {"download_count": current_count + 1}
        ).eq("id", resource_id).execute()

        get_client().table("resource_downloads").insert({
            "resource_id": resource_id,
            "ip_address": ip[:64] if ip else None,
            "user_agent": (user_agent or "")[:512],
            "referrer": (referrer or "")[:512],
        }).execute()

    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN LIST
# ─────────────────────────────────────────────────────────────────────────────
def admin_list_resources(
    page: int = 1,
    per_page: int = 20,
    category: Optional[str] = None,
    search: Optional[str] = None,
    published: Optional[bool] = None,
) -> dict:

    offset = (page - 1) * per_page

    q = get_client().table("resources").select(SELECT_ADMIN, count="exact")

    if category and category != "all":
        q = q.eq("category", category)

    if published is not None:
        q = q.eq("published", published)

    if search:
        q = q.or_(f"title.ilike.%{search}%,description.ilike.%{search}%")

    q = q.order("created_at", desc=True).range(offset, offset + per_page - 1)

    result = q.execute()
    total = result.count or 0

    return {
        "items": result.data or [],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────
def create_resource(data: ResourceCreate, file_meta: dict, thumb_meta: Optional[dict]) -> dict:

    payload = {
        **data.model_dump(),
        **file_meta,
        **(thumb_meta or {"thumbnail_url": None, "thumbnail_path": None}),
    }

    existing = (
        get_client()
        .table("resources")
        .select("id")
        .eq("slug", payload.get("slug"))
        .limit(1)
        .execute()
    )

    if existing.data:
        payload["slug"] = f"{payload['slug']}-{uuid.uuid4().hex[:6]}"

    result = get_client().table("resources").insert(payload).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create resource")

    return result.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────────────────────
def update_resource(resource_id: str, data: ResourceUpdate, thumb_meta: Optional[dict] = None) -> dict:

    payload = {k: v for k, v in data.model_dump().items() if v is not None}

    if thumb_meta:
        payload.update(thumb_meta)

    result = (
        get_client()
        .table("resources")
        .update(payload)
        .eq("id", resource_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Resource not found")

    return result.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# DELETE
# ─────────────────────────────────────────────────────────────────────────────
def delete_resource_record(resource_id: str) -> dict:
    existing = get_resource_by_id(resource_id, admin=True)

    get_client().table("resources").delete().eq("id", resource_id).execute()

    return existing


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────
def get_download_analytics(resource_id: str) -> dict:
    result = (
        get_client()
        .table("resource_downloads")
        .select("downloaded_at,ip_address,referrer")
        .eq("resource_id", resource_id)
        .order("downloaded_at", desc=True)
        .limit(100)
        .execute()
    )

    return {
        "events": result.data or [],
        "total": len(result.data or [])
    }