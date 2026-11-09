<!-- budget: 240 words -->
# Choosing colours for a lit room

`# research(2026-11)`

A deck's colours have to survive a projector with the room lights on. Room light adds the same light to every colour, so dark inks lift and pale fills vanish.

`palette` measures a candidate set (run from the skill's folder):

```
uv run --no-project --quiet --with colorspacious==1.1.2 --with numpy python scripts/slides.py palette "#6a1b6e,#e66100,#33bbee" [--ground "#ffffff"] [--room 0.3]
```

It reports, for normal vision and for simulated protan, deutan and tritan vision, the closest pair of colours in CAM02-UCS after adding room light, and each colour's contrast with the ground on screen and in the lit room. It exits 0 whatever it finds: there is no published minimum distance in this space, so compare candidate sets and keep the widest. Use the numbers against each other, never as a pass mark.

Room light defaults to 30% of projector white, the setting talks#92 used. It scored three shades of one red at 7.6 and plum, orange and sky at 20.7, reproduced by this tool. Dark rooms are `--room 0`.

Below 3:1 on screen (WCAG 2.2, Non-text Contrast) a mark gets a `pale` note: give it a darker outline, which meets the criterion, or drop the fill and carry the state with a symbol.

Sources: [WCAG 2.2 Understanding 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html); Machado, Oliveira and Fernandes (2009) for the vision simulation; CAM02-UCS is what talks#92 scored in; the room-light level is that PR's choice, not a published constant.
