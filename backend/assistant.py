"""
KisanLink AI Assistant -- optional chat + voice layer.

Adds a Claude-powered chatbot (text) and a Sarvam AI-powered voice layer
(speech-to-text + text-to-speech, Indian languages) on top of the existing
KisanLink API. This file is 100% additive: it does not import from, modify,
or depend on any existing route in main.py -- it only reads the same
commodities_data.json and the same database models everything else already
uses.

Both integrations are OFF by default. If ANTHROPIC_API_KEY / SARVAM_API_KEY
are not set as environment variables, these endpoints return a clear
503 "not configured" response instead of failing -- the rest of the app
(listings, orders, forecasts, hubs) is completely unaffected either way,
whether or not this file is even wired in.

Setup:
    pip install httpx
    # Windows (PowerShell):
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    $env:SARVAM_API_KEY   = "sk_..."
    # macOS/Linux:
    export ANTHROPIC_API_KEY="sk-ant-..."
    export SARVAM_API_KEY="sk_..."
    uvicorn main:app --reload
"""
import json
import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import SessionLocal
import models

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

with open(os.path.join(BASE_DIR, "commodities_data.json")) as f:
    COMMODITIES = {c["name"]: c for c in json.load(f)}

router = APIRouter(prefix="/api", tags=["assistant"])


# --------------------------------------------------------------- context ---
def _build_context() -> str:
    """A compact, live snapshot of app data the assistant can reason over,
    read fresh on every call so it never goes stale."""
    db = SessionLocal()
    try:
        listings = (
            db.query(models.Listing)
            .filter(models.Listing.status != "sold")
            .order_by(models.Listing.created_at.desc())
            .limit(30)
            .all()
        )
        listing_lines = [
            f"- #{l.id} {l.commodity} in {l.district} by {l.farmer_name}: "
            f"Rs.{l.expected_price_per_quintal}/qtl, "
            f"{l.quantity_quintal - sum(o.quantity_ordered for o in l.orders)} qtl left "
            f"({l.status})"
            for l in listings
        ]
    finally:
        db.close()

    commodity_lines = [
        f"- {c['name']}: avg mandi price Rs.{c['avg_mandi_price']}/qtl, "
        f"{c['chosen_model']} forecast (holdout MAPE {c['holdout_mape_pct']}%), "
        f"farmer share ~{c.get('farmer_share_pct', 'n/a')}% of consumer price"
        for c in COMMODITIES.values()
    ]

    return (
        "You are the KisanLink Assistant, built into a farm-to-consumer marketplace app "
        "for Maharashtra (SIH 2026, Problem Statement 26033). You help farmers decide when "
        "to sell and how to list produce, and help buyers understand and choose listings. "
        "Reply in the same language the user writes in. Keep answers short and practical -- "
        "this is often read aloud to a farmer who cannot read, over a voice call, so avoid "
        "long paragraphs and NEVER use markdown formatting (no **bold**, no bullet points, "
        "no headers, no asterisks) -- write plain spoken sentences only, as if talking to "
        "someone out loud. "
        "Only state figures that appear below; if something isn't covered, say so rather "
        "than guessing.\n\n"
        "CURRENT LISTINGS (most recent 30):\n" + "\n".join(listing_lines or ["(none yet)"]) + "\n\n"
        "COMMODITY REFERENCE DATA:\n" + "\n".join(commodity_lines)
    )


# ------------------------------------------------------------------ chat ---
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Text chat, powered by the Claude API."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            503, "The AI assistant isn't configured yet -- set ANTHROPIC_API_KEY to enable it."
        )

    messages = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    messages.append({"role": "user", "content": req.message})

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 500,
                "system": _build_context(),
                "messages": messages,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Claude API error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    reply = "".join(block.get("text", "") for block in data.get("content", []))
    return ChatResponse(reply=reply.strip())


# ----------------------------------------------------------------- voice ---
@router.post("/voice/transcribe")
async def transcribe(audio: UploadFile = File(...), language_code: str = "unknown"):
    """Speech -> text, powered by Sarvam AI (Indic languages + English).
    `language_code` is a BCP-47 code (e.g. "hi-IN", "mr-IN") or "unknown" to auto-detect."""
    if not SARVAM_API_KEY:
        raise HTTPException(503, "Voice input isn't configured yet -- set SARVAM_API_KEY to enable it.")

    audio_bytes = await audio.read()
    print(f"[voice/transcribe] received {len(audio_bytes)} bytes, filename={audio.filename!r}, "
          f"content_type={audio.content_type!r}, language_code={language_code!r}")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": (audio.filename or "audio.wav", audio_bytes, audio.content_type or "audio/wav")},
            data={"language_code": language_code, "model": "saaras:v3"},
        )
    print(f"[voice/transcribe] sarvam status={resp.status_code} body={resp.text[:300]!r}")
    if resp.status_code != 200:
        raise HTTPException(502, f"Sarvam speech-to-text error ({resp.status_code}): {resp.text[:300]}")
    return resp.json()  # {"request_id", "transcript", "language_code"}


class SpeakRequest(BaseModel):
    text: str
    language_code: str = "hi-IN"


@router.post("/voice/speak")
async def speak(req: SpeakRequest):
    """Text -> speech, powered by Sarvam AI. Returns base64-encoded WAV audio."""
    if not SARVAM_API_KEY:
        raise HTTPException(503, "Voice output isn't configured yet -- set SARVAM_API_KEY to enable it.")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SARVAM_TTS_URL,
            headers={"api-subscription-key": SARVAM_API_KEY, "content-type": "application/json"},
            json={"text": req.text, "target_language_code": req.language_code, "model": "bulbul:v3"},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Sarvam text-to-speech error ({resp.status_code}): {resp.text[:300]}")
    return resp.json()  # {"request_id", "audios": ["<base64 wav>"]}


@router.post("/voice/chat")
async def voice_chat(audio: UploadFile = File(...), language_code: str = "unknown"):
    """One-shot voice round trip: speech -> Claude reply -> speech.
    Convenience endpoint for a single mic-button UI."""
    transcribed = await transcribe(audio, language_code)
    transcript = transcribed.get("transcript", "")
    detected_lang = transcribed.get("language_code") or (
        language_code if language_code != "unknown" else "hi-IN"
    )

    if not transcript.strip():
        raise HTTPException(422, "Couldn't make out any speech in that recording -- please try again.")

    chat_resp = await chat(ChatRequest(message=transcript))

    spoken = await speak(SpeakRequest(text=chat_resp.reply, language_code=detected_lang))

    return {
        "transcript": transcript,
        "reply": chat_resp.reply,
        "language_code": detected_lang,
        "audios": spoken.get("audios", []),
    }


@router.get("/assistant/status")
def assistant_status():
    """Lets the frontend know whether to show the chat/voice widget at all."""
    return {
        "chat_enabled": bool(ANTHROPIC_API_KEY),
        "voice_enabled": bool(SARVAM_API_KEY),
    }
