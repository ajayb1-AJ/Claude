# Run it in your browser (Google Colab) — no install

This is the easiest way: everything runs in the cloud, so there's no
PowerShell, no virtualenv, no `.env` file to hand-edit, and the Gujarati font
downloads automatically.

## How to open the notebook

1. Go to **https://colab.research.google.com**
2. In the popup: click the **GitHub** tab.
3. Paste this repo: `ajayb1-AJ/Claude`
4. In the **Branch** dropdown pick: `claude/gujarati-youtube-automation-q33bzm`
5. Click the notebook **`colab/Gujarati_YouTube.ipynb`** to open it.

(If the GitHub tab asks you to sign in to GitHub, you can also use
**File → Upload notebook** and upload this `.ipynb` after downloading it.)

## How to use it

Run the cells top to bottom with the ▶ button:

1. **Setup** — installs ffmpeg, packages, and the Gujarati font (one line).
2. **Keys** — paste your Anthropic + ElevenLabs keys when prompted (hidden
   input; they're written to a local `.env` in the Colab session only, never
   committed). It then verifies the keys live.
3. **Make a video** — type a topic; it builds the MP4 in your voice.
4. **Watch / Download** — preview inline, or download the file.

## Notes

- A Colab session is temporary — when it closes, the clone and `.env` are gone.
  That's fine: just re-run the Setup + Keys cells next time.
- This is for **interactive** video-making. For **hands-off daily uploads**
  in the cloud, use GitHub Actions instead (ask and we'll add a workflow).
- Auto-upload to YouTube from Colab needs a one-time OAuth token; the notebook
  covers `--no-upload` first so you can review output before wiring uploads.
