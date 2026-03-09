import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, HttpUrl, Field
from sqlalchemy import (
    create_engine,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    mapped_column,
    Mapped,
    relationship,
    sessionmaker,
    Session,
)
import redis
import secrets


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/url_shortener",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"

INACTIVE_DELETE_DAYS = int(os.getenv("INACTIVE_DELETE_DAYS", "30"))

class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


redis_client = redis.from_url(REDIS_URL, decode_responses=True)


def cache_key_for_short_code(short_code: str) -> str:
    return f"link:{short_code}"


def cache_key_for_stats(short_code: str) -> str:
    return f"link_stats:{short_code}"


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    links: Mapped[List["Link"]] = relationship("Link", back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    owner_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    links: Mapped[List["Link"]] = relationship("Link", back_populates="project")


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    short_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    original_url: Mapped[str] = mapped_column(Text, index=True)
    owner_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    click_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    owner: Mapped[Optional[User]] = relationship("User", back_populates="links")
    project: Mapped[Optional[Project]] = relationship(
        "Project", back_populates="links"
    )


class ExpiredLinkHistory(Base):
    __tablename__ = "expired_links_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    short_code: Mapped[str] = mapped_column(String(32), index=True)
    original_url: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    click_count: Mapped[int] = mapped_column(Integer)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserCreate(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LinkCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: Optional[str] = Field(
        default=None, description="Optional custom short code"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiry datetime (ISO8601, minute precision, UTC recommended)",
    )
    project_id: Optional[int] = Field(
        default=None, description="Optional project grouping identifier"
    )


class LinkUpdate(BaseModel):
    # Можно поменять short_code
    new_short_code: Optional[str] = Field(
        default=None, description="New short code to assign"
    )
    # А можно прилинковать short_code к новому original_url
    new_original_url: Optional[HttpUrl] = Field(
        default=None, description="New original URL for existing short link"
    )
    expires_at: Optional[datetime] = Field(
        default=None, description="New expiry datetime"
    )
    project_id: Optional[int] = Field(
        default=None, description="Change project association"
    )


class LinkOut(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    expires_at: Optional[datetime]
    project_id: Optional[int]

    class Config:
        from_attributes = True


class LinkStats(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    click_count: int
    last_accessed_at: Optional[datetime]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class ExpiredLinkOut(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    expired_at: datetime
    click_count: int
    last_accessed_at: Optional[datetime]

    class Config:
        from_attributes = True


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_user(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


async def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(db, int(user_id))
    if user is None:
        raise credentials_exception
    return user


ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_short_code(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def ensure_unique_short_code(db: Session, desired: Optional[str] = None) -> str:
    if desired:
        exists = db.query(Link).filter(Link.short_code == desired, Link.deleted is False).first()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Custom alias already in use",
            )
        return desired

    while True:
        candidate = generate_short_code()
        exists = db.query(Link).filter(Link.short_code == candidate, Link.deleted is False).first()
        if not exists:
            return candidate


def move_to_history_and_delete(db: Session, link: Link, expired_at: datetime) -> None:
    history = ExpiredLinkHistory(
        short_code=link.short_code,
        original_url=link.original_url,
        owner_id=link.owner_id,
        project_id=link.project_id,
        created_at=link.created_at,
        expired_at=expired_at,
        click_count=link.click_count,
        last_accessed_at=link.last_accessed_at,
    )
    db.add(history)
    db.delete(link)
    redis_client.delete(cache_key_for_short_code(link.short_code))
    redis_client.delete(cache_key_for_stats(link.short_code))


def cleanup_expired_and_inactive_links(db: Session) -> None:
    now = datetime.now(timezone.utc)
    expired_links = (
        db.query(Link)
        .filter(
            Link.deleted is False,
            Link.expires_at.isnot(None),
            Link.expires_at <= now,
        )
        .all()
    )
    for link in expired_links:
        move_to_history_and_delete(db, link, expired_at=link.expires_at or now)
    threshold = now - timedelta(days=INACTIVE_DELETE_DAYS)
    inactive_links = (
        db.query(Link)
        .filter(
            Link.deleted is False,
            Link.last_accessed_at.isnot(None),
            Link.last_accessed_at <= threshold,
        )
        .all()
    )
    for link in inactive_links:
        move_to_history_and_delete(db, link, expired_at=now)

    db.commit()


app = FastAPI(title="URL Shortener Service")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.post("/auth/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_email(db, user_in.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/token", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = get_user_by_email(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )
    access_token = create_access_token({"sub": str(user.id)})
    return Token(access_token=access_token)


@app.post("/links/shorten", response_model=LinkOut)
def create_short_link(
    payload: LinkCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    auth_header = request.headers.get("Authorization")
    current_user: Optional[User] = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload_token = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            user_id = int(payload_token.get("sub"))
            current_user = get_user(db, user_id)
        except Exception:
            current_user = None

    cleanup_expired_and_inactive_links(db)

    short_code = ensure_unique_short_code(db, payload.custom_alias)
    link = Link(
        short_code=short_code,
        original_url=str(payload.original_url),
        owner_id=current_user.id if current_user else None,
        project_id=payload.project_id,
        expires_at=payload.expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    redis_client.set(cache_key_for_short_code(short_code), link.original_url)
    redis_client.delete(cache_key_for_stats(short_code))

    return LinkOut(
        short_code=link.short_code,
        original_url=link.original_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
        project_id=link.project_id,
    )


@app.get("/{short_code}")
def redirect_short_link(short_code: str, db: Session = Depends(get_db)):
    cleanup_expired_and_inactive_links(db)

    cached_url = redis_client.get(cache_key_for_short_code(short_code))
    if cached_url:
        link = (
            db.query(Link)
            .filter(Link.short_code == short_code, Link.deleted is False)
            .first()
        )
        if link:
            link.click_count += 1
            link.last_accessed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(link)
            redis_client.delete(cache_key_for_stats(short_code))
        return RedirectResponse(url=cached_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    link = (
        db.query(Link)
        .filter(Link.short_code == short_code, Link.deleted is False)
        .first()
    )
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")

    now = datetime.now(timezone.utc)
    if link.expires_at and link.expires_at <= now:
        move_to_history_and_delete(db, link, expired_at=link.expires_at)
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link expired")

    link.click_count += 1
    link.last_accessed_at = now
    db.commit()
    db.refresh(link)

    redis_client.set(cache_key_for_short_code(short_code), link.original_url)
    redis_client.delete(cache_key_for_stats(short_code))

    return RedirectResponse(url=link.original_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/links/{short_code}/stats", response_model=LinkStats)
def get_link_stats(short_code: str, db: Session = Depends(get_db)):
    cleanup_expired_and_inactive_links(db)

    cached = redis_client.hgetall(cache_key_for_stats(short_code))
    if cached:
        return LinkStats(
            short_code=short_code,
            original_url=cached["original_url"],
            created_at=datetime.fromisoformat(cached["created_at"]),
            click_count=int(cached["click_count"]),
            last_accessed_at=datetime.fromisoformat(cached["last_accessed_at"])
            if cached.get("last_accessed_at")
            else None,
            expires_at=datetime.fromisoformat(cached["expires_at"])
            if cached.get("expires_at")
            else None,
        )

    link = (
        db.query(Link)
        .filter(Link.short_code == short_code, Link.deleted is False)
        .first()
    )
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")

    stats = LinkStats(
        short_code=link.short_code,
        original_url=link.original_url,
        created_at=link.created_at,
        click_count=link.click_count,
        last_accessed_at=link.last_accessed_at,
        expires_at=link.expires_at,
    )

    redis_client.hset(
        cache_key_for_stats(short_code),
        mapping={
            "original_url": stats.original_url,
            "created_at": stats.created_at.isoformat(),
            "click_count": str(stats.click_count),
            "last_accessed_at": stats.last_accessed_at.isoformat()
            if stats.last_accessed_at
            else "",
            "expires_at": stats.expires_at.isoformat() if stats.expires_at else "",
        },
    )
    redis_client.expire(cache_key_for_stats(short_code), 300)

    return stats


@app.delete("/links/{short_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    link = (
        db.query(Link)
        .filter(Link.short_code == short_code, Link.deleted is False)
        .first()
    )
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    if link.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to delete this link",
        )

    now = datetime.now(timezone.utc)
    move_to_history_and_delete(db, link, expired_at=now)
    db.commit()

    return


@app.put("/links/{short_code}", response_model=LinkOut)
def update_link(
    short_code: str,
    payload: LinkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    link = (
        db.query(Link)
        .filter(Link.short_code == short_code, Link.deleted is False)
        .first()
    )
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    if link.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to update this link",
        )

    if payload.new_short_code:
        ensure_unique_short_code(db, payload.new_short_code)
        old_code = link.short_code
        link.short_code = payload.new_short_code
        redis_client.delete(cache_key_for_short_code(old_code))
        redis_client.delete(cache_key_for_stats(old_code))

    if payload.new_original_url:
        link.original_url = str(payload.new_original_url)

    if payload.expires_at is not None:
        link.expires_at = payload.expires_at

    if payload.project_id is not None:
        link.project_id = payload.project_id

    db.commit()
    db.refresh(link)

    redis_client.set(cache_key_for_short_code(link.short_code), link.original_url)
    redis_client.delete(cache_key_for_stats(link.short_code))

    return LinkOut(
        short_code=link.short_code,
        original_url=link.original_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
        project_id=link.project_id,
    )


@app.get("/links/search", response_model=List[LinkOut])
def search_links_by_original_url(
    original_url: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    cleanup_expired_and_inactive_links(db)

    query = db.query(Link).filter(
        Link.original_url == original_url,
        Link.deleted is False,
    )

    if current_user:
        query = query.filter(Link.owner_id == current_user.id)
    else:
        query = query.filter(Link.owner_id.is_(None))

    links = query.all()
    return [
        LinkOut(
            short_code=l.short_code,
            original_url=l.original_url,
            created_at=l.created_at,
            expires_at=l.expires_at,
            project_id=l.project_id,
        )
        for l in links
    ]


@app.get("/links/expired", response_model=List[ExpiredLinkOut])
def list_expired_links(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    query = db.query(ExpiredLinkHistory)
    if current_user:
        query = query.filter(ExpiredLinkHistory.owner_id == current_user.id)
    else:
        query = query.filter(ExpiredLinkHistory.owner_id.is_(None))

    records = query.order_by(ExpiredLinkHistory.expired_at.desc()).all()
    return [
        ExpiredLinkOut(
            short_code=r.short_code,
            original_url=r.original_url,
            created_at=r.created_at,
            expired_at=r.expired_at,
            click_count=r.click_count,
            last_accessed_at=r.last_accessed_at,
        )
        for r in records
    ]


@app.get("/projects/{project_id}/links", response_model=List[LinkOut])
def list_links_by_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cleanup_expired_and_inactive_links(db)

    links = (
        db.query(Link)
        .filter(
            Link.project_id == project_id,
            Link.owner_id == current_user.id,
            Link.deleted is False,
        )
        .all()
    )
    return [
        LinkOut(
            short_code=l.short_code,
            original_url=l.original_url,
            created_at=l.created_at,
            expires_at=l.expires_at,
            project_id=l.project_id,
        )
        for l in links
    ]


@app.post("/projects", response_model=dict)
def create_project(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(name=name, owner_id=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "name": project.name}


@app.post("/admin/cleanup", response_model=dict)
def trigger_cleanup(db: Session = Depends(get_db)):
    cleanup_expired_and_inactive_links(db)
    return {"status": "cleanup completed"}


@app.get("/health", response_model=dict)
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

