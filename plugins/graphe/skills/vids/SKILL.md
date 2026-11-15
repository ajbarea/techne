---
name: vids
description: "Create a complete Google Vids video with the user's digital-twin avatar, from script and review through editing, music, export, and disclosure. Use it for cinematic avatar videos, explainers, sketches, and Shorts made in Google Vids. It is not for ordinary coding questions, debugging, or videos that do not use Google Vids."
---

# Google Vids video maker

`<skill-dir>` is the directory holding this SKILL.md.

Script rules: [references/vids-rules.md](references/vids-rules.md).

Make the video in this order. Do not skip the user's approval step.

## 1. Write and approve the script

Choose the format, duration, tone, sets, wardrobe, and avatar behavior first. Use one segment per clip, no longer than 15 seconds. Aim for 12 to 15 seconds.

Each segment must have these fields:

- `Environment & Lighting`: set, light, camera, framing, and aspect ratio.
- `Avatar (Wardrobe & Physicality)`: clothes, posture, props, and timed gestures.
- `Visual Overlay`: every caption, card, label, or animation, or `None`.
- `Spoken Script`: exactly one spoken line in double quotes.
- `Vocal Direction`: pace, tone, stress, pauses, and pronunciations.

Repeat the full set and clothing description in every segment. Do not refer to another segment. Keep sentences short and plain. Put directions in single quotes or normal prose, never inside spoken quotes.

Run the lint:

```bash
python3 <skill-dir>/scripts/check_script.py path/to/script.md
