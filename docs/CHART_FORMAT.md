# Preparing a chart for ChordPresenter

This guide explains what ChordPresenter expects in a chord chart, so you can paste one in (the **📋 Paste** tab) or tidy a fetched one in the **chart preview** before clicking **Generate**.

The short version:

```
Key: A
Capo: 2

[Verse 1]
G           C          G
Amazing grace how sweet the sound
         Em         D
That saved a soul like me

[Verse 2]
C          G/B        Am7
Through many dangers, toils and snares
```

- **Section names** on their own lines
- **Chords on the line directly above** their lyric, lined up with spaces
- Optional **`Key:`** and **`Capo:`** lines at the top (here: G chord shapes, played with capo 2, sounding in A)

---

## 1. Section names

Each section starts with its name on its own line. That name becomes the **group** in ProPresenter (Verse 1, Chorus, Bridge…).

Two ways to write them:

| Style | Examples |
|---|---|
| In brackets: **any name works** | `[Verse 1]` · `[Chorus]` · `[Pre-Chorus]` · `[Tag]` · `[Spontaneous]` |
| Plain name, **starting at the left edge** | `Verse 1` · `Chorus:` · `Bridge` · `First Verse` |

Plain names only work for these words, optionally followed by a number or a colon:
Intro, Verse, Chorus, Pre-Chorus, Bridge, Tag, Outro, Interlude, Instrumental, Ending, Coda, Hook, Turn, Turnaround, Transition, Vamp, Breakdown, Refrain.

- **Don't indent a plain section name.** `   Chorus` with spaces in front is treated as a lyric. Use `[Chorus]` if you're unsure.
- A section named **`[Tab]`** is skipped (guitar tablature isn't slide material).
- If a pasted chart has **no section names at all**, the whole song becomes one "Verse" group. Add names to split it into groups.

## 2. Chord lines and lyric lines

A **chord line** is a line containing only chords. Put it **directly above** the lyric it belongs to, with no blank line in between. Each chord is placed over the character it sits above, so line them up with spaces. The editor uses a fixed-width font to make this easy.

```
G           C          G
Amazing grace how sweet the sound
```

**On a chord line, these are fine besides chords:**
- bar lines: `| G | D/F# Em |`
- repeat marks: `x2`, `2x`, `(x4)`, `%`
- no-chord: `N.C.`
- walk-downs joined with dashes: `C-Bb-Ab` (read as C, Bb, Ab)

**If any other word is on the line, the whole line is treated as a lyric.** The audience would then see it as words. So avoid things like `Intro: G C D` or `G  C  (repeat)`. Put `Intro` on its own line as a section name, and the chords on the next line.

**Chord names:** most spellings work: `G`, `Em7`, `G/B`, `Cadd9`, `Dsus4`, `Bm7b5`, `E7#9`, `C+`, `Cdim7`, `C°7`, `Cmaj7`, `CM7`, `Cm(maj7)`, `C-7`, `Ab(sus4)`, `C7(b9)`.
- For diminished, write `dim` or `°` (`Cdim7`, `C°7`), not `o` (`Co7`).
- A dash straight after the root means **minor** only when something follows: `C-7` is C minor 7, but `C-` followed by another chord is a walk-down.

When you fetch an Ultimate Guitar link, a warning lists any chords the app doesn't recognize.

## 3. How lyrics become slides

- **Each lyric line becomes one slide.** Keep lines short, about **25–28 characters** fits the theme. Longer lines wrap on screen, so split them with a line break where you'd breathe.
- **A long line with a comma** (at least 4 words before the comma) becomes a **two-line slide**, split at the comma.
- **Syllable dashes** (`A - maz - ing`) are removed to rejoin the word, and chords move with the syllables.
- **Extra spaces inside a lyric** are squeezed to one on the slide, and chords stay on their words.
- **A section with only chord lines** (an Intro, Interlude or Turnaround) becomes slides that are **blank on the audience screen** but show the chords on the stage display.
- **Inside a sung section, a chord line with no lyric under it isn't shown.** Put instrumental bits in their own section (e.g. `[Interlude]`) if the band needs to see them.
- Slides are stored in **capital letters** (the theme's style).
- Every song starts with **two blank "Opening" slides** for backgrounds and walk-in.

## 4. Key and capo

Add these lines anywhere, usually at the top. They're read, then removed from the chart:

| Line | Examples |
|---|---|
| **Key** | `Key: G` · `Key: Bb` · `Key: F#m` |
| **Capo** | `Capo: 2` · `Capo 3` · `Capo: 3rd fret` · `Capo on fret 1` |

- **Charts written for a capo** are converted to the key they actually **sound** in, so electric guitar and keys can read them. The app shows a note like *"Source chart was written for capo 3 (G shapes)"*.
- **With both lines,** write **`Key:` as the key the song sounds in** (Ultimate Guitar's convention). For G chord shapes played with capo 3, that's `Key: Bb` and `Capo: 3`. The app also checks the chords: if they already match the `Key:` line, it treats that line as the shapes key instead.
- **Without a `Key:` line,** the key is worked out from the chords.
- **After loading, you can pick any key and capo** in the app. The chart is transposed for you, and the first slide gets a stage-display note when a capo is set.

## 5. Lines that are removed automatically

When you paste a chart, these don't become slides:
- **Everything before the first section name.** The first real line there fills in the **Title** field and a `by …` line the **Artist**, if you left them empty.
- `Tuning:`, `Capo:`, `Key:`, `Difficulty:`, `Tempo:`, `BPM`, `Time signature:`, `Strumming:`, `Author:`, `Chords by …`, `Tabbed by …`
- page markers like `Page 1/3`
- guitar-tab lines (`e|--7--9--|`), divider lines (`-----`, `*****`) and strum patterns (`| / / / / |`)
- lines starting with `REPEAT` (e.g. `REPEAT CHORUS`)

Scrambled apostrophes from copy-paste (`Iâ€™m`) are repaired automatically.

## 6. Checklist before you click Generate

In the chart preview:
1. **Every section has a name** on its own line (or in brackets).
2. **Every chord line sits right above its lyric,** with no blank line between them.
3. **No chord line has stray words** on it (`Intro:`, `repeat`, notes). Move them to their own line or delete them.
4. **Lyric lines are short**, split where you'd breathe.
5. **Remove leftovers** like copyright notices, "Chord chart provided by…" lines, or website text that slipped in.
6. **Check the key and capo** shown under the chart.

Then **Print** it to check the layout on paper, or **Generate** and look at the stage display in ProPresenter.

## Where text comes from

- **Pasting from a website's print view** usually keeps line breaks, and works best.
- **PDFs** sometimes lose the spacing that lines chords up. Check the chord positions in the preview.
- **Web clippers** (like Obsidian's) may join lines together on some sites. If the preview shows one very long line per page, copy from the page directly instead.
