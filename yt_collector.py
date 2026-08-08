#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

# Список каналов — вставь сюда свои ссылки
CHANNELS = [
    "https://www.youtube.com/@worstplayerever/streams",
    "https://www.youtube.com/@worstplayerever/videos",
    "https://www.youtube.com/@ZloyHeron/streams",
    "https://www.youtube.com/@ZloyHeron/videos",
    "https://www.youtube.com/@Arhont_Sibirskii/streams",
    "https://www.youtube.com/@newmayer/streams",
    "https://www.youtube.com/@kuplinovplay/videos",
    "https://www.youtube.com/@Wylsacom/streams",
    "https://www.youtube.com/@ASATAchannel/videos",
    "https://www.youtube.com/@YAKOVLEVmisha/videos"
]

OUTPUT_FILE = Path("/opt/yt-dlp-web/collected_links.json")
VIDEOS_PER_CHANNEL = 1

def get_latest_videos(channel_url, count=3):
    cmd = [
        "/opt/yt-dlp-web/venv/bin/yt-dlp",
        "--flat-playlist",
        "--playlist-end", str(count),
        "--print", "%(id)s|||%(title)s|||%(channel)s",
        channel_url.rstrip("/") + "/videos"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|||")
            if len(parts) == 3:
                vid, title, channel = parts
                videos.append({
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "title": title,
                    "channel": channel,
                    "collected_at": time.strftime("%Y-%m-%d %H:%M:%S")
                })
        return videos
    except Exception as e:
        print(f"Ошибка при обработке {channel_url}: {e}")
        return []

def main():
    all_videos = []
    for ch in CHANNELS:
        all_videos.extend(get_latest_videos(ch, VIDEOS_PER_CHANNEL))
        time.sleep(2)

    existing = []
    if OUTPUT_FILE.exists():
        try:
            existing = json.loads(OUTPUT_FILE.read_text())
        except Exception:
            existing = []

    existing_urls = {v["url"] for v in existing}
    new_videos = [v for v in all_videos if v["url"] not in existing_urls]
    combined = (new_videos + existing)[:100]

    OUTPUT_FILE.write_text(json.dumps(combined, ensure_ascii=False, indent=2))
    print(f"Новых: {len(new_videos)}, всего в списке: {len(combined)}")

if __name__ == "__main__":
    main()
