import math
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Smart Emergency Alert & Response System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not found in .env file")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)

class SOSRequest(BaseModel):
    emergency_type: str
    latitude: float
    longitude: float

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/api/sos")
def trigger_sos(sos: SOSRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT * FROM responders WHERE service_type = %s AND is_available = TRUE",
            (sos.emergency_type,)
        )
        responders = cur.fetchall()

        if not responders:
            raise HTTPException(status_code=404, detail="No available responders nearby")

        nearest = min(
            responders,
            key=lambda r: haversine_km(sos.latitude, sos.longitude, r["latitude"], r["longitude"])
        )
        min_dist = haversine_km(sos.latitude, sos.longitude, nearest["latitude"], nearest["longitude"])

        cur.execute(
            """INSERT INTO alerts (emergency_type, latitude, longitude, status, responder_id)
               VALUES (%s, %s, %s, 'ASSIGNED', %s) RETURNING *""",
            (sos.emergency_type, sos.latitude, sos.longitude, nearest["id"])
        )
        alert = cur.fetchone()

        cur.execute("UPDATE responders SET is_available = FALSE WHERE id = %s", (nearest["id"],))
        conn.commit()

        return {
            "alert": alert,
            "assigned_responder": nearest,
            "distance_km": round(min_dist, 2)
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


    finally:
        cur.close()
        conn.close()
