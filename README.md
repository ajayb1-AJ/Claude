# Gujarati Faceless YouTube Automation 🎬

Automated pipeline that turns a topic into a finished, uploaded Gujarati video —
**no face, no manual editing**. Built for the niche chosen after audience research:
**Gujarati moral & motivational stories** (બોધકથા / પ્રેરક વાર્તા).

```
topic ──▶ script (Claude) ──▶ voiceover + subtitles (ElevenLabs)
      ──▶ visuals (Pexels) ──▶ assemble (ffmpeg) ──▶ upload (YouTube API)
```

Everything that shapes the channel — niche, language, format, voice, upload
privacy — lives in **`config.yaml`**. Change the niche by editing the prompt
there; no code changes needed.

---

## Why this niche?

| Niche | Automatable | Audience fit | Risk (for hands-off) | CPM |
|-------|:-----------:|:------------:|:--------------------:|-----|
| **Moral/motivational stories** ✅ | High | Strong | **Low** | ₹50–80 |
| Devotional | High | Strong | Low | ₹50–80 |
| Finance/stock explainers | Medium | Strong | **High** (accuracy) | ₹100–200 |
| Comedy/vlogs | Low (needs a person) | Very strong | — | — |

Moral stories are evergreen, safe to run unattended, and the whole thing is a
prompt swap away from devotional or "interesting facts" if you want to pivot.

---

## Quick start

```bash
# 1. Install Python deps + ffmpeg (system)
pip install -r requirements.txt
brew install ffmpeg          # macOS   (Ubuntu: sudo apt-get install ffmpeg)

# 2. Add the Gujarati subtitle font (see assets/fonts/README.md)
#    -> assets/fonts/NotoSansGujarati-Bold.ttf

# 3. Configure secrets
cp .env.example .env         # then fill in the keys

# 4. Verify everything is set up correctly
python check_setup.py

# 5. Build ONE video WITHOUT uploading (always review first!)
python main.py --topic "સાચી મહેનતનું ફળ" --no-upload

# 5. Once happy, let it upload (privacy defaults to "private" in config.yaml)
python main.py --from-queue
```

The finished video and all intermediate files land in `output/<timestamp>-<slug>/`.

---

## API keys you need

| Service | Env var | Where | Notes |
|---------|---------|-------|-------|
| Claude | `ANTHROPIC_API_KEY` | console.anthropic.com | Script generation |
| ElevenLabs | `ELEVENLABS_API_KEY` | you already have this | Set `ELEVENLABS_VOICE_ID` to a voice you tested on Gujarati |

> Find a voice's ID by name: `python main.py --list-voices "Aj Katihyawadi"`
> (lists all your voices with `--list-voices` and no name). Copy the ID into
> `.env` as `ELEVENLABS_VOICE_ID=<id>`.
| Pexels | `PEXELS_API_KEY` | pexels.com/api (free) | Optional — without it you get solid-color slides |
| YouTube | OAuth client JSON | see below | For auto-upload |

### YouTube setup (one-time)

1. Google Cloud Console → new project → **enable "YouTube Data API v3"**.
2. **OAuth consent screen** → External → add yourself as a test user.
3. **Credentials → Create OAuth client ID → Desktop app** → download JSON.
4. Save it as `client_secrets.json` in the project root (path is configurable
   via `YOUTUBE_CLIENT_SECRETS`).
5. First upload opens a browser to authorize; the token is cached to
   `youtube_token.json` so future runs (and cron) are non-interactive.

> ⚠️ **Uploads start as `private`** (see `upload.privacy` in `config.yaml`).
> Watch a few, then switch to `public`. The default upload quota allows a
> handful of uploads per day.

---

## Usage

```bash
python main.py --topic "..."            # one explicit topic (Claude writes the script)
python main.py --from-queue             # next topic from topics/topics.txt
python main.py --from-queue --count 3   # three from the queue
python main.py --auto-topic             # let Claude invent a topic
python main.py --topic "..." --no-upload

# No Anthropic key? Write the story yourself and skip the LLM entirely:
python main.py --script-file my_story.txt --no-upload
python main.py --script-file my_story.txt --title "મારી વાર્તા"
```

### Two ways to get the script
- **Auto (default):** Claude writes it from a topic — needs a funded
  `ANTHROPIC_API_KEY`.
- **Manual (`--script-file`):** you supply the Gujarati narration in a `.txt`
  file (write it yourself, or generate it free in the Claude.ai chat and paste
  it) — **no Anthropic key used.** The first line becomes the title; visuals,
  voice, captions, and upload all work the same.

## Run it daily (cron)

```cron
# 9:00 AM every day: publish the next queued topic
0 9 * * *  cd /path/to/project && /path/to/venv/bin/python main.py --from-queue >> cron.log 2>&1
```

Keep `topics/topics.txt` topped up, or use `--auto-topic` to never run dry.

---

## Project layout

```
config.yaml            # ALL settings (niche, format, voice, upload)
main.py                # CLI
topics/topics.txt      # topic queue
src/
  config.py            # config + secrets loader
  script_generator.py  # Claude -> Gujarati script + title/desc/tags/scenes
  voiceover.py         # ElevenLabs TTS + SRT from word timings
  visuals.py           # Pexels / local / color slides
  assembler.py         # ffmpeg: Ken Burns, mux audio+music, burn subtitles
  uploader.py          # YouTube Data API v3 resumable upload
  pipeline.py          # orchestration
output/                # generated videos (git-ignored)
```

---

## Tuning quality

- **Voice**: the single biggest quality lever. Test a few ElevenLabs voices on a
  Gujarati paragraph and set the best `ELEVENLABS_VOICE_ID`.
- **Format**: `channel.format: short` → 9:16 Shorts; `long` → 16:9.
- **Visuals**: raise `visuals.images_per_video` for more scene variety, or set
  `provider: local` and hand-pick images in `assets/images/`.
- **Music**: drop a royalty-free track in `assets/music/`, set `music.enabled: true`.

---

## Professional / engagement features

Built for high average-view-duration (the goal: 90–95% retention):

- **Fast pace, never static** — a new scene every ~3.5s
  (`visuals.seconds_per_scene`); scene count follows the real narration length.
- **No repeated scenes** — every scene downloads a *distinct* photo/clip
  (candidates are pulled in bulk and de-duplicated across the whole video).
- **Varied motion (not just zoom)** — 10 effects (zoom-in/out, pans in every
  direction, corner zooms) chosen so the same effect never runs back-to-back.
- **Photos + video clips** — each scene is a Pexels/Pixabay photo *or* stock
  video; mix controlled by `visuals.video_ratio`.
- **Your own clips** — drop AI-generated or motion-graphic clips into
  `assets/clips/` and set `visuals.provider: local`.
- **Varied transition SFX** — a library of 7 sounds (whoosh, swoosh, click,
  pop, ding, hit, riser) is auto-synthesized (no files needed) and rotated so
  the same sound never repeats consecutively (`sfx.variety`).
- **Ducked background music** — sidechain compression lowers music under the
  voice automatically (`music.enabled` + a royalty-free track in `assets/music/`).
- **Loudness-normalized voice** — even, broadcast-style level so the narration
  is never too loud or too quiet (`voiceover.loudnorm`). Tune pitch with
  `voiceover.pitch` (e.g. `1.03` slightly higher, `0.97` lower).
- **Retention-tuned script** — 3-second hook, mid-story twist, payoff + CTA.
- **Bold Gujarati captions** — large, outlined, readable on any background.

Pacing/quality knobs live in `config.yaml` under `visuals`, `sfx`, `music`,
and `voiceover`.

## ⚖️ Copyright — important

This tool uses **only** free/licensed media (Pexels, Pixabay — both CC0-style)
and your own original scripts and clips. It deliberately does **not** download
copyrighted content from other creators/videos.

There is **no "safe" duration** for copyrighted material — a 3-second clip can
still get a Content ID claim or a copyright strike, and 3 strikes deletes a
channel. "Fair use / fair dealing" is a legal defense decided case-by-case, not
a length rule. Keep everything original or properly licensed and the channel
stays safe. Music must be royalty-free / licensed too.

## Responsible use

- Keep content original, respectful, and non-defamatory (the script prompt
  already enforces this). Auto-generated content still has to follow YouTube's
  policies — **you** are responsible for what the channel publishes.
- Review the first batch on `private` before going `public`.
- Use royalty-free / properly-licensed music and images only. Pexels content is
  free to use; still credit where the license asks.
