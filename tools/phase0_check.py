"""Phase 0 headless check — no Qt, no window.

Connects to Home Assistant, authenticates, subscribes to the compressed
entity feed, prints the first diffs, and optionally toggles one entity.

    .venv\\Scripts\\python.exe tools\\phase0_check.py --url http://homeassistant.local:8123
    .venv\\Scripts\\python.exe tools\\phase0_check.py --toggle light.bedroom
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets  # noqa: E402

from ha_dock import db  # noqa: E402
from ha_dock.ha_client import ws_url  # noqa: E402


async def run(url: str, token: str, toggle: str | None, seconds: int) -> int:
    endpoint = ws_url(url)
    print(f"-> {endpoint}")
    async with websockets.connect(endpoint, open_timeout=10,
                                  max_size=8 * 1024 * 1024) as ws:
        hello = json.loads(await ws.recv())
        print(f"   greeting: {hello.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        reply = json.loads(await ws.recv())
        if reply.get("type") != "auth_ok":
            print(f"!! auth failed: {reply}")
            return 2
        print(f"   auth ok, HA {reply.get('ha_version')}")

        await ws.send(json.dumps({"id": 1, "type": "subscribe_entities"}))
        if toggle:
            await ws.send(json.dumps({
                "id": 2, "type": "call_service",
                "domain": toggle.split(".", 1)[0], "service": "toggle",
                "target": {"entity_id": toggle},
            }))
            print(f"   toggling {toggle}")

        seen = 0
        try:
            async with asyncio.timeout(seconds):
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "result":
                        print(f"   result id={msg.get('id')} "
                              f"success={msg.get('success')}")
                        continue
                    if msg.get("type") != "event":
                        continue
                    ev = msg.get("event") or {}
                    if "a" in ev:
                        print(f"   snapshot: {len(ev['a'])} entities")
                        for eid in sorted(ev["a"])[:5]:
                            print(f"     {eid} = {ev['a'][eid].get('s')}")
                    for eid, delta in (ev.get("c") or {}).items():
                        seen += 1
                        print(f"   change  {eid}: {delta.get('+', {})}")
        except TimeoutError:
            pass
        print(f"<- {seen} change events in {seconds}s")
    return 0


def main() -> int:
    store = db.Store()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=store.get("ha_url"))
    ap.add_argument("--token", default=db.load_token())
    ap.add_argument("--toggle", default=None)
    ap.add_argument("--seconds", type=int, default=15)
    args = ap.parse_args()
    if not args.token:
        print("!! no token. Pass --token or save one in the GUI first.")
        return 1
    return asyncio.run(run(args.url, args.token, args.toggle, args.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
