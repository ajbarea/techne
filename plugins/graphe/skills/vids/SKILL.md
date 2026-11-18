---
name: vids
description: "Make a short video in Google Vids with the user's own AI avatar (Vids' Me avatar): write and lint the script, generate each clip twice and keep the better take, check every take without playback, add a song from Vids' music generator, mix, export, and upload to YouTube with the AI disclosure. Use when the user asks for a Google Vids video, a Short or skit starring their avatar or digital twin, a still image animated into a seamless idle loop, or a check of a Vids clip or export for slop. Not for a talk deck or its recording (graphe:slides), and not for editing footage outside Google Vids."
---

<!-- budget: 900 words -->
# Google Vids video maker

`<skill-dir>` is the directory holding this SKILL.md.

Make the video in this order, and stop at the user's approval before anything is generated. Click-level steps: [references/playwright.md](references/playwright.md); script rules: [references/vids-rules.md](references/vids-rules.md). To animate a still image into a seamless idle loop instead, follow [references/idle-loop.md](references/idle-loop.md).

**Needs:** a browser signed in to the user's Google account with Vids access (Playwright MCP), `ffmpeg`, and `uv`. Run Python with `uv run --with faster-whisper --with pillow python`; transcribe by loading the audio as a 16 kHz numpy array and using model `base.en`.

## 1. Write the script and get it approved

Pick the format, length, tone, sets and outfit. Write one segment per clip, 15 seconds or less. Each segment has five fields: `Environment & Lighting`, `Avatar (Wardrobe & Physicality)`, `Visual Overlay`, `Spoken Script` (one line in double quotes) and `Vocal Direction`. Restate the set and the outfit in every segment; each clip is generated alone.

Lint it and fix every problem:

```bash
python3 <skill-dir>/scripts/check_script.py path/to/script.md
```

Hand the script to the user. They read it aloud and approve it before any generation. Check that enough Vids generations remain for every segment, twice over.

## 2. Make each segment

Before any upload or post, open the account menu and read the account or channel name to the user; a browser often holds several Google accounts, and a URL parameter does not prove which one a page opened.

Open Vids, start a Blank video and set the canvas with the Video size control (Portrait 9:16 for a Short; playwright.md step 2). Then, for every segment:

1. **AI Video** > **Create**, add the **Me** avatar, then type the prompt (never `fill()`, which deletes the avatar chip).
2. Add a continuity still from the previous clip as an ingredient, when there is one.
3. Set orientation, resolution and duration in Generation settings, not in the prompt.
4. Generate two takes.
5. Download both and check each without playback: an ffmpeg contact sheet at 2 fps, and a local faster-whisper transcript compared word for word with the script.
6. Keep the better take and insert it as the next scene (**Insert** for the first, **Insert in new scene** after).

Takes vanish on reload until inserted, and the tab grows to several GB: insert what you keep, then reload every few clips.

## 3. Music, mix and export

Generate the song in Vids' **Music** panel before any outside tool. It lands on its own audio row; start it at 0:00 and trim its end to the video's.

Set the song to a fixed volume with ducking Off; Narrative clips lower it for their whole length, burying it. The slider is not linear: export, measure each part's `mean_volume` with ffmpeg, and adjust until the dialogue sits a few dB above the song.

Wait for **Saved to Drive**, then File > Download > MP4. An export started before the save can be the previous version.

Sung lyrics need local rendering, since Vids captions only speech. First mute every clip for one song-only export and take word times from it, then unmute (playwright.md step 27). Draw the lyrics over the final export with Pillow frames piped to ffmpeg, above the Shorts overlay (step 30).

Transcribe the final file: every spoken line must come through word for word. Hand the MP4 to the user.

## 4. YouTube

Upload in YouTube Studio as Unlisted, after reading the channel name to the user. Fill in title, description (say an AI avatar of the user narrates, and that the song is AI-generated), thumbnail, not made for kids, and **AI use: Yes**. Post and pin the comment from the same channel. The user checks it on their phone, then makes it Public.

## Rules that prevent slop

- Describe the clothes in every prompt, or the avatar renders shirtless.
- Anything in double quotes is spoken; on-screen text goes in single quotes.
- A prop must be shown arriving before it is used.
- State the framing (close-up, first-person POV, wide).
- Ask for each line to be said once; a repeated line is a retake.
- Check every take's frames as well as its words: hands, lettering and props drift.

## Driving the editor

[references/playwright.md](references/playwright.md) holds the verified click-level steps. The locators used most:

- `getByRole('button', { name: 'Generate an AI video clip' })`, then the panel's **Create** tab.
- The **Avatar** button, then **Me** and **Select** in the dialog. With an image ingredient attached, Avatar moves into **Add avatar or ingredients**.
- The panel's last textbox, whose name changes once ingredients are attached.
- `getByRole('button', { name: /Generation settings/ })`; the duration slider reports its value in `aria-valuetext`.
- `getByRole('button', { name: 'Zoom to fit timeline' })` before dragging or right-clicking scenes.
