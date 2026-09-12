# Stories — the script queue (no API, fully automated)

Videos are made from ready-written Gujarati scripts. No Anthropic/LLM key needed.

## Folders
- `queue/` — scripts waiting to become videos. **Line 1 = title** (not spoken),
  the rest = the narration (first spoken line should be a strong hook).
- `done/`  — scripts already used (moved here automatically, dated).

## Make today's video (uses the NEXT script in queue/)
```powershell
python main.py --daily
```
It renders the alphabetically-first script in `queue/`, then moves it to `done/`.
So tomorrow's run picks the next one automatically.

## Run it automatically every day (Windows Task Scheduler)
1. Open **Task Scheduler** → **Create Basic Task**.
2. Name: `Gujarati daily video` → Trigger: **Daily**, pick a time.
3. Action: **Start a program**.
   - Program/script: `powershell.exe`
   - Add arguments: `-ExecutionPolicy Bypass -File "D:\Claude\run_daily.ps1"`
4. Finish. It now makes one video a day into `output\`. Collect and upload them.

Check `daily.log` for what happened each run.

## Keeping the queue stocked
When `queue/` runs low, ask Claude (in the browser) for more, e.g.
"give me 5 more Gujarati moral-story scripts for the queue". Save each as a new
`.txt` in `queue/` (title on line 1, a hook on line 2).
