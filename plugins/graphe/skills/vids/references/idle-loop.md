<!-- budget: 900 words -->
# Animating a still into an idle loop

Turn one illustration into a seamless idle loop (breathing, a blink, an effect such as smoke) with Vids' **Animate** tab. The click steps are [playwright.md](playwright.md) steps 31 to 38. Numbers come from one run (2026-11-18, six takes).

## 1. Prepare the still

- **Aspect.** Animate makes only 16:9 or 9:16 and adds black bars to any other ratio. For a square or wider crop, pad the art onto 16:9 in its own flat background colour and crop the centre back out of the take. For a tall crop, cut a 9:16 window from the art (face in the upper third, the effect in frame) rather than padding a square.
- **Keep the background flat; light in post.** Frame 0 of a take is the uploaded still, so lighting asked for in the prompt ramps in and breaks the seam. Generate on the flat background, then relight every frame of the cut loop: replace only the background region connected to the border, and shift edge pixels by `(1 - a) * (new - old)` so hair and translucent smoke keep no fringe. Relit frames flickered less than a take generated from a lit still, and the backdrop can change later without a new take.
- **Inspiration only:** describe a reference's motion and light in words; never upload its images or clips.

## 2. Prompt

State a locked camera, each motion's size and timing, what stays still, and a return to the first frame. Omni adds a slow blink unasked, with the eyes shut about 2 s; ask for a quick one outright. The wording that came closest:

> Static locked-off camera, no camera movement, no cuts. Subtle idle animation of this exact illustration, like a 2D game character idle loop. The blacksmith breathes very softly and shallowly: his chest and shoulders rise and fall only a tiny amount, barely visible, one slow calm breath every three seconds, never heaving. He blinks exactly once, a very quick natural blink: the eyes close and reopen in a fraction of a second, then stay open for the rest of the clip. [...] No new objects, no text, no music. The motion is a seamless loop that returns exactly to the first frame.

On landscape takes it cut breathing from about 2.1 % to 1.6 % of the width. The blink came out 0.6 s in the best take and 1.5 to 2 s in two others, against a natural 100 to 400 ms. Generate 6 s takes, two per prompt.

## 3. What takes do

- Portrait takes pushed in during the first half second, despite "locked-off".
- One take grew longer hair from 1 s on.
- Every take carries Google's visible sparkle mark, fixed bottom right (about x 1739, y 898 on 1920x1080). A centred crop of a landscape take leaves it out; a portrait take keeps it over the art.
- Each take carries audio.

## 4. Score every take

Crop to the delivered window, scale to the still's size and measure against the still. Score the cut loop too: whole-clip breathing includes a long blink's head dip (2.2 % over one clip, 0.8 % inside its loop).

| Measure | How | Target |
|---|---|---|
| Loop point | the pair 2 to 4 s apart whose ±2-frame runs match best (mean absolute difference, MAD) | period in the brief, for example 2.5 to 3.5 s |
| Seam | MAD of the loop's last frame against its first | near the clip's own frame step |
| Breathing | peak-to-peak vertical shift of the torso window (phase correlation), % of width | about 1 % |
| Blink | count frames on a 12 fps strip of the eye window | 100 to 400 ms shut |
| Identity | face-window MAD and SSIM against the still, face window aligned first | near an untouched control |
| Camera | zoom and shift that map sampled frames back onto the still | 1.00 throughout |
| Background | MAD outside the figure mask | near zero |

Self-test the scorer on the still shifted by a known sine first. It caught three pitfalls:

- **Match runs, not frames.** A bob passes each height twice per cycle, so a single-frame match at half a period cuts the motion in reverse. A synthetic 3 s bob picked 2.0 s frame by frame and 3.0 s with runs.
- **Align before identity.** An untouched face that only bobbed 12 px read SSIM 0.30 unaligned and 0.97 aligned. Report head motion apart.
- **Count blinks by eye.** Eye-window MAD and brightness both missed a 0.6 s blink on a lit take, where the lids change the window by only 2 to 5 grey levels.

## 5. Cut the loop and encode

Cut at the best pair and crossfade the last 6 frames into the frames just before the loop start (or the first frames from those just after its end); the wrap then stayed within 1.6x of a normal frame step. If the frames before the start have the eyes shut, the crossfade makes a blink at the wrap: one loop got a 0.33 s blink that way. Strip audio; encode WebM (VP9, `-crf 30 -b:v 0`) and MP4 (H.264, `-crf 20`, `+faststart`, even width and height). A 2.6 to 3.5 s loop at 640x1066 came to 0.35 to 0.65 MB.

## The visible mark

Google's [Generative AI Prohibited Use Policy](https://policies.google.com/terms/generative-ai/use-policy) bars passing generated content off as solely human-made to deceive and says nothing about the visible mark. Since [August 2026](https://techcrunch.com/2026/08/14/google-will-now-allow-users-to-remove-visible-watermark-from-its-ai-generations/), Gemini and Flow can switch it off for Omni; SynthID and C2PA stay. No Vids rule was found. Label the clip AI-generated where it ships; cropping or switching off the mark is the user's call.
