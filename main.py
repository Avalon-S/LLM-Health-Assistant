from fastapi import FastAPI, HTTPException, Depends
from fastapi.routing import APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from passlib.context import CryptContext
from pydantic import BaseModel
from datetime import datetime, timedelta
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv
from backend.health_chat import router as health_chat_router
from backend.query_pubmed import router as query_pubmed_router
from backend.voice_chat import router as voice_chat_router


load_dotenv() 

# ======== SQLite Settings ========
DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ======== User Table ========
class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True, index=True)
    hashed_password = Column(String, nullable=False)
    gender = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    medical_history = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

# ======== Password encryption settings ========
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ======== JWT Configuration ========
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1 # Expiration time (x min)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})  # Add expiration time
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise JWTError
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ======== Pinecone Initialization ========
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "healthassistant"
embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

pc = Pinecone(api_key=PINECONE_API_KEY, environment="us-east-1-aws")
existing_indexes = [index["name"] for index in pc.list_indexes()]
if INDEX_NAME not in existing_indexes:
    pc.create_index(name=INDEX_NAME, dimension=384, metric="cosine")

pinecone_index = pc.Index(INDEX_NAME)

# ======== FastAPI Application ========
app = FastAPI()

# Mount the static file directory
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Integrate sub-applications using APIRouter
router = APIRouter()
router.include_router(health_chat_router)
router.include_router(query_pubmed_router)
router.include_router(voice_chat_router)

app.include_router(router)

# ======== Pydantic Data Model========
class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    gender: str
    age: int
    medical_history: str

# ======== Dependency: Get a database session ========
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ======== Register (auto login) ========
@app.post("/api/authenticate")
def authenticate(user: LoginRequest, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()

    if db_user:
        if not pwd_context.verify(user.password, db_user.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect password.")
    else:
        hashed_password = pwd_context.hash(user.password)
        new_user = User(username=user.username, hashed_password=hashed_password)
        db.add(new_user)
        db.commit()

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Authenticating user access to the Dashboard
@app.get("/api/verify")
def verify_dashboard(token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    return {"username": username}


# ======== Get user information ========
@app.get("/api/user/{username}")
def get_user(username: str, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = verify_token(token)
    if current_user != username:
        raise HTTPException(status_code=403, detail="Access denied.")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user.username, "gender": user.gender, "age": user.age, "medical_history": user.medical_history}

# ======== Update user information (overwrite storage) ========
@app.put("/api/user/{username}")
def update_user(username: str, profile: UserProfile, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = verify_token(token)
    if current_user != username:
        raise HTTPException(status_code=403, detail="Access denied.")

    # Updating SQLite Data
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.gender = profile.gender
    user.age = profile.age
    user.medical_history = profile.medical_history
    db.commit()

    # Delete Profile data (keep other data)
    try:
        pinecone_index.delete(ids=[f"profile-{username}"], namespace=username)  # 只删除用户的 Profile 数据
    except Exception as e:
        print(f"Error deleting profile from Pinecone for user {username}: {e}")

    # Upload new Profile data to Pinecone
    try:
        prompt = f"My gender is {user.gender}, my age is {user.age}, and I have a medical history of {user.medical_history}."
        vector = embedding_model.encode([prompt])[0].tolist()
        pinecone_index.upsert([(f"profile-{username}", vector, {"text": prompt})], namespace=username)
    except Exception as e:
        print(f"Error uploading profile to Pinecone for user {username}: {e}")

    return {"message": "Profile updated successfully"}


# ======== Processing chat history ========
@app.post("/api/chat")
def chat_with_model(username: str, message: str, token: str = Depends(oauth2_scheme)):
    current_user = verify_token(token)
    if current_user != username:
        raise HTTPException(status_code=403, detail="Access denied.")
    vector = embedding_model.encode([message])[0].tolist()
    pinecone_index.upsert([(f"chat-{username}-{message[:10]}", vector, {"text": message})], namespace=username)
    return {"message": "Chat stored"}

# ======== Query user chat history ========
@app.get("/api/chat/{username}")
def get_chat_history(username: str, top_k: int = 3, token: str = Depends(oauth2_scheme)):
    current_user = verify_token(token)
    if current_user != username:
        raise HTTPException(status_code=403, detail="Access denied.")
    user_query_vector = embedding_model.encode([f"Retrieve last {top_k} messages"]).tolist()
    results = pinecone_index.query(vector=user_query_vector, top_k=top_k, include_metadata=True, namespace=username)

    chat_history = [r["metadata"]["text"] for r in results.get("matches", [])]
    return {"chat_history": chat_history if chat_history else ["No chat history found."]}

# By default, it will jump to index.html
@app.get("/")
def read_root():
    return RedirectResponse(url="/static/index.html")
