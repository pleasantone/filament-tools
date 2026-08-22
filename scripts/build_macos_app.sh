#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
asset_dir="${repo_dir}/build/macos-assets"
iconset_dir="${asset_dir}/FilamentTools.iconset"
base_icon="${asset_dir}/FilamentTools-1024.png"
app_icon="${asset_dir}/FilamentTools.icns"
bundle_path="${repo_dir}/dist/Filament Tools.app"
plist_path="${bundle_path}/Contents/Info.plist"
spec_path="${repo_dir}/Filament Tools.spec"
uv_cache_dir="${UV_CACHE_DIR:-/private/tmp/filament-tools-uv-cache}"

trap 'rm -f "${spec_path}"' EXIT

rm -rf "${iconset_dir}"
mkdir -p "${iconset_dir}"
qlmanage -t -s 1024 -o "${asset_dir}" "${repo_dir}/assets/macos/filament-tools.svg" >/dev/null
mv "${asset_dir}/filament-tools.svg.png" "${base_icon}"

for size in 16 32 128 256 512; do
  sips -z "${size}" "${size}" "${base_icon}" --out "${iconset_dir}/icon_${size}x${size}.png" >/dev/null
  double_size=$((size * 2))
  sips -z "${double_size}" "${double_size}" "${base_icon}" --out "${iconset_dir}/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "${iconset_dir}" -o "${app_icon}"

cd "${repo_dir}"
UV_CACHE_DIR="${uv_cache_dir}" uv run --extra desktop nicegui-pack \
  --name "Filament Tools" \
  --windowed \
  --onedir \
  --clean \
  --noconfirm \
  --icon "${app_icon}" \
  --osx-bundle-identifier "com.pleasantone.filament-tools" \
  "${repo_dir}/src/filament_tools/desktop.py"

/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 0.2.0" "${plist_path}" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.2.0" "${plist_path}"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1" "${plist_path}" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion 1" "${plist_path}"
/usr/libexec/PlistBuddy -c "Add :LSApplicationCategoryType string public.app-category.utilities" "${plist_path}" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :LSApplicationCategoryType public.app-category.utilities" "${plist_path}"

codesign --force --deep --sign - "${bundle_path}"
codesign --verify --deep --strict "${bundle_path}"

echo "Built ${bundle_path}"
