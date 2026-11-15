---
description: "Make a Google Vids video with your digital-twin avatar: script, two takes per clip, checks without playback, song, mix and export."
---

# `graphe:vids`

Make a short video in Google Vids with your own AI avatar: write the script, lint it, read it aloud, then generate each clip twice in the Vids editor, keep the better take, add a song from Vids' own music generator, mix it and export the MP4.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`, then `/graphe:setup`.

## When to use

- "Make a video of me skating a mega ramp," or "turn this script into a Short."
- A Google Vids project with your personal avatar (Vids calls it **Me**).
- Checking a finished clip or export for slop before it is posted.

## Usage

```
/graphe:vids
```

It drives the Vids editor in a browser you are signed in to, so sign in to Google first. Lint a script on its own:

```
python3 plugins/graphe/skills/vids/scripts/check_script.py path/to/script.md
```

## What it checks

- Every clip's spoken line word for word, from a local transcript, and each clip's frames on a contact sheet: props that appear from nowhere, a line said twice, framing wider than asked, lettering that drifts.
- The final mix: every line still clear under the song.

## Notes

- Describe the clothes in every prompt; an avatar left undressed in the prompt renders shirtless.
- Generated takes are temporary until inserted into the timeline, and a long session can grow the editor tab to several GB; reload the tab every few clips.
- YouTube export uploads as Private. Tick **Altered or synthetic content** before making it public.

The click-level steps are in [`references/playwright.md`](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/vids/references/playwright.md).

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/vids/SKILL.md) holds the full instructions Claude follows for this skill.
