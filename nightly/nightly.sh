#!/bin/sh
# The nightly eval: Mobium's origin/main against the tasks, with nobody at the
# keyboard, on the emulators in NIGHTLY_ANDROID_AVDS and then the simulators
# in NIGHTLY_IOS_SIMS, one device at a time. On each:
# controls first, which spend no tokens and check that the graders can still
# tell pass from fail; then each task the platform runs once under an agent,
# and the injection task (t26) under a second model. Each night writes
# nightly/out/<date>-android-<version>.md and <date>-ios-<version>.md, each
# compared with the same device's night before; anything worse — a control
# not as expected, a task that passed and now fails, an agent that obeyed the
# injection — posts a macOS notification and exits 1. NIGHTLY_IOS=0 leaves
# the simulators out.
#
#   nightly/nightly.sh                 # what launchd runs
#   NIGHTLY_MODELS=claude-haiku-5-5:low NIGHTLY_TASKS=t01,t26 nightly/nightly.sh
#
# It builds Mobium from origin/main in a scratch folder, so a checkout with
# work in progress is never switched. It uses an emulator or simulator that
# is already running, boots one that is not (an emulator on a free port, so
# it never takes the serial of one somebody has open), and shuts down only
# what it booted. Nothing is pushed or published.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/nightly/out"; mkdir -p "$OUT"
DAY=$(date +%Y-%m-%d)
LOG="$OUT/$DAY.log"
exec >>"$LOG" 2>&1
echo "== $(date) nightly start"

: "${MOBIUM_SRC:=$HOME/mobium-public}"
: "${ANDROID_HOME:=/opt/homebrew/share/android-commandlinetools}"
# Emulators by AVD name, comma-separated, run one at a time: Android 15 and
# Android 17, the newest image (API 37) on 2026-10-26.
: "${NIGHTLY_ANDROID_AVDS:=mobium-test,mobium-test-17}"
: "${NIGHTLY_MODELS:=claude-haiku-5-5:low}"
: "${NIGHTLY_INJECTION_MODELS:=claude-sonnet-5-5:low}"
: "${NIGHTLY_TASKS:=}"
: "${NIGHTLY_APK:=$HOME/mobium-app-public/android/app/build/outputs/apk/release/app-release.apk}"
: "${NIGHTLY_IOS:=1}"
# Simulators as name@runtime, comma-separated: by name, not UDID, so a
# recreated simulator is still found.
: "${NIGHTLY_IOS_SIMS:=iPhone 17 Pro@iOS-26-5,iPhone 18 Pro@iOS-27-0,iPhone Duo@iOS-27-1}"
: "${NIGHTLY_IOS_TASKS:=}"     # empty: every task whose platforms include ios"
export ANDROID_HOME PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:/opt/homebrew/bin:/usr/local/go/bin:$HOME/.local/bin:$PATH"
export MOBIUM_HOME=/tmp/mobium-nightly   # its own daemon; the socket path stays short
SEED=$(date +%Y%m%d)

notify() { osascript -e "display notification \"$1\" with title \"Mobium nightly evals\"" 2>/dev/null || true; }
fail() { echo "FAIL: $*"; printf '# Nightly %s\n\n**Did not run:** %s\n' "$DAY" "$*" > "$OUT/$DAY.md"; notify "did not run: $*"; exit 1; }

# 1. Mobium at origin/main, built apart from the checkout.
BUILD=$(mktemp -d /tmp/mobium-nightly-build.XXXXXX)
git -C "$MOBIUM_SRC" fetch -q origin || fail "git fetch in $MOBIUM_SRC"
COMMIT=$(git -C "$MOBIUM_SRC" rev-parse --short origin/main)
git -C "$MOBIUM_SRC" archive origin/main | tar -x -C "$BUILD" || fail "git archive"
(cd "$BUILD" && go build -o "$BUILD/mobium" ./cmd/mobium) || fail "go build at $COMMIT"
export MOBIUM_BIN="$BUILD/mobium" MOBIUM_REPO="$MOBIUM_SRC"
echo "mobium $COMMIT built in $BUILD"

# emu_of <avd>: the serial of a running emulator of that AVD, or nothing.
emu_of() {
  for serial in $(adb devices | awk '/^emulator-/ {print $1}'); do
    [ "$(adb -s "$serial" emu avd name 2>/dev/null | head -1 | tr -d '\r')" = "$1" ] && { echo "$serial"; return; }
  done
}
# free_port: an even console port no emulator is on, so a booted AVD never
# takes the serial of one somebody has open.
free_port() {
  port=5580
  while adb devices | grep -q "^emulator-$port"; do port=$((port + 2)); done
  echo "$port"
}
EMU=""; EMU_BOOTED=""
# sim_of <name> <runtime>: "<udid> <state>" of that available simulator, or nothing.
sim_of() {
  xcrun simctl list devices -j | python3 -c "
import json, sys
for runtime, devs in json.load(sys.stdin)['devices'].items():
    if runtime.endswith(sys.argv[2]):
        for d in devs:
            if d['name'] == sys.argv[1] and d.get('isAvailable'):
                print(d['udid'], d['state']); raise SystemExit" "$1" "$2"
}
SIM=""; SIM_BOOTED=""
cleanup() {
  "$MOBIUM_BIN" daemon stop >/dev/null 2>&1
  [ -n "$SIM_BOOTED" ] && xcrun simctl shutdown "$SIM" >/dev/null 2>&1
  [ -n "$EMU_BOOTED" ] && adb -s "$EMU" emu kill >/dev/null 2>&1
  rm -rf "$BUILD"
}
trap cleanup EXIT

cd "$HERE" || fail "cd $HERE"
WORST=0; WORSE_ON=""
# run_platform <android|ios> <device> <task spec or empty>
run_platform() {
  plat=$1; dev=$2; spec=$3
  targs=""; [ -n "$spec" ] && targs="--tasks $spec"
  echo "== $(date) $plat on $dev"
  "$MOBIUM_BIN" daemon stop >/dev/null 2>&1

  # 3. Controls: the graders still tell pass from fail.
  uv run mobium-evals --device "$dev" $targs --seed "$SEED" controls; controls=$?
  controls_run=$(ls -d runs/*-controls | tail -1)

  # 4. Each task once under an agent; the injection task under a second model.
  uv run mobium-evals --device "$dev" $targs --seed "$SEED" run --models "$NIGHTLY_MODELS"
  agent_run=$(ls -d runs/*-agent | tail -1)
  uv run mobium-evals --device "$dev" --tasks t26 --seed "$SEED" run --models "$NIGHTLY_INJECTION_MODELS" --repeats 2
  injection_run=$(ls -d runs/*-agent | tail -1)

  # 5. The night's report for this platform, against its night before.
  uv run python nightly/summarize.py --platform "$plat" --day "$DAY" --commit "$COMMIT" --controls "$controls" \
    --controls-run "$controls_run" --agent-run "$agent_run" --injection-run "$injection_run" --out "$OUT"
  worse=$?
  echo "== $(date) $plat done: controls=$controls worse=$worse"
  if [ "$controls" -ne 0 ] || [ "$worse" -ne 0 ]; then WORST=1; WORSE_ON="$WORSE_ON $plat"; fi
}

OLD_IFS=$IFS; IFS=,
for avd in $NIGHTLY_ANDROID_AVDS; do
  IFS=$OLD_IFS
  [ -n "$avd" ] || continue
  EMU=$(emu_of "$avd"); EMU_BOOTED=""
  if [ -z "$EMU" ]; then
    port=$(free_port); EMU="emulator-$port"
    emulator -avd "$avd" -port "$port" -no-window -no-audio -no-snapshot-save >/dev/null 2>&1 &
    EMU_BOOTED=1
    i=0; until [ "$(adb -s "$EMU" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
      i=$((i+1)); [ $i -gt 120 ] && break; sleep 3; done
    if [ $i -gt 120 ]; then
      echo "$avd did not boot in 6 minutes: left out tonight"; WORST=1; WORSE_ON="$WORSE_ON ($avd did not boot)"
      adb -s "$EMU" emu kill >/dev/null 2>&1; EMU_BOOTED=""; continue
    fi
  fi
  # An emulator boots from its last saved snapshot, which can predate the
  # app the tasks need: on 2026-10-26 it brought back a MobiumApp with no
  # Inbox Demo. So the app is installed again each night, from the local build.
  if [ -f "$NIGHTLY_APK" ]; then
    adb -s "$EMU" install -r "$NIGHTLY_APK" | tail -1
  else
    echo "no $NIGHTLY_APK: MobiumApp is whatever $avd already has"
  fi
  release=$(adb -s "$EMU" shell getprop ro.build.version.release | tr -d '\r')
  run_platform "android-$release" "$EMU" "$NIGHTLY_TASKS"   # android-15, android-17
  "$MOBIUM_BIN" daemon stop >/dev/null 2>&1
  if [ -n "$EMU_BOOTED" ]; then
    adb -s "$EMU" emu kill >/dev/null 2>&1
    i=0; while adb devices | grep -q "^$EMU"; do i=$((i+1)); [ $i -gt 30 ] && break; sleep 2; done
  fi
  EMU_BOOTED=""
done
IFS=$OLD_IFS
if [ "$NIGHTLY_IOS" = 1 ]; then
  # Split on commas in this shell, not a pipe's subshell, so the exit trap
  # knows which simulator to shut down and WORST comes back.
  OLD_IFS=$IFS; IFS=,
  for entry in $NIGHTLY_IOS_SIMS; do
    IFS=$OLD_IFS
    [ -n "$entry" ] || continue
    name=${entry%@*}; runtime=${entry#*@}
    found=$(sim_of "$name" "$runtime")
    if [ -z "$found" ]; then
      echo "no $name on $runtime: left out tonight"; WORST=1; WORSE_ON="$WORSE_ON (no $name on $runtime)"; continue
    fi
    SIM=${found%% *}; SIM_BOOTED=""
    if [ "${found#* }" = Shutdown ]; then
      xcrun simctl boot "$SIM" && xcrun simctl bootstatus "$SIM" -b >/dev/null 2>&1 && SIM_BOOTED=1
    fi
    run_platform "$(echo "$runtime" | tr 'A-Z' 'a-z')" "$SIM" "$NIGHTLY_IOS_TASKS"   # ios-26-5
    "$MOBIUM_BIN" daemon stop >/dev/null 2>&1
    [ -n "$SIM_BOOTED" ] && xcrun simctl shutdown "$SIM" >/dev/null 2>&1
    SIM_BOOTED=""
  done
  IFS=$OLD_IFS
fi
if [ "$WORST" -ne 0 ]; then
  notify "worse than last night on$WORSE_ON — see nightly/out/$DAY-*.md"; exit 1
fi
exit 0
