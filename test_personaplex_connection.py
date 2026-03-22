"""
test_personaplex_connection.py
─────────────────────────────────────────────────────────────────────
Verifies PersonaPlex is reachable and responding with audio.

Usage:
  python test_personaplex_connection.py

Your .env must have:
  PERSONAPLEX_WS_URL=wss://abc123-8998.proxy.runpod.net/api/chat?voice_prompt=NATF0.pt
─────────────────────────────────────────────────────────────────────
"""

import asyncio
import os
import struct
import time

import numpy as np
import websockets
from dotenv import load_dotenv

load_dotenv()

WS_URL = os.getenv("PERSONAPLEX_WS_URL", "")

MOSHI_SAMPLE_RATE   = 24_000
MOSHI_FRAME_SAMPLES = 1_920
MSG_AUDIO_CHUNK     = 1
MSG_TEXT_CHUNK      = 2

YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


def make_silent_frame() -> bytes:
    silence = np.zeros(MOSHI_FRAME_SAMPLES, dtype=np.float32)
    return struct.pack("B", MSG_AUDIO_CHUNK) + silence.tobytes()


def make_sine_frame(freq_hz: float = 440.0, t_offset: float = 0.0) -> bytes:
    t    = np.linspace(t_offset, t_offset + 0.08, MOSHI_FRAME_SAMPLES, endpoint=False)
    tone = (np.sin(2 * np.pi * freq_hz * t) * 0.3).astype(np.float32)
    return struct.pack("B", MSG_AUDIO_CHUNK) + tone.tobytes()


async def test_connection():
    print(f"\n{CYAN}PersonaPlex Connection Test{RESET}")
    print(f"Target: {YELLOW}{WS_URL}{RESET}\n")

    if not WS_URL:
        print(f"{RED}ERROR: PERSONAPLEX_WS_URL is not set in .env{RESET}")
        print("Set it like:")
        print("  PERSONAPLEX_WS_URL=wss://abc123-8998.proxy.runpod.net/api/chat?voice_prompt=NATF0.pt")
        return

    if "/api/chat" not in WS_URL:
        print(f"{YELLOW}WARNING: URL does not contain /api/chat path{RESET}")
        print("Your URL should look like:")
        print("  wss://abc123-8998.proxy.runpod.net/api/chat?voice_prompt=NATF0.pt")

    if "voice_prompt=" not in WS_URL:
        print(f"{YELLOW}WARNING: voice_prompt parameter missing from URL{RESET}")
        print("Add ?voice_prompt=NATF0.pt to your URL")

    # ── Step 1: Connect ───────────────────────────────────────────────────────
    print("Step 1: Connecting to PersonaPlex WebSocket...")
    try:
        ws = await websockets.connect(
            WS_URL,
            additional_headers={"User-Agent": "moshi-client/1.0"},
            open_timeout=15,
        )
        print(f"  {GREEN}✓ Connected{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Connection failed: {e}{RESET}")
        print(f"\n  Check:")
        print(f"  1. PersonaPlex is running on RunPod (port 8998 open)")
        print(f"  2. URL contains /api/chat?voice_prompt=NATF0.pt")
        print(f"  3. voice_prompt value matches a .pt file in voices/ folder")
        return

    # ── Step 2: Send silence ──────────────────────────────────────────────────
    print("Step 2: Sending 1 second of silence (12 frames × 80ms)...")
    try:
        for _ in range(12):
            await ws.send(make_silent_frame())
            await asyncio.sleep(0.05)
        print(f"  {GREEN}✓ Silence sent{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Send failed: {e}{RESET}")
        await ws.close()
        return

    # ── Step 3: Send tone and wait for response ───────────────────────────────
    print("Step 3: Sending 2s tone, waiting for PersonaPlex audio response...")

    frames_received = 0
    text_received   = []
    t_start         = time.time()

    async def send_tone():
        t = 0.0
        for _ in range(25):
            await ws.send(make_sine_frame(440.0, t))
            t += 0.08
            await asyncio.sleep(0.08)

    async def receive_responses():
        nonlocal frames_received
        deadline = time.time() + 5.0
        try:
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    if isinstance(msg, bytes) and len(msg) > 0:
                        if msg[0] == MSG_AUDIO_CHUNK:
                            frames_received += 1
                        elif msg[0] == MSG_TEXT_CHUNK:
                            try:
                                text_received.append(msg[1:].decode("utf-8"))
                            except Exception:
                                pass
                except asyncio.TimeoutError:
                    continue
        except websockets.exceptions.ConnectionClosed:
            pass

    await asyncio.gather(send_tone(), receive_responses())

    # ── Step 4: Summary ───────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print(f"\nStep 4: Summary")
    print(f"  Audio frames received : {GREEN}{frames_received}{RESET}")
    print(f"  Text chunks received  : {GREEN}{len(text_received)}{RESET}")
    print(f"  Test duration         : {elapsed:.1f}s")

    if text_received:
        combined = "".join(text_received).strip()
        if combined:
            print(f"  Inner monologue       : {GREEN}\"{combined[:80]}\"{RESET}")

    print()
    if frames_received > 0:
        print(f"{GREEN}✓ PersonaPlex is working! Run the agent next:{RESET}")
        print(f"  python personaplex_agent.py start")
    else:
        print(f"{YELLOW}⚠  Connected but no audio received yet.{RESET}")
        print(f"  Possible reasons:")
        print(f"    - Model still warming up (wait 60s and retry)")
        print(f"    - Wrong voice_prompt filename (check voices/ folder)")
        print(f"    - GPU out of memory (run nvidia-smi on RunPod)")
    print()

    await ws.close()


if __name__ == "__main__":
    asyncio.run(test_connection())