"""
ATRBA + Blog CMS — Combined FastAPI Backend
Handles lead capture (ATRBA) and full blog CMS with admin panel.
"""

"""
ATRBA + Blog CMS — Combined FastAPI Backend
Handles lead capture (ATRBA) and full blog CMS with admin panel.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
from fastapi import FastAPI, HTTPException, Depends, Header, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import re
import uuid
import bcrypt
import secrets
import bleach
from supabase import create_client, Client
from dotenv import load_dotenv

# ── Environment ───────────────────────────────────────────────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")  # service_role key

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment variables")

# ── Supabase client (single global instance) ──────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ATRBA + Blog CMS API",
    description="Lead capture and blog CMS backend",
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.abovetherestadvisors.com"],          # Tighten this to your domain(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# HTML SANITISATION (for blog content stored as raw HTML)
# Strips dangerous tags/attributes before storing; preserves rich formatting.
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr", "blockquote", "pre", "code",
    "strong", "em", "u", "s", "mark",
    "ul", "ol", "li",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "div", "span", "figure", "figcaption",
]

ALLOWED_ATTRS = {
    "*": ["class", "style", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height", "loading"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

def sanitize_html(html: str) -> str:
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────────────────────────────────────

# ── Leads ─────────────────────────────────────────────────────────────────────
class LeadCreate(BaseModel):
    first_name: str
    last_name: str = ""
    email: EmailStr
    company_name: str = ""
    annual_revenue_range: str = ""
    primary_area_of_interest: str = ""
    message: str = ""

    @field_validator("first_name")
    @classmethod
    def first_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("first_name is required")
        return v.strip()

    @field_validator("email", mode="before")
    @classmethod
    def email_not_empty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("email is required")
        return v


class LeadResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    company_name: str
    annual_revenue_range: str
    primary_area_of_interest: str
    message: str
    created_at: str


class SuccessResponse(BaseModel):
    success: bool
    message: str
    data: LeadResponse


# ── Blog ──────────────────────────────────────────────────────────────────────
class BlogCreate(BaseModel):
    title: str
    slug: Optional[str] = None
    content: str
    excerpt: Optional[str] = None
    category: str = "general"
    featured: bool = False
    read_time: int = 5
    cover_image: Optional[str] = None
    author: str = "Admin"
    published: bool = False

    @field_validator("slug", mode="before")
    @classmethod
    def generate_slug(cls, v, info):
        if not v:
            title = info.data.get("title", "")
            slug = re.sub(r"[^\w\s-]", "", title.lower())
            return re.sub(r"[-\s]+", "-", slug).strip("-")
        return v

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        return sanitize_html(v)


class BlogUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    category: Optional[str] = None
    featured: Optional[bool] = None
    read_time: Optional[int] = None
    cover_image: Optional[str] = None
    published: Optional[bool] = None

    @field_validator("content", mode="before")
    @classmethod
    def sanitize_content(cls, v):
        return sanitize_html(v) if v else v


class AdminLogin(BaseModel):
    username: str
    password: str


# ─────────────────────────────────────────────────────────────────────────────
# AUTH HELPER
# ─────────────────────────────────────────────────────────────────────────────
async def get_admin_user(authorization: Optional[str] = Header(None)):
    """Validate Bearer token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ", 1)[1]

    result = (
        supabase.table("admin_sessions")
        .select("*, admin_users(*)")
        .eq("token", token)
        .gte("expires_at", datetime.now(timezone.utc).isoformat())
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return result.data


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "ATRBA + Blog CMS API", "version": "1.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE UPLOAD ENDPOINT
# Accepts a multipart file, stores it in Supabase Storage bucket "blog-images",
# and returns the public URL for Quill to insert as <img src="...">.
# ─────────────────────────────────────────────────────────────────────────────
BLOG_IMAGES_BUCKET = "blog-images"

@app.post("/upload-image", tags=["Blog - Admin"])
async def upload_image(file: UploadFile = File(...), session=Depends(get_admin_user)):
    """Upload an image to Supabase Storage and return its public URL."""
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    object_name = f"{uuid.uuid4().hex}.{ext}"

    contents = await file.read()

    try:
        supabase.storage.from_(BLOG_IMAGES_BUCKET).upload(
            path=object_name,
            file=contents,
            file_options={"content-type": file.content_type},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(exc)}")

    public_url = supabase.storage.from_(BLOG_IMAGES_BUCKET).get_public_url(object_name)

    return {"url": public_url}


# ─────────────────────────────────────────────────────────────────────────────
# LEADS ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.post(
    "/leads",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Leads"],
    summary="Create a new lead",
)
def create_lead(lead: LeadCreate):
    payload = {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "email": lead.email,
        "company_name": lead.company_name,
        "annual_revenue_range": lead.annual_revenue_range,
        "primary_area_of_interest": lead.primary_area_of_interest,
        "message": lead.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "website_contact_form",
    }

    try:
        result = supabase.table("leads").insert(payload).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(exc)}",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Insert succeeded but returned no data.",
        )

    return SuccessResponse(
        success=True,
        message="Lead received. We will be in touch within 24 business hours.",
        data=LeadResponse(**result.data[0]),
    )


@app.get(
    "/leads",
    tags=["Leads"],
    summary="List all leads (internal use)",
)
def list_leads(limit: int = 100, offset: int = 0):
    try:
        result = (
            supabase.table("leads")
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(exc)}",
        )

    return {"success": True, "count": len(result.data), "data": result.data}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC BLOG ENDPOINTS
# IMPORTANT: fixed-path routes (/blogs/featured) MUST be declared before
# parameterised routes (/blogs/{slug}) — FastAPI matches top-to-bottom.
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/blogs/featured", tags=["Blog - Public"])
async def get_featured_blogs():
    """Return up to 5 featured published posts."""
    result = (
        supabase.table("blogs")
        .select("id, title, slug, excerpt, category, featured, read_time, cover_image, author, created_at")
        .eq("featured", True)
        .eq("published", True)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    return result.data or []


@app.get("/blogs/category/{category}", tags=["Blog - Public"])
async def get_blogs_by_category(category: str):
    """Return all published posts for a given category."""
    result = (
        supabase.table("blogs")
        .select("id, title, slug, excerpt, category, featured, read_time, cover_image, author, created_at")
        .eq("category", category)
        .eq("published", True)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@app.get("/blogs", tags=["Blog - Public"])
async def get_blogs(limit: int = 10, offset: int = 0):
    """Paginated list of published blog posts (no full content)."""
    result = (
        supabase.table("blogs")
        .select("id, title, slug, excerpt, category, featured, read_time, cover_image, author, published, created_at, updated_at")
        .eq("published", True)
        .order("created_at", desc=True)
        .limit(limit)
        .offset(offset)
        .execute()
    )
    return result.data or []


@app.get("/blogs/{slug}", tags=["Blog - Public"])
async def get_blog_by_slug(slug: str):
    """Single published post by slug — includes full HTML content."""
    result = (
        supabase.table("blogs")
        .select("*")
        .eq("slug", slug)
        .eq("published", True)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return result.data


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/admin/login", tags=["Blog - Admin"])
async def admin_login(credentials: AdminLogin):
    """Authenticate admin; returns a 24-hour session token."""
    result = (
        supabase.table("admin_users")
        .select("*")
        .eq("username", credentials.username)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = result.data
    if not bcrypt.checkpw(
        credentials.password.encode("utf-8"),
        user["password_hash"].encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    supabase.table("admin_sessions").insert({
        "admin_id": user["id"],
        "token": token,
        "expires_at": expires_at.isoformat(),
    }).execute()

    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "admin": {"id": user["id"], "username": user["username"], "email": user["email"]},
    }


@app.post("/admin/logout", tags=["Blog - Admin"])
async def admin_logout(session=Depends(get_admin_user)):
    """Invalidate the current session token."""
    supabase.table("admin_sessions").delete().eq("id", session["id"]).execute()
    return {"message": "Logged out successfully"}


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN BLOG ENDPOINTS  (all require valid Bearer token)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/blogs", tags=["Blog - Admin"])
async def admin_get_all_blogs(session=Depends(get_admin_user)):
    """Return ALL posts including unpublished drafts (DEV MODE - no auth)."""
    result = (
        supabase.table("blogs")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@app.post("/admin/blogs", tags=["Blog - Admin"])
async def admin_create_blog(blog: BlogCreate, session=Depends(get_admin_user)):
    """Create a new blog post."""
    data = blog.model_dump()

    # Ensure slug uniqueness
    existing = supabase.table("blogs").select("id").eq("slug", data["slug"]).execute()
    if existing.data:
        data["slug"] = f"{data['slug']}-{uuid.uuid4().hex[:6]}"

    result = supabase.table("blogs").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create blog post")
    return result.data[0]


@app.put("/admin/blogs/{blog_id}", tags=["Blog - Admin"])
async def admin_update_blog(
    blog_id: str,
    blog: BlogUpdate,
    session=Depends(get_admin_user),
):
    """Update an existing blog post (partial update — only supplied fields)."""
    data = {k: v for k, v in blog.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = supabase.table("blogs").update(data).eq("id", blog_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return result.data[0]


@app.delete("/admin/blogs/{blog_id}", tags=["Blog - Admin"])
async def admin_delete_blog(blog_id: str, session=Depends(get_admin_user)):
    """Permanently delete a blog post."""
    supabase.table("blogs").delete().eq("id", blog_id).execute()
    return {"message": "Blog post deleted successfully"}


@app.patch("/admin/blogs/{blog_id}/featured", tags=["Blog - Admin"])
async def toggle_featured(blog_id: str, featured: bool, session=Depends(get_admin_user)):
    """Set or unset a post as featured."""
    result = supabase.table("blogs").update({"featured": featured}).eq("id", blog_id).execute()
    return result.data[0] if result.data else {}


@app.patch("/admin/blogs/{blog_id}/publish", tags=["Blog - Admin"])
async def toggle_published(blog_id: str, published: bool, session=Depends(get_admin_user)):
    """Publish or unpublish a post."""
    result = supabase.table("blogs").update({"published": published}).eq("id", blog_id).execute()
    return result.data[0] if result.data else {}
