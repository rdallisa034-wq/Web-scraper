#!/usr/bin/env python3
"""
API Manajemen Token — MaxPreps Scraper

Jalankan:
  pip install fastapi uvicorn
  export ADMIN_API_KEY="rahasia-anda"
  uvicorn api:app --host 0.0.0.0 --port 8000

Auth: header  Authorization: Bearer <ADMIN_API_KEY>
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import (
    ensure_tokens_file,
    ensure_users_file,
    create_token,
    list_tokens,
    get_token,
    delete_token,
    set_token_active,
    add_token_credits,
    token_status,
    scrape_credit_cost,
    get_settings,
    save_settings,
    log_access,
    COST_PER_STATE,
    COST_ALL_STATES,
    COST_TOP25,
)

ensure_users_file()
ensure_tokens_file()

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "ganti-api-key-ini")

app = FastAPI(
    title="MaxPreps Token API",
    description="Manajemen token credit / waktu untuk scraper",
    version="1.0.0",
)


def require_admin(authorization: Optional[str] = Header(None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Butuh header: Authorization: Bearer <ADMIN_API_KEY>")
    key = authorization[7:].strip()
    if key != ADMIN_API_KEY:
        raise HTTPException(403, "API key salah")


# ---------- models ----------

class CreateTokenIn(BaseModel):
    mode: str = Field(..., description="credit atau time")
    credits: int = Field(0, description="Wajib >0 jika mode=credit")
    valid_days: float = Field(0, description="Wajib >0 jika mode=time")
    label: str = ""


class CreditsIn(BaseModel):
    amount: int = Field(..., description="Bisa negatif untuk mengurangi")


class SettingsIn(BaseModel):
    buy_token_url: Optional[str] = None
    buy_token_text: Optional[str] = None
    buy_token_message: Optional[str] = None
    buy_token_enabled: Optional[bool] = None


class CostQuery(BaseModel):
    is_all: bool = False
    top25_on: bool = False


# ---------- endpoints ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/costs")
def costs():
    """Tarif credit scrape."""
    return {
        "per_state": COST_PER_STATE,
        "all_states": COST_ALL_STATES,
        "top25_addon": COST_TOP25,
        "examples": {
            "1_state": scrape_credit_cost(is_all=False, top25_on=False),
            "1_state_top25": scrape_credit_cost(is_all=False, top25_on=True),
            "all": scrape_credit_cost(is_all=True, top25_on=False),
            "all_top25": scrape_credit_cost(is_all=True, top25_on=True),
        },
    }


@app.post("/v1/tokens", dependencies=[Depends(require_admin)])
def api_create_token(body: CreateTokenIn):
    mode = body.mode.strip().lower()
    if mode == "credit":
        ok, msg, info = create_token(
            "credit", credits=body.credits, label=body.label, created_by="api"
        )
    elif mode == "time":
        ok, msg, info = create_token(
            "time", valid_days=body.valid_days, label=body.label, created_by="api"
        )
    else:
        raise HTTPException(400, "mode harus credit atau time")
    if not ok or not info:
        raise HTTPException(400, msg)
    log_access("api", "create_token", f"{info['mode']}:{info['token']}")
    return {"ok": True, "message": msg, "token": info}


@app.get("/v1/tokens", dependencies=[Depends(require_admin)])
def api_list_tokens():
    return {"ok": True, "tokens": list_tokens()}


@app.get("/v1/tokens/{token}")
def api_get_token(token: str):
    """Cek status token (tanpa admin key — hanya info terbatas)."""
    status, msg, session = token_status(token)
    info = get_token(token)
    if status != "ok":
        return {
            "ok": False,
            "status": status,
            "message": msg,
            "token": None,
        }
    # jangan expose semua field internal
    return {
        "ok": True,
        "status": status,
        "message": msg,
        "token": {
            "token": info.get("token"),
            "mode": info.get("mode"),
            "label": info.get("label"),
            "credits": info.get("credits") if info.get("mode") == "credit" else None,
            "expires_at": info.get("expires_at") if info.get("mode") == "time" else None,
            "active": info.get("active"),
            "use_count": info.get("use_count"),
        },
    }


@app.delete("/v1/tokens/{token}", dependencies=[Depends(require_admin)])
def api_delete_token(token: str):
    ok, msg = delete_token(token)
    if not ok:
        raise HTTPException(404, msg)
    log_access("api", "delete_token", token)
    return {"ok": True, "message": msg}


@app.post("/v1/tokens/{token}/credits", dependencies=[Depends(require_admin)])
def api_add_credits(token: str, body: CreditsIn):
    ok, msg = add_token_credits(token, body.amount)
    if not ok:
        raise HTTPException(400, msg)
    log_access("api", "add_credits", f"{token}:{body.amount}")
    info = get_token(token)
    return {"ok": True, "message": msg, "credits": info.get("credits") if info else None}


@app.post("/v1/tokens/{token}/activate", dependencies=[Depends(require_admin)])
def api_activate(token: str):
    ok, msg = set_token_active(token, True)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True, "message": msg}


@app.post("/v1/tokens/{token}/deactivate", dependencies=[Depends(require_admin)])
def api_deactivate(token: str):
    ok, msg = set_token_active(token, False)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True, "message": msg}


@app.get("/v1/settings/buy-token", dependencies=[Depends(require_admin)])
def api_get_buy_settings():
    return {"ok": True, "settings": get_settings()}


@app.put("/v1/settings/buy-token", dependencies=[Depends(require_admin)])
def api_put_buy_settings(body: SettingsIn):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    ok, msg = save_settings(**kwargs)
    return {"ok": ok, "message": msg, "settings": get_settings()}
