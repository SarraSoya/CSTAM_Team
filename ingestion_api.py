import os
import json
import logging
from typing import Dict
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from passlib.context import CryptContext
from kafka import KafkaProducer

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# --- Configuration (using environment variables for security) ---
class Settings:
    """
    Application settings loaded from environment variables.
    """

    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
    )
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your_super_secret_key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    KAFKA_TOPIC_HEARTRATE: str = "heartrate"
    KAFKA_TOPIC_CALORIES: str = "calories"
    KAFKA_TOPIC_STEPS: str = "steps"


settings = Settings()

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Secure Fitness Data Ingestion API",
    description="A secure API to ingest fitness data streams into Kafka topics.",
    version="1.0.0",
)

# --- Security and Authentication ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# In a real-world scenario, you would connect to a database to manage users.
# For this example, we'll use a hardcoded user.
# IMPORTANT: In a production environment, never hardcode credentials like this.
users_db = {
    "user123": {
        "username": "user123",
        "hashed_password": pwd_context.hash("securepassword"),
    }
}


def verify_password(plain_password, hashed_password):
    """Verifies a plain-text password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_user(username: str):
    """Retrieves a user from the mock database."""
    if username in users_db:
        user_dict = users_db[username]
        return user_dict
    return None


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """Creates a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Dependency to get the current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username=username)
    if user is None:
        raise credentials_exception
    return user


# --- Kafka Producer Setup ---
kafka_producer = None


@app.on_event("startup")
async def startup_event():
    """Initializes the Kafka producer on application startup."""
    global kafka_producer
    try:
        kafka_producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        logging.info("Successfully connected to Kafka.")
    except Exception as e:
        logging.error(f"Failed to connect to Kafka: {e}")
        kafka_producer = None


@app.on_event("shutdown")
def shutdown_event():
    """Closes the Kafka producer on application shutdown."""
    if kafka_producer:
        kafka_producer.close()
        logging.info("Kafka producer closed.")


def convert_to_json_serializable(obj):
    """Converts objects to a JSON-serializable format, specifically datetimes."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Handle other types if needed, or simply return the object
    return obj


def publish_to_kafka(topic: str, data: Dict):
    """
    Publishes a message to a Kafka topic.
    Returns True on success, False otherwise.
    """
    if not kafka_producer:
        logging.error("Kafka producer is not initialized.")
        return False
    try:
        # Convert any non-serializable objects (like datetime) to strings
        serializable_data = {
            k: convert_to_json_serializable(v) for k, v in data.items()
        }
        future = kafka_producer.send(topic, value=serializable_data)
        future.get(timeout=10)  # Wait for the message to be sent
        logging.info(f"Published data to topic '{topic}': {serializable_data}")
        return True
    except Exception as e:
        logging.error(f"Failed to publish to Kafka topic '{topic}': {e}")
        return False


# --- Pydantic Data Models for Ingestion ---
class HeartRate(BaseModel):
    user_id: str
    time: datetime
    heart_rate: int = Field(..., ge=0, le=250)


class Calories(BaseModel):
    user_id: str
    time: datetime
    calories: float = Field(..., ge=0)


class Steps(BaseModel):
    user_id: str
    time: datetime
    steps: int = Field(..., ge=0)


# --- API Endpoints ---
@app.post("/token", tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticates a user and returns a JWT access token.
    """
    user = get_user(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/ingest/heartrate", tags=["Data Ingestion"])
async def ingest_heartrate(
    data: HeartRate, current_user: dict = Depends(get_current_user)
):
    """
    Ingests heart rate data into the 'heartrate' Kafka topic.
    This endpoint requires authentication.
    """
    if publish_to_kafka(settings.KAFKA_TOPIC_HEARTRATE, data.dict()):
        return {
            "status": "success",
            "message": "Heart rate data ingested successfully.",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest data into Kafka.",
        )


@app.post("/ingest/calories", tags=["Data Ingestion"])
async def ingest_calories(
    data: Calories, current_user: dict = Depends(get_current_user)
):
    """
    Ingests calories data into the 'calories' Kafka topic.
    This endpoint requires authentication.
    """
    if publish_to_kafka(settings.KAFKA_TOPIC_CALORIES, data.dict()):
        return {"status": "success", "message": "Calories data ingested successfully."}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest data into Kafka.",
        )


@app.post("/ingest/steps", tags=["Data Ingestion"])
async def ingest_steps(data: Steps, current_user: dict = Depends(get_current_user)):
    """
    Ingests steps data into the 'steps' Kafka topic.
    This endpoint requires authentication.
    """
    if publish_to_kafka(settings.KAFKA_TOPIC_STEPS, data.dict()):
        return {"status": "success", "message": "Steps data ingested successfully."}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest data into Kafka.",
        )


# --- Main execution block for local development ---
if __name__ == "__main__":
    import uvicorn

    # Make sure to set the environment variables before running:
    # export KAFKA_BOOTSTRAP_SERVERS="localhost:9092"
    # export SECRET_KEY="your_super_secret_key"
    uvicorn.run(app, host="0.0.0.0", port=8000)
