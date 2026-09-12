# Stories (manual scripts — no Anthropic key)

Each `.txt` file here is a ready-to-use Gujarati narration:
- **Line 1** = the YouTube title
- **The rest** = the spoken narration

## How to make a video from one
```bash
python main.py --script-file stories/01_sachi_mehnat.txt --no-upload
```

## How to add your own
Ask Claude in the browser (claude.ai chat) — free — e.g.
"write a 150-word Gujarati moral story about honesty, with a hook and a moral".
Save what it gives you as a new `.txt` file here (title on line 1), then run the
command above. No Anthropic API key is used.
