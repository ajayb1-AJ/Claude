#!/usr/bin/env python3
"""Gujarati faceless YouTube automation — command-line entry point.

Examples
--------
  # One video from a topic you type:
  python main.py --topic "સાચી મહેનતનું ફળ"

  # Pull the next topic from the queue (topics/topics.txt):
  python main.py --from-queue

  # Generate N videos from the queue:
  python main.py --from-queue --count 3

  # Build the video but DON'T upload (great for reviewing output first):
  python main.py --topic "..." --no-upload

  # Let Claude brainstorm a fresh topic in the niche:
  python main.py --auto-topic
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import Config

QUEUE = Path(__file__).parent / "topics" / "topics.txt"


def _read_queue() -> list[str]:
    if not QUEUE.exists():
        return []
    lines = QUEUE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _pop_queue() -> str | None:
    topics = _read_queue()
    if not topics:
        return None
    topic = topics[0]
    remaining = topics[1:]
    header = "# Topic queue — one per line. Lines starting with # are ignored.\n"
    QUEUE.write_text(header + "\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
    return topic


def _auto_topic(cfg: Config) -> str:
    """Ask Claude for one fresh topic idea in the configured niche."""
    from anthropic import Anthropic

    client = Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=cfg.get("script", "model", default="claude-sonnet-5"),
        max_tokens=100,
        system=cfg.get("niche", "system_prompt", default=""),
        messages=[{
            "role": "user",
            "content": (
                "એક નવો, રસપ્રદ વિડિયો વિષય ફક્ત એક લીટીમાં ગુજરાતીમાં આપો. "
                "બીજું કંઈ લખશો નહીં."
            ),
        }],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gujarati faceless YouTube automation")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--topic", help="Explicit topic (Gujarati or English)")
    src.add_argument("--from-queue", action="store_true", help="Take topic(s) from topics/topics.txt")
    src.add_argument("--auto-topic", action="store_true", help="Let Claude pick a topic")
    src.add_argument(
        "--list-voices", nargs="?", const="", metavar="NAME",
        help="List your ElevenLabs voices (optionally filter by name) and exit",
    )
    src.add_argument(
        "--script-file", metavar="PATH",
        help="Use your OWN Gujarati narration from a text file (NO Anthropic key needed)",
    )
    src.add_argument(
        "--daily", action="store_true",
        help="Make today's video from the NEXT script in stories/queue/ (no API). "
             "The used script is moved to stories/done/.",
    )

    parser.add_argument("--count", type=int, default=1, help="How many videos (queue/auto only)")
    parser.add_argument("--no-upload", action="store_true", help="Build only; skip YouTube upload")
    parser.add_argument("--title", default=None, help="Optional YouTube title (manual-script mode)")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config) if args.config else Config.load()

    if args.list_voices is not None:
        from src.voiceover import list_voices

        voices = list_voices(cfg, match=args.list_voices or None)
        if not voices:
            print("No matching voices found.")
            return 1
        print(f"{'VOICE ID':24}  NAME  (category)")
        for v in voices:
            print(f"{v['voice_id']:24}  {v['name']}  ({v['category']})")
        print("\nCopy the VOICE ID into .env as ELEVENLABS_VOICE_ID=<id>")
        return 0

    do_upload = None if not args.no_upload else False

    from src.pipeline import run_pipeline

    # Daily mode: pull the next queued script, render, archive it. No API.
    if args.daily:
        from src.script_generator import manual_script
        queue_dir = Path(__file__).parent / "stories" / "queue"
        done_dir = Path(__file__).parent / "stories" / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        scripts = sorted(queue_dir.glob("*.txt")) if queue_dir.exists() else []
        if not scripts:
            print("Queue is empty (stories/queue/). Add scripts, or ask Claude for more.",
                  file=sys.stderr)
            return 2
        nxt = scripts[0]
        print(f"Daily: using next queued script -> {nxt.name} "
              f"({len(scripts)} in queue)")
        script = manual_script(nxt.read_text(encoding="utf-8"), cfg)
        try:
            run_pipeline(script.title, cfg, do_upload=do_upload, script=script)
        except Exception as exc:
            print(f"!! Failed on '{nxt.name}': {exc}", file=sys.stderr)
            return 1
        # Archive the used script so tomorrow takes the next one.
        import shutil, time as _t
        shutil.move(str(nxt), str(done_dir / f"{_t.strftime('%Y%m%d')}_{nxt.name}"))
        print(f"\nDone. Archived {nxt.name}; {len(scripts)-1} left in queue.")
        return 0

    # Manual-script mode: no Anthropic API used at all.
    if args.script_file:
        from src.script_generator import manual_script
        text = Path(args.script_file).read_text(encoding="utf-8")
        script = manual_script(text, cfg, title=args.title)
        try:
            run_pipeline(script.title, cfg, do_upload=do_upload, script=script)
            print("\nDone. 1/1 succeeded.")
            return 0
        except Exception as exc:
            print(f"!! Failed: {exc}", file=sys.stderr)
            return 1

    topics: list[str] = []
    if args.topic:
        topics = [args.topic]
    elif args.from_queue:
        for _ in range(args.count):
            t = _pop_queue()
            if t is None:
                break
            topics.append(t)
        if not topics:
            print("Topic queue is empty (topics/topics.txt).", file=sys.stderr)
            return 1
    elif args.auto_topic:
        topics = [_auto_topic(cfg) for _ in range(args.count)]

    failures = 0
    for topic in topics:
        try:
            run_pipeline(topic, cfg, do_upload=do_upload)
        except Exception as exc:
            failures += 1
            print(f"!! Failed on '{topic}': {exc}", file=sys.stderr)

    print(f"\nDone. {len(topics) - failures}/{len(topics)} succeeded.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
