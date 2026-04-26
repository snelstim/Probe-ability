#!/usr/bin/env python3
"""
Quick smoke-test for the Supabase cook-sharing endpoint.

Sends a fake cook with the exact same payload and aiohttp call that
_async_share_cook() uses in HA, so you can confirm the endpoint and
the aiohttp.ClientTimeout fix work without doing a real cook.

Usage:
    python3 test_share.py
"""
import asyncio
import json
import sys
import time

import aiohttp

# --- Copy of the relevant constants from const.py ---
SUPABASE_URL = "https://hlsfrqvfhtauoyhugyou.supabase.co"
SUPABASE_KEY = "sb_publishable_UaNANuzjnNgEP7wGaBARNg_lUbBrMjK"

# --- Fake cook data ---
FAKE_COOK = {
    "cook_name":          "Test Beef Sirloin Medium Rare",
    "target_temp_c":      54.0,
    "reached_target":     True,
    "ambient_median_c":   200.0,
    "duration_s":         3600,
    "reading_count":      120,
    "integration_version": "0.6.2-test",
    # Simulate a steak going from 22°C → 54°C over 60 min at 200°C ambient
    "readings": [
        [i * 30, round(22 + (54 - 22) * (i / 120), 2), 200.0]
        for i in range(121)
    ],
}


async def main() -> None:
    url = f"{SUPABASE_URL}/rest/v1/cooks"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

    print("Sending fake cook to Supabase…")
    print(f"  cook_name:    {FAKE_COOK['cook_name']}")
    print(f"  target_temp:  {FAKE_COOK['target_temp_c']}°C")
    print(f"  readings:     {FAKE_COOK['reading_count']}")
    print(f"  version:      {FAKE_COOK['integration_version']}")
    print()

    timeout = aiohttp.ClientTimeout(total=15)   # same as fixed HA code
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                url, json=FAKE_COOK, headers=headers, timeout=timeout
            ) as resp:
                status = resp.status
                body = await resp.text()
                if status in (200, 201):
                    print(f"✅  Success — HTTP {status}")
                    print("   Check Supabase Table Editor → cooks to see the row.")
                    print("   (cook_name starts with 'Test ' so easy to find and delete)")
                else:
                    print(f"❌  Failed — HTTP {status}")
                    print(f"   Response: {body[:500]}")
                    sys.exit(1)
        except aiohttp.ClientError as exc:
            print(f"❌  Network error: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
