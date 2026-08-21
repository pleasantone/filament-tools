# Filament profile comparison memory

This repository-specific note records durable comparison practice and a dated local-profile snapshot. Installed presets can change independently of this repository, so verify all profile identities and values live before reporting them as current.

## Comparison workflow

- Use the supported `profile_diff.py` entry point.
- For practical comparisons, use effective mode with `--only-different --show-source`. Add `--csv` with an output path under `/private/tmp` when a wide table may be truncated.
- Include `machine` and `nozzle` in every selector. Resolve ambiguous shorthand with `--find-profile`, then use the exact full name or JSON path.
- The CLI prefers a corresponding `system` profile over its bundled copy and warns on stderr when their parsed JSON differs. Other same-name variants remain ambiguous.
- Analyze the output rather than merely reproducing it: identify meaningful tuning clusters, explicit versus inherited values, practical tradeoffs, and suspicious enable-state combinations.
- Separate substantive settings from representation noise such as two-value versus three-value arrays, explicit empty fields, missing values, and user profiles that duplicate inherited defaults.

Typical command shape:

```bash
./profile_diff.py \
  --select "FIRST;machine=H2C;nozzle=0.4;label=First" \
  --select "SECOND;machine=H2C;nozzle=0.4;label=Second" \
  --only-different \
  --show-source \
  --csv /private/tmp/filament-profile-comparison.csv
```

## H2C 0.4 PETG snapshot

Snapshot date: 2026-08-21.

Profiles compared:

- `Bambu PETG HF` for H2C 0.4
- `Bambu PETG Basic` for H2C 0.4
- `Generic PETG @BBL H2C 0.4 nozzle`
- `SUNLU PETG BASIC GEN2 @Bambu Lab H2C 0.4 nozzle`
- `Tecbears PETG HS Matte PST`

Observed high-signal differences:

- Maximum volumetric speed: Bambu HF `25/35/25`, Basic `18/21/18`, Generic `12/12/12`, Sunlu `18/21`, Tecbears `25/35`.
- Nozzle temperature: HF and Tecbears `245 C`; Basic and Sunlu `250 C`; Generic `255 C`.
- Bambu HF and Tecbears shared the H2C HF dimensional-compensation set. Basic, Generic, and Sunlu shared the common PETG set.
- Sunlu used flow ratio `0.97`, enabled pressure advance `0.038`, fan range `20-50`, 38 mm/s retraction, and 3 mm wipe distance.
- Tecbears PST explicitly used flow ratio `1.0185`; it stored pressure advance `0.02` while pressure advance was disabled. It otherwise tracked many Bambu HF settings.
- Generic PETG was the most conservative throughput profile and used the hottest nozzle and strongest general cooling of the five.

When reusing this snapshot, rerun the comparison and report any drift.
