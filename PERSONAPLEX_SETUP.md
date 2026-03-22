# PersonaPlex + LiveKit — Step-by-Step Guide

Pure speech-to-speech: Browser/Phone → LiveKit → PersonaPlex on RunPod → LiveKit → Browser/Phone.
No STT. No LLM. No TTS. Just audio in, audio out.

---

## What You're Building

```
[Browser mic]
      ↕  WebRTC  (LiveKit local Docker)
[personaplex_agent.py]  ← this repo
      ↕  WebSocket binary  (Moshi protocol, 24kHz float32, 80ms frames)
[PersonaPlex 7B 4-bit]  ← running on RunPod GPU
```

---

## Prerequisites

- Docker + Docker Compose (for local LiveKit)
- Python 3.10+
- A RunPod account with a GPU pod (RTX 3080 12GB minimum for 4-bit)
- The existing LiveKit Docker stack from your project (`docker-files-livekit/`)

---

## Part 1 — Deploy PersonaPlex on RunPod

### Step 1.1 — Create a RunPod pod

1. Go to https://runpod.io → **Deploy**
2. Choose a GPU:
   - **Minimum:** RTX 3080 12GB (fits 7B 4-bit, ~10GB VRAM used)
   - **Recommended:** RTX 3090 24GB or A4000 16GB (headroom for audio processing)
3. Select template: **RunPod PyTorch 2.2**
4. **Expose port 8998** (HTTP port) — this is the PersonaPlex WebSocket port
5. Deploy and wait for it to start

### Step 1.2 — SSH into the pod and run the startup script

```bash
# Copy the startup script to RunPod (or paste it manually in the pod terminal)
scp runpod/start.sh root@<pod-ip>:~/start.sh

# SSH in
ssh root@<pod-ip>

# Run the setup script
chmod +x ~/start.sh
bash ~/start.sh
```

The script will:
1. Install `moshi`, `bitsandbytes`, `torch`, etc.
2. Download `brianmatzelle/personaplex-7b-v1-bnb-4bit` from HuggingFace (~14GB)
3. Start the Moshi WebSocket server on port 8998

> **Note:** First download takes 5–10 minutes. Model warm-up on first connection takes ~30–60s.

### Step 1.3 — Get your RunPod public URL

In the RunPod dashboard:
- Go to your pod → **Connect** → **HTTP Service**
- Find the public URL for port 8998
- It will look like: `https://abc123def456-8998.proxy.runpod.net`
- Convert to WebSocket: `wss://abc123def456-8998.proxy.runpod.net`

Or if using a direct IP (RunPod bare metal):
- `ws://74.12.55.100:8998`

---

## Part 2 — Set Up Your Local Environment

### Step 2.1 — Install dependencies (minimal, no OpenAI/Deepgram needed)

```bash
cd your-project-root
pip install -r requirements_personaplex.txt
```

### Step 2.2 — Configure .env

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Your existing LiveKit config (unchanged)
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret1234567890secret1234567890

# Your RunPod PersonaPlex URL
PERSONAPLEX_WS_URL=wss://abc123def456-8998.proxy.runpod.net
# or for direct IP: PERSONAPLEX_WS_URL=ws://74.12.55.100:8998
```

---

## Part 3 — Start Local LiveKit

```bash
cd docker-files-livekit
docker-compose up -d
```

Verify:
```bash
docker ps
# Should show: livekit, livekit-redis, livekit-sip, livekit-test-ui, livekit-token-api
```

---

## Part 4 — Test PersonaPlex Connection

Before starting the full agent, verify PersonaPlex is reachable:

```bash
python test_personaplex_connection.py
```

Expected output:
```
PersonaPlex Connection Test
Target: wss://abc123def456-8998.proxy.runpod.net

Step 1: Connecting to PersonaPlex WebSocket...
  ✓ Connected
Step 2: Sending 1 second of silence (12 frames × 80ms)...
  ✓ Silence sent
Step 3: Sending 2 seconds of 440Hz tone, waiting for PersonaPlex to respond...
  ✓ Received 25 audio frames from PersonaPlex

Step 4: Summary
  Audio frames received: 25
  Text chunks received:  3

✓ PersonaPlex is working. You can start the agent.
```

If you get 0 audio frames but connected successfully — the model is still loading. Wait 60 seconds and run again.

---

## Part 5 — Start the Agent

```bash
python personaplex_agent.py start
```

You should see:
```
Prewarming VAD model...
VAD ready
```

---

## Part 6 — Test in Browser

1. Start the token server (from original project):
   ```bash
   python token_server.py
   ```

2. Serve `test.html`:
   ```bash
   python -m http.server 8000
   ```

3. Open http://localhost:8000/test_personaplex.html

4. Click **Generate Token** → **Connect & Test Agent**

5. Start speaking. PersonaPlex will respond in real-time.

---

## Troubleshooting

### "Connection refused" on port 8998
- Make sure port 8998 is exposed in RunPod pod settings
- Check `docker ps` equivalent on RunPod: `pgrep -a python`
- Re-run the startup script

### Agent connects but no audio back
- Model may still be loading (wait 60s)
- Check RunPod terminal for errors: `tail -f /var/log/moshi.log`
- VRAM may be insufficient: run `nvidia-smi` on RunPod, need <12GB used at idle

### Audio quality is choppy
- Network latency to RunPod — try a closer region
- Check: `ping <runpod-ip>` — should be <50ms for good quality

### "Module not found" errors locally
- Run `pip install -r requirements_personaplex.txt`
- Make sure you're in the project root

### Browser mic not working
- Allow microphone permissions in browser
- Use Chrome or Firefox (Safari has WebRTC limitations)

---

## Architecture Notes

| Layer | Details |
|---|---|
| Audio in | 48kHz int16 mono (WebRTC standard) |
| Resample | 48kHz → 24kHz float32 (linear interpolation in `bridge.py`) |
| Frame size | 1920 samples = 80ms at 24kHz (Moshi protocol requirement) |
| WS protocol | Binary frames: `[1 byte type][float32 PCM payload]` |
| Audio out | 24kHz float32 → resampled 48kHz int16 → LiveKit |
| Latency | ~200ms end-to-end (160ms model + 40ms network) |

---

## File Map

```
personaplex_agent.py              ← Entry point (replaces agent_server.py)
src/personaplex/bridge.py         ← Core WebSocket ↔ LiveKit audio bridge
test_personaplex_connection.py    ← Verify RunPod connection before starting
runpod/start.sh                   ← RunPod setup + server launch script
requirements_personaplex.txt      ← Minimal deps (no OpenAI/Deepgram)
.env.example                      ← Config template
```
