# Bambu filament profile identity and compatibility

This document records the source-verified rules used by generated profiles and
the implemented inheritance-free flattening operation. The source snapshot is
BambuStudio commit
[`926a7192574bcb9b3a732e1ec59a46d79cb45466`](https://github.com/bambulab/BambuStudio/commit/926a7192574bcb9b3a732e1ec59a46d79cb45466).

## Three different identifiers

`filament_id`, `filament_settings_id`, and `setting_id` are not interchangeable.

### `filament_id`: material-family identity

Bambu Studio's custom-filament dialog derives a user material ID as `P` plus
the first seven hexadecimal characters of an MD5 digest. The digest input is
the custom filament name plus `@<user_id>` while logged in, or only the name
offline. It first reuses an existing ID for the same filament name. If the
eight-character candidate collides with a different material, it hashes the
name plus the current time until it finds an available ID. See
[`CreatePresetsDialog.cpp`, `get_filament_id()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/CreatePresetsDialog.cpp#L415-L506).

Every printer/nozzle root created in one custom-filament operation receives the
same `filament_id`. The ID is written into a root JSON profile only when
`inherits` is empty. A derived profile receives its material ID from its parent
in memory, so a sparse child should not manufacture or copy a different ID. See
[`Preset::save()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L629-L703)
and the
[`user-preset inheritance loader`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L1435-L1459).

### `filament_settings_id`: config-facing preset name

Despite its name, `filament_settings_id` is a configuration array whose first
entry is set to the user preset's name whenever Bambu Studio saves or clones a
filament preset. It is not the cloud database ID. See
[`PresetCollection::save_current_preset()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L2595-L2705).

### `setting_id`: cloud preset identity

For a new user preset, Bambu Studio clears the inherited/copied `setting_id`,
asks its network agent for a new one during synchronization, and records it in
the sibling `.info` file along with `base_id`, `user_id`, sync state, and update
time. The ID is therefore opaque and cloud-assigned; file-generation tools
must not invent one. See
[`GUI_App::sync_preset()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp#L6242-L6378)
and
[`Preset::save_info()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L591-L614).

System profile JSON may contain a `setting_id`, but that does not make it safe
to copy into a generated user preset. A derived user's `.info` `base_id` records
the parent preset's cloud/system setting identity instead.

## Sparse-save behavior

When a user preset has a parent, Bambu Studio calculates a configuration diff
against the parent's effective configuration and writes the dirty options. It
also always carries `filament_extruder_variant`; nullable multi-extruder vectors
may use `nil` entries to inherit unchanged positions. Writing the full changed
array is semantically valid, while omitting `filament_extruder_variant` is not a
faithful reproduction of the current save path. See
[`Preset::save()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L653-L690)
and
[`get_extruder_names_and_keysets()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L906-L924).

## Multiple machines and nozzle diameters

`compatible_printers` is an array of exact printer preset names. Compatibility
and the classic AMS material list compare its entries with the current
printer/nozzle's accepted preset-name set. Official bundled profiles sometimes
put several machines or nozzle diameters in one array; for example,
[`Generic PHA @BBL H2C`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL/filament/Generic%20PHA%20%40BBL%20H2C.json)
supports the H2C 0.6 and 0.8 nozzle presets from one profile.

Bambu Studio's custom-filament wizard uses a more conservative convention: it
loops over every selected printer/nozzle, creates a separate root profile with
one `compatible_printers` entry, and passes the same generated `filament_id` to
all variants. See the
[`custom-filament creation loop`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/CreatePresetsDialog.cpp#L1069-L1135)
and
[`clone_presets_for_filament()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L2555-L2578).

The practical rule is:

- One profile with several compatibility entries is supported when its settings
  are genuinely valid for every listed target.
- Separate profiles are safer when flow, PA, temperature, retraction, or other
  values differ by machine/nozzle.
- Separate roots representing the same physical material must share one
  `filament_id`; each preset receives its own cloud `setting_id`.

The Bambu Lab community discussion on
[sharing filament profiles between nozzles](https://forum.bambulab.com/t/how-to-share-filament-profiles-between-nozzles/75744)
matches this source interpretation: one profile can be made broadly compatible,
but machine/nozzle-specific calibration differences then cannot vary within it.

## Classic AMS eligibility

The classic AMS picker skips non-root presets, requires a nonempty
`filament_id`, matches `compatible_printers`, and deduplicates visible entries by
`filament_id`. See
[`AMSMaterialsSetting::get_filaments_info()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/AMSMaterialsSetting.cpp#L1742-L1804).

Consequences for this repository:

- Sparse generation inherits the base material identity and omits a fake cloud
  ID, but the result is not itself a classic AMS root.
- Flattening removes `inherits`, writes a nonempty root `filament_id`, retains
  exact compatibility entries, and keep user cloud metadata out of the JSON.
- Flattening one material into several machine/nozzle roots reuses the same
  generated or explicitly supplied `filament_id` across all roots.

## User installation directories

Bambu Studio reads `preset_folder` from application config, uses `default` when
it is empty, and loads the selected tree below
`<data_dir>/user/<preset_folder>`. Its filament loader processes the `base`
subdirectory before ordinary derived presets. See
[`PresetBundle::load_presets()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp#L552-L571)
and
[`PresetCollection::load_presets()`](https://github.com/bambulab/BambuStudio/blob/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/Preset.cpp#L1348-L1361).

OrcaSlicer uses the same active-folder contract: its preset bundle reads
`preset_folder`, defaults to `default`, and builds the user root as
`<data_dir>/user/<folder>`. This was verified at OrcaSlicer commit
[`90f76fa28c1c05dce79271dcf0be608119879b62`](https://github.com/SoftFever/OrcaSlicer/commit/90f76fa28c1c05dce79271dcf0be608119879b62)
in
[`PresetBundle.cpp`](https://github.com/SoftFever/OrcaSlicer/blob/90f76fa28c1c05dce79271dcf0be608119879b62/src/libslic3r/PresetBundle.cpp#L579-L586)
and its
[`load_user_presets()` path construction](https://github.com/SoftFever/OrcaSlicer/blob/90f76fa28c1c05dce79271dcf0be608119879b62/src/libslic3r/PresetBundle.cpp#L1002-L1012).

The installer therefore places inheritance-free filament roots under
`filament/base` and derived profiles directly under `filament`. It resolves one
unambiguous application data directory, reads the active folder unless the
operator overrides it, creates only the required filament directories, and
uses exclusive file creation. It never installs or synthesizes `.info` files;
the target slicer owns cloud synchronization metadata.
