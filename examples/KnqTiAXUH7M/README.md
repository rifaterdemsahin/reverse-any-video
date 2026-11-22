# Base video: KnqTiAXUH7M

**How to reverse engineer any editing style (Turned it into a skill)**, Taha El Harti | Making AI Useful
https://www.youtube.com/watch?v=KnqTiAXUH7M

This repo's starting point. `oembed.json` and `thumbnail.jpg` were fetched from YouTube's public oEmbed endpoint.

## Status

| Piece | Status |
|---|---|
| Title, channel, thumbnail | ✅ saved (`oembed.json`) |
| Transcript / script | ❌ not yet. YouTube served a "confirm you're not a bot" page to the cloud machine this repo was built on |
| Shot cuts / pacing | ❌ needs the video file |

## Finish it on your machine

```bash
python reverse_video.py "https://www.youtube.com/watch?v=KnqTiAXUH7M" --download --out examples
```

If YouTube asks you to sign in, export your browser cookies to `cookies.txt` and add `--cookies cookies.txt`.
Or open the video on YouTube → **…more → Show transcript**, copy it into `transcript.txt`, and run:

```bash
python reverse_video.py "https://www.youtube.com/watch?v=KnqTiAXUH7M" --transcript transcript.txt --out examples
```
