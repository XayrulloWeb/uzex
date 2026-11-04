"""
UZEX Synapse FastAPI Backend Server
Provides REST API endpoints for natural language query execution,
exchange statistics, sector analytics, and serves the production frontend.
"""

import os
import sys
import sqlite3
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine import UzexQueryEngine, DB_PATH
import build_db

# Auto-build database on startup if missing
if not os.path.exists(DB_PATH):
    print("Database uzex.db not found. Building from CSVs (~14 seconds)...")
    build_db.main()

app = FastAPI(title="UZEX Synapse Cognitive Exchange API", version="2.0")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = UzexQueryEngine()

class QueryRequest(BaseModel):
    query: str

@app.post("/api/query")
async def execute_query(req: QueryRequest):
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    result = engine.query(q)
    return result

@app.get("/api/stats")
async def get_overview_stats():
    conn = engine.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                COUNT(*) as total_deals,
                SUM(deal_amount_uzs) as total_volume_uzs,
                COUNT(DISTINCT seller_inn) as sellers_count,
                COUNT(DISTINCT buyer_inn) as buyers_count,
                MIN(deal_date) as start_date,
                MAX(deal_date) as end_date
            FROM deals
        """)
        row = cur.fetchone()

        cur.execute("SELECT COUNT(*) FROM contracts")
        contracts_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM brokers")
        brokers_cnt = cur.fetchone()[0]

        # Latest USD rate
        cur.execute("SELECT rate_date, usd_rate FROM usd_rates ORDER BY rate_date DESC LIMIT 1")
        latest_usd = cur.fetchone()

        return {
            "total_deals": row["total_deals"],
            "total_volume_uzs": row["total_volume_uzs"],
            "sellers_count": row["sellers_count"],
            "buyers_count": row["buyers_count"],
            "contracts_count": contracts_cnt,
            "brokers_count": brokers_cnt,
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "latest_usd_rate": latest_usd["usd_rate"] if latest_usd else 12850.0,
            "latest_usd_date": latest_usd["rate_date"] if latest_usd else "2026-10-30"
        }
    finally:
        conn.close()

@app.get("/api/sectors")
async def get_sectors_breakdown():
    conn = engine.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                c.category,
                COUNT(d.deal_num) as deals_count,
                SUM(d.deal_amount_uzs) as total_uzs
            FROM contracts c
            JOIN deals d ON d.contract_num = c.contract_num
            GROUP BY c.category
            ORDER BY total_uzs DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        return {"sectors": rows}
    finally:
        conn.close()

@app.get("/api/recent-deals")
async def get_recent_deals():
    conn = engine.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                deal_num, deal_date, deal_time, product_name, 
                quantity, unit, deal_amount_uzs, currency, status, region
            FROM deals
            ORDER BY deal_num DESC
            LIMIT 15
        """)
        rows = [dict(r) for r in cur.fetchall()]
        return {"deals": rows}
    finally:
        conn.close()

# Mount frontend build if available
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
