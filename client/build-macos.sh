#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
BUILD="$ROOT/client/build"
APP="$BUILD/MediaDrop Ripper.app"
TOOLS="$APP/Contents/Resources/Tools"
SOURCES="$APP/Contents/Resources/Sources"
export MACOSX_DEPLOYMENT_TARGET=15.0
mkdir -p "$BUILD" "$TOOLS" "$APP/Contents/MacOS" "$SOURCES"
# Dependencies are installed only on the build machine. The finished app
# includes their dynamic libraries and never needs Homebrew on the user's Mac.
brew install lame libdiscid pkg-config
LAME="$(brew --prefix lame)"
DISCID="$(brew --prefix libdiscid)"
# Build an audio-only FFmpeg instead of shipping a large video toolchain.
if [ ! -f "$BUILD/ffmpeg-8.0.1.tar.xz" ]; then
  curl --fail --location --retry 3 https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz -o "$BUILD/ffmpeg-8.0.1.tar.xz"
fi
if [ ! -d "$BUILD/ffmpeg-8.0.1" ]; then tar -xf "$BUILD/ffmpeg-8.0.1.tar.xz" -C "$BUILD"; fi
(
  cd "$BUILD/ffmpeg-8.0.1"
  ./configure --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-x86asm \
    --enable-ffmpeg --enable-avfilter --enable-swresample --enable-protocol=file,pipe \
    --enable-demuxer=aiff,wav --enable-decoder=pcm_s16be,pcm_s16le,pcm_s24be,pcm_s24le \
    --enable-encoder=libmp3lame --enable-libmp3lame --enable-muxer=mp3 \
    --enable-filter=aresample,aformat,anull --extra-cflags="-I$LAME/include" \
    --extra-ldflags="-L$LAME/lib -Wl,-headerpad_max_install_names"
  make -j "$(sysctl -n hw.logicalcpu)"
)
cp "$BUILD/ffmpeg-8.0.1/ffmpeg" "$TOOLS/ffmpeg"
clang client/discid.c -I"$DISCID/include" -L"$DISCID/lib" -ldiscid \
  -Wl,-headerpad_max_install_names -o "$TOOLS/discid"
swiftc -swift-version 5 -O -parse-as-library client/Sources/*.swift \
  -framework SwiftUI -framework AppKit -o "$APP/Contents/MacOS/MediaDropRipper"
python3 client/bundle_libraries.py "$APP"
swift client/make-icon.swift "$BUILD/AppIcon.iconset"
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
# Bundle exact upstream source archives and the build recipe alongside the LGPL
# binaries, so rebuilding/replacing them does not depend on an online promise.
cp "$BUILD/ffmpeg-8.0.1.tar.xz" "$SOURCES/"
for formula in lame libdiscid $(brew deps --installed lame libdiscid); do
  brew fetch --build-from-source "$formula"
  archive="$(brew --cache --build-from-source "$formula")"
  cp "$archive" "$SOURCES/"
done
cp client/build-macos.sh client/bundle_libraries.py client/discid.c "$SOURCES/"
cp "$BUILD/ffmpeg-8.0.1/COPYING.LGPLv2.1" "$APP/Contents/Resources/FFmpeg-LICENSE.txt"
cp client/THIRD-PARTY.txt "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>MediaDropRipper</string>
<key>CFBundleIdentifier</key><string>com.croftsoft.mediadrop.ripper</string>
<key>CFBundleName</key><string>MediaDrop Ripper</string>
<key>CFBundleDisplayName</key><string>MediaDrop Ripper</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>15.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSRemovableVolumesUsageDescription</key><string>MediaDrop reads your audio CD to copy selected music tracks.</string>
<key>NSLocalNetworkUsageDescription</key><string>MediaDrop uploads your ripped CDs to your media server on your local network.</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>
<key>NSHumanReadableCopyright</key><string>MediaDrop Ripper. Includes FFmpeg, LAME and libdiscid. See bundled licenses and sources.</string>
</dict></plist>
PLIST
# Ad-hoc signatures verify bundle integrity. Developer ID notarisation requires
# the owner's Apple developer credentials and is deliberately not faked.
find "$APP/Contents/Frameworks" -type f -name '*.dylib' -exec codesign --force --sign - {} \;
codesign --force --sign - "$TOOLS/ffmpeg"
codesign --force --sign - "$TOOLS/discid"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
# Test the bundled encoder, with Homebrew binaries excluded from PATH.
/usr/bin/afconvert /System/Library/Sounds/Glass.aiff "$BUILD/test.wav" -f WAVE -d LEI16@44100
PATH=/usr/bin:/bin "$TOOLS/ffmpeg" -v error -y -i "$BUILD/test.wav" -c:a libmp3lame -b:a 320k "$BUILD/test.mp3"
test -s "$BUILD/test.mp3"
swiftc -swift-version 5 client/Sources/Core.swift client/Tests/main.swift -o "$BUILD/core-tests"
"$BUILD/core-tests"
# Launch the packaged app on the build Mac to catch missing runtime resources.
open -a "$APP"
sleep 3
pgrep -f "$APP/Contents/MacOS/MediaDropRipper" >/dev/null
pkill -f "$APP/Contents/MacOS/MediaDropRipper"
# Create a conventional drag-to-Applications disk image.
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp client/INSTALL.txt "$STAGE/Read me.txt"
mkdir -p "$ROOT/dist"
ARCH="$(uname -m)"
hdiutil create -volname "MediaDrop Ripper" -srcfolder "$STAGE" -ov -format UDZO "$ROOT/dist/MediaDrop-Ripper-$ARCH.dmg"
shasum -a 256 "$ROOT/dist/MediaDrop-Ripper-$ARCH.dmg" > "$ROOT/dist/MediaDrop-Ripper-$ARCH.dmg.sha256"
