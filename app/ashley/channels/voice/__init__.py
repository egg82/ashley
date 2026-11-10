"""The voice channel adapter (`decisions.md`, "She runs her own voice pipeline"): satellites reached over the ESPHome
native API, held by one singleton (`satellites`), each wake carried to her reply (`run`) and played from a short-lived
clip (`clips`, served at `GET /api/voice/clips/{token}`). Tunables are data, `voice.json`."""
