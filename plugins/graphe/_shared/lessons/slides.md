<!-- budget: 651 words -->
# Lessons for decks

Read with `common.md`. Rules already in `SKILL.md` (claim titles, no slogan slides, questions at the end, optional footnotes, a conclusion slide) stay there; these are the lessons `SKILL.md` does not carry on its own.

## Reference to beat

- [Checking the Checker](https://ajbarea.github.io/talks/checking-the-checker/) (talks#92) for colour under room light, plain titles, names on the figures in place of legends, and a clickable backup index. [Five Claude apps](https://ajbarea.github.io/talks/claude-tooling/), pending talks#96's merge, for a look taken from its subject: calm warm paper with orange as a small accent. Until that merge the live page shows the old look.
- Before calling a deck done, open the reference at 1920 wide next to the new deck and name one way the new one is better and one way it is worse.

### own-look-per-talk: Every talk has its own look

- **Rule:** No shared theme: give each talk a strong identity from its own subject, with its own ground, type and title illustration; styling from a culture or a cast belongs only on a talk about it.
- **Why:** One look imposed on every talk made them alike, and undoing it took four PRs.
- **Since:** 2026-11-09
- **Check:** gate: plugins/graphe/skills/slides/scripts/slides.py#own-look, test: test_own_look_reviews_a_placeholder_and_a_title_slide_with_no_picture

### light-by-default: Slides the room reads are light

- **Rule:** Talk slides sit on a light ground; a dark title or closing slide can be part of a talk's identity, and a dark deck needs an explicit request.
- **Why:** Dark slides wash out when the room lights stay on.
- **Since:** 2026-10-30
- **Check:** gate: plugins/graphe/skills/slides/scripts/slides.py#dark-slides, test: test_a_mostly_dark_deck_warns_and_allow_dark_clears_it

### chrome-is-identity: Navigation chrome belongs to the talk

- **Rule:** Style the chapter rail and other chrome in the talk's own CSS, never one rail across talks, and avoid rounded pills; keep the function: keyboard reach, 44px targets on touch, the current chapter marked by more than colour.
- **Why:** Identical rails read as one template, and pills are the default the owner dislikes.
- **Since:** 2026-11-09
- **Check:** guidance: comparing rails needs every talk in view; the starter's rail function has a test.

### one-job-per-colour: One job per colour

- **Rule:** Give each colour one meaning across the talk, and put names on the figure rather than in a legend.
- **Why:** A palette of reused meanings forces the room to re-learn the key on each slide.
- **Since:** 2026-11-08
- **Check:** guidance: a colour's meaning cannot be computed.

### lit-room-colours: Choose colour groups for a lit room

- **Rule:** Score candidate colour sets with `slides.py palette` (room light 30% of projector white, closest pair across vision types) and keep the set with the widest closest pair; carry state with outlines and symbols, since pale fills disappear under room light.
- **Why:** Three shades of one hue scored 7.6, plum, orange and sky 20.7, on the same measure.
- **Since:** 2026-11-08
- **Check:** gate: plugins/graphe/skills/slides/scripts/slides.py#def palette_scores, test: test_palette_reproduces_the_published_scores

### notes-free-pdf: A submitted PDF carries no speaker notes

- **Rule:** Hand out or submit the `pdf` export, which never prints speaker notes.
- **Why:** A deck that sets reveal.js's `showNotes` otherwise prints its script into the file.
- **Since:** 2026-11-09
- **Check:** gate: plugins/graphe/skills/slides/scripts/slides.py#def pdf_html, test: test_pdf_leaves_the_speaker_notes_out_whatever_the_deck_configures

### us-dates: Dates read month first

- **Rule:** Write "Apr 7" or "October 30, 2026" on anything shown in the room; ISO dates stay in file names and data.
- **Why:** The audience reads month-first.
- **Since:** 2026-10-27
- **Check:** guidance: a digit run on a slide may be a label or an identifier.

## Retired

- `shared-forge-look`, retired 2026-11-09 by `own-look-per-talk`: one forge look across talks was reversed; Greek styling stays only on a talk about Greek figures.
