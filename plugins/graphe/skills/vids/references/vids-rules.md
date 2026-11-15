<!-- budget: 900 words -->
# Google Vids writing rules

Every script in `videos/` follows these rules. They come from the [YouTube director skill](youtube-director/SKILL.md) (its Mode A phases, segment fields, quotation rule and anti-slop rule), from AJ's own Vids sessions, and from the working example, [01 Federated Agents](01-federated-agents/script.md). `check_script.py` enforces the ones a script can check.

## Why the rules exist

Vids makes each clip with Gemini Omni from that clip's prompt alone, and an Omni clip is 15 seconds at most since [Gemini Omni 1.2 Flash, Nov 5 2026](https://the-decoder.com/googles-gemini-omni-1-2-flash-stretches-ai-video-clips-to-15-seconds-and-cuts-pricing-by-30-percent/) (10 seconds before, [Opus Clip's Gemini Omni guide](https://www.opus.pro/blog/how-to-use-gemini-omni-beginners-guide); AJ's sessions agree). Whatever a prompt leaves out, Vids makes up, and the made-up parts read as AI slop. Anything inside double quotes is spoken aloud.

## The rules

1. **One segment is one clip, 15 seconds or less.** Aim for 12 to 15. Head each one `### Segment N (m:ss – m:ss): Title`; a Short's segments are `S1`, `S2`, and so on.
2. **The spoken line fits its clip, with a second to spare.** At about 150 words a minute, a 15-second clip holds 35 words once a second is left for pauses and the cut. The lint times every line at that rate and counts a number by its digits ('2025' takes two words' time).
3. **Every segment states five fields, in full:**
   - `Environment & Lighting`: the set, the light, the camera and the framing (16:9 or 9:16).
   - `Avatar (Wardrobe & Physicality)`: the outfit, the posture and each gesture with its time ('At 0:14, points to the chart').
   - `Visual Overlay`: every card, label, chart or animation, or 'None'.
   - `Spoken Script`: the words, in double quotes.
   - `Vocal Direction`: pace, tone, stress, pauses and how to say any hard word.
4. **No pointers to other segments.** Each clip is generated alone, so 'same as Segment 1' tells Vids nothing. Restate the set and the outfit word for word.
5. **Double quotes go only around the spoken words.** One quoted span per segment, because every quoted span is voiced, a repeat included. On-screen text, labels and directions take single quotes; code takes backticks, and code shown on screen uses single-quoted strings.
6. **No directions inside the spoken quotes.** Write a pause as '...' in the line; put '[smiles]', '[0.6 s pause]' and the like in `Vocal Direction`.
7. **Keep the look the same.** Name the outfit and the sets once in the header, then repeat them in every segment, unless the script means the change.
8. **Any voice, any cast.** The narrator is AJ's avatar, so a script may use any voice, or several characters played by the avatar. Name each character's wardrobe, set and voice in the header, and start each segment's avatar field with its character.
9. **Plain language.** Most sentences 20 words or fewer, about an 8th to 10th grade reading level. Name a field term once and explain it in the same line.
10. **Every fact traces to its source.** List the sources at the top of the file, with the segments each one backs. Sources are never voiced.
11. **Where a talk deck exists, the narration comes from the deck's speaker notes** (`graphe:slides`), so the video and the talk say the same thing.
12. **Shorts:** 45 to 50 seconds, the hook in the first 3, the face and a question at the end, and a last line and set that loop back into the first.
13. **Long versions:** 2 to 4 minutes, 16:9, with chapters in the description: the first at 00:00, at least three, each 10 seconds or longer ([YouTube's chapter rules](https://support.google.com/youtube/answer/9884579)).

## A script file holds

1. The header: title, mode, formats and lengths, tone, the look, and the sources.
2. `## Long version` and `## Short`, each a run of segments.
3. The audio prompt: one 30-second loop under both cuts, since Vids generates music 30 seconds at a time (the director skill's workaround).
4. The transitions and SFX schedule: each cut's sound, half before the cut and half after, 0.5 to 1.2 seconds.
5. The YouTube metadata for each cut: title, description with chapters and sources, the AI-avatar disclosure, the pinned comment, tags.
6. The assets: the avatar, each overlay to make, and the audio.

## Pre-flight, before recording

- [ ] `python3 videos/check_script.py` passes on the script.
- [ ] Every overlay is listed under Assets, and none shows a private repository, account, email or key.
- [ ] Each fact matches a source at the top; nothing comes from a paper in review or an unpublished result.
- [ ] The outfit and sets read the same in every segment.
- [ ] Hard words have a pronunciation in `Vocal Direction`.
- [ ] Enough Vids generations are left this month for every segment, plus retakes.
- [ ] The description says an AI avatar of AJ narrates, and 'Altered or synthetic content' is ticked on upload.

## The lint

```
python3 videos/check_script.py                 # every videos/*/script.md
python3 videos/check_script.py path/script.md  # one script
make videos-check                              # the same, from make
```

It prints `path:line: problem` for a heading that looks like a segment but does not parse, and for each segment with a missing field, a double quote outside the spoken line, more than one quoted span, a [direction] inside the quotes, a pointer to another segment, a gesture time outside the segment, a gap or overlap with the segment before, or a clip or spoken line that does not fit in 10 seconds. `make test` runs it on every script too, so CI fails a script that breaks a rule.
