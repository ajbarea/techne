<!-- budget: 900 words -->
# Animating a still into an idle loop

Turn one illustration into a seamless idle loop (breathing, a blink, an effect such as smoke) with Vids' **Animate** tab; clicks are [playwright.md](playwright.md) steps 31 to 38. Numbers come from one six-take run (2026-11-18). The user approves the still and the prompt before the first take.

## 1. Prepare the still

- **Generate Landscape, crop afterwards.** Animate makes only 16:9 or 9:16 and adds black bars to any other ratio. Pad the art onto 16:9 in its own flat background colour, then crop the square or a tall window (such as 3:5) from the take's centre. Portrait takes pushed the camera in despite "locked-off", kept the visible mark over the art and had the worst seams (15.0 and 15.2; landscape 8.1 to 13.8).
- **Keep the background flat; light in post.** Frame 0 is the uploaded still, so prompted lighting ramps in and breaks the seam. Relight every frame of the cut loop instead: replace only the background region connected to the border, and shift edge pixels by `(1 - a) * (new - old)` so hair and translucent smoke keep no fringe. The model never sees the lighting, and the backdrop can change per theme without a new take.
- **Inspiration only:** describe a reference's motion and light in words; never upload its images or clips.

## 2. Prompt

State a locked camera, each motion's size and timing, what stays still, and a return to the first frame. Omni adds a slow blink unasked (eyes shut about 2 s); ask for a quick one. The revised breathing and blink lines (v2):

> [...] The blacksmith breathes very softly and shallowly: his chest and shoulders rise and fall only a tiny amount, barely visible, one slow calm breath every three seconds, never heaving. He blinks exactly once, a very quick natural blink: the eyes close and reopen in a fraction of a second, then stay open for the rest of the clip. [...]

On landscape takes, v2 cut breathing from about 2.1 % to 1.6 % of the width; its two landscape takes blinked for 0.6 s and 1.5 s, against a natural 100 to 400 ms. The recommended loop came from a v1 take: its 2.1 s blink falls outside the loop, and the crossfade adds a 0.33 s one at the wrap (section 5).

**When to stop.** Generate 6 s takes, two per prompt. Keep the first loop meeting every section 4 target; else revise the prompt. After two revisions (six takes), stop and report the numbers. Vids shows no counter; its [help page](https://support.google.com/docs/answer/16143507) allows most users 50 videos a month, reset on the 1st.

## 3. What takes do

- One take grew its hair longer from 1 s.
- Every take carries Google's visible sparkle mark, fixed bottom right (about x 1739, y 898 on 1920x1080). A centred crop of a landscape take leaves it out.
- Each take carries audio.

## 4. Score every take

No scorer ships yet ([#384](https://github.com/ajbarea/techne/issues/384)); write one with `uv run --with numpy --with pillow python`, frames read through `ffmpeg`. Crop to the delivered window, scale to the still's size and measure against it. Score the cut loop too; whole-clip breathing counts a long blink's head dip (2.2 % over one clip, 0.8 % inside its loop). Accepted and rejected values are from the 2026-11-18 run.

| Measure | How | Target |
|---|---|---|
| Loop point | the pair 2 to 4 s apart whose ±2-frame runs match best (mean absolute difference, MAD) | period in the brief, for example 2.5 to 3.5 s |
| Seam | MAD of the loop's last frame against its first, after the crossfade | within 1.6x the mean frame step (accepted 2.19, step 1.41) |
| Breathing | peak-to-peak vertical shift of the torso window (phase correlation), % of width | about 1 % |
| Blink | count frames on a 12 fps strip of the eye window | 100 to 400 ms shut |
| Identity | face-window SSIM against the still, face window aligned first | near an untouched control (0.97); accepted 0.79, rejected 0.48 |
| Camera | zoom and shift that map sampled frames back onto the still | 1.00 throughout |
| Background | MAD outside the figure mask | lowest of the takes (kept 1.19, rejected 1.60) |

Self-test the scorer on the still shifted by a known sine first. It caught three pitfalls:

- **Match runs, not frames.** A bob passes each height twice per cycle, so a single-frame match can cut at half a period, in reverse. A synthetic 3 s bob picked 2.0 s frame by frame, 3.0 s with runs.
- **Align before identity.** An untouched face that only bobbed 12 px read SSIM 0.30 unaligned and 0.97 aligned. Report head motion separately.
- **Count blinks by eye.** Eye-window MAD and brightness missed a 0.6 s blink on a lit take (lids moved it 2 to 5 grey levels).

## 5. Cut the loop and encode

Cut at the best pair and crossfade the last 6 frames into those just before the loop start. If those frames have the eyes shut, the crossfade makes a blink at the wrap, as in the recommended loop. Strip audio; encode WebM (VP9, `-crf 30 -b:v 0`) and MP4 (H.264, `-crf 20`, `+faststart`, even width and height). A 2.6 to 3.5 s loop at 640x1066 came to 0.35 to 0.65 MB.

## The visible mark

Google's [Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy) bars passing generated content off as solely human-made to deceive and says nothing about the visible mark. Since [August 2026](https://techcrunch.com/2026/08/14/google-will-now-allow-users-to-remove-visible-watermark-from-its-ai-generations/), Gemini and Flow can turn it off for Omni; SynthID and C2PA stay. No Vids rule was found. Label the clip AI-generated where it ships; cropping or switching off the mark is the user's call.
