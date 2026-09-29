# ChordPresenter

ChordPresenter was created to streamline the process of creating ProPresenter files that have embedded chord charts in them. While there are many online resources for finding chord charts for popular songs, there is no easy way to get those into your Stage Monitor on ProPresenter.

I have spent years in tech and was not able to find a solution, so I decided to make one. This is a simple app built on [Tauri](https://tauri.app) for macOS. I may later add Windows support if there is interest.

There are two ways of creating the `.pro` files. The first is through the [Obsidian Clipper](https://obsidian.md/clipper) browser extension, which creates Markdown files of pages with chords and lyrics. Simply navigate to the page your song is on, clip the file to a folder, then drag and drop it into ChordPresenter. It will give a preview of what will be imported into ProPresenter. The second method is to copy and paste the link to the song into the URL Fetch tab. It will parse the information, give a preview, and output it to your desired directory.

You can also **paste** a chart directly (the 📋 Paste tab) — from a site's print view, a PDF, an email, anywhere you can copy chords-above-lyrics text. See **[Preparing a chart](docs/CHART_FORMAT.md)** for what the app expects (section names, chord lines, `Key:`/`Capo:` lines) and how to tidy a chart before generating.

ChordPresenter can also transpose keys — it auto-detects the source key and lets you target any key you need. Charts written for a capo come in at their real (concert) key, and you can add a capo on output: the stage monitor then shows capo shapes, and the first slide gets a stage-only note saying which capo to use. There's a Print button for rehearsal charts, and an Edit .pro tab for adding or fixing chords in files you've already made.

There is only one built-in theme, but once inside ProPresenter you can change it to your preferred look.

This is a work in progress, so there may be some reflowing that needs to be done for the slides. This is just a fun side project for me — I first love the Church and also have an affinity for tech. It is free to use and always will be. Please feel free to let me know if you have issues; there is a logging system built in as well.

*#forthekingdom*

---

## Supported Sites

| Site | Output |
|---|---|
| EssentialWorship.com | Chords + Lyrics |
| WorshipTogether.com | Chords + Lyrics |
| WorshipChords.com | Chords + Lyrics |
| WorshipChords.net | Chords + Lyrics |
| Ultimate Guitar | Chords + Lyrics |
| Genius.com | Lyrics Only |
| AllChristianSongsLyrics.com | Lyrics Only |
| AZLyrics, LyricsFreak, SongLyrics | Lyrics Only |

---

## Notes

This is a work in progress — some reflowing of slides may be needed depending on lyric line length. There is a logging system built in, so if you run into issues please feel free to report them.

This is a free side project and always will be. First love the Church, second love tech.

*#forthekingdom*

---

## Install

Download the latest `ChordPresenter_<version>_universal.dmg` from [Releases](https://github.com/Anagaion/ChordPresenter/releases/latest), open it, and drag ChordPresenter into Applications. It runs natively on Apple Silicon and Intel Macs, and **nothing else needs to be installed** — Python is built in.

The app isn't notarized by Apple yet, so the first time you open it:
- **macOS 15 Sequoia or newer:** open it once, click **Done**, then go to **System Settings → Privacy & Security** and click **Open Anyway**.
- **Older macOS:** right-click the app, choose **Open**, then click **Open**.

---

## Build From Source

Requires: Rust (via rustup), Node + pnpm, Xcode Command Line Tools, Python 3 (for development and tests). macOS only.

```bash
cd ChordPresenter
pnpm tauri dev                         # dev mode with hot reload (uses your system python3)
scripts/build/release_mac.sh           # tests → bundled Python → universal build → sign → .dmg
```

`release_mac.sh` runs `scripts/build/bundle_python.sh`, which downloads a checksum-verified standalone Python from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) and trims it into `src-tauri/python-runtime/` (git-ignored). If Homebrew's Rust is installed, the script puts rustup's toolchain first on `PATH`, since only that one has the Apple Silicon target.

---

## Python Scripts

The `.pro` generation pipeline:

| File | Role |
|---|---|
| `ew_fetch.py` | Fetches URLs, dispatches the site-specific parser, calls md_to_pro |
| `md_to_pro.py` | Parses chord charts → sections, slides and chord positions; key/capo/transpose; writes the `.pro` |
| `create_pro_song.py` | Low-level protobuf builder (RTF text, chord attributes, slide notes) |
| `parse_pro.py` | Reads an existing `.pro` back into slides + chords (Edit .pro tab) |
| `chord_grammar.json` | Chord-name grammar shared by the Python scripts and the app (`src/music.ts`) |

---

## Tests

```bash
python3 -m unittest discover tests
```

- `tests/test_chart_rules.py` and `tests/test_chord_parity.py` use made-up lines only and run anywhere. The parity test checks that the Python scripts and the app read chords identically.
- `tests/test_url_fixtures.py` runs saved song pages through the full URL pipeline and compares against recorded snapshots. Pages are stored locally in `tests/fixtures/local/` (git-ignored, since they contain copyrighted lyrics); add one with `python3 tests/tools/add_fixture.py <song URL>`.

---

## Pending / Future

- **Rust rewrite (v2)**: move the Python pipeline into the app itself — smaller, faster, one implementation
- **Windows support**: much simpler once the pipeline is in Rust
- **Notarized releases**: no more "Open Anyway" step
- **Additional site parsers**: Genius and AllChristianSongsLyrics need further testing
