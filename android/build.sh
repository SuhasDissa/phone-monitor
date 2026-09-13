#!/usr/bin/env bash
# Builds both phone clients without Gradle:
#   out/phone-monitor.dex  root client, run via app_process
#   out/phone-monitor.apk  non-root client (no launcher icon), installed via adb
set -euo pipefail
cd "$(dirname "$0")"

SDK=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}
BUILD_TOOLS=$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)
PLATFORM=$(ls -d "$SDK"/platforms/android-* | sort -V | tail -1)
ANDROID_JAR=$PLATFORM/android.jar
MIN_API=30
KEYSTORE=keystore.jks
KEYSTORE_PASS=phone-monitor

echo "build-tools: $BUILD_TOOLS"
echo "platform:    $PLATFORM"

rm -rf out
mkdir -p out/root out/apk

# --- root client: classes -> dex ---
javac -source 8 -target 8 -Xlint:-options -nowarn -bootclasspath "$ANDROID_JAR" \
    -d out/root $(find common root -name '*.java')
"$BUILD_TOOLS/d8" --min-api $MIN_API --output out/root $(find out/root -name '*.class')
mv out/root/classes.dex out/phone-monitor.dex

# --- apk: manifest -> base apk, classes -> dex, zip, align, sign ---
"$BUILD_TOOLS/aapt2" link -o out/apk/base.apk -I "$ANDROID_JAR" \
    --manifest apk/AndroidManifest.xml --min-sdk-version $MIN_API --target-sdk-version 34
javac -source 8 -target 8 -Xlint:-options -nowarn -bootclasspath "$ANDROID_JAR" \
    -d out/apk $(find common apk/src -name '*.java')
"$BUILD_TOOLS/d8" --min-api $MIN_API --output out/apk $(find out/apk -name '*.class')
python3 -c "import zipfile; zipfile.ZipFile('out/apk/base.apk', 'a').write('out/apk/classes.dex', 'classes.dex')"
"$BUILD_TOOLS/zipalign" -f 4 out/apk/base.apk out/apk/aligned.apk
"$BUILD_TOOLS/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:$KEYSTORE_PASS \
    --out out/phone-monitor.apk out/apk/aligned.apk

rm -rf out/root out/apk
ls -la out
