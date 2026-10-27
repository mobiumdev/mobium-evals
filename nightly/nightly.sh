#!/bin/sh
# The nightly eval: Mobium's origin/main against the tasks, with nobody at the
# keyboard, on the Android emulator and then the iOS simulator. On each:
# controls first, which spend no tokens and check that the graders can still
# tell pass from fail; then each task the platform runs once under an agent,
# and the injection task (t26) under a second model. The simulators are
# NIGHTLY_IOS_SIMS, one iOS version each, run one after another. Each night
# writes nightly/out/<date>-android.md and <date>-ios-<version>.md, each
# compared with the same device's night before; anything worse — a control
# not as expected, a task that passed and now fails, an agent that obeyed the
# injection — posts a macOS notification and exits 1. NIGHTLY_IOS=0 leaves
# the simulators out.
#
#   nightly/nightly.sh                 # what launchd runs
#   NIGHTLY_MODELS=claude-haiku-5-5:low NIGHTLY_TASKS=t01,t26 nightly/nightly.sh
#
# It builds Mobium from origin/main in a scratch folder, so a checkout with
# work in progress is never switched. It boots the emulator only if no device
# answers, and shuts down only what it booted. Nothing is pushed or published.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/nightly/out"; mkdir -p "$OUT"
DAY=$(date +%Y-%m-%d)
LOG="$OUT/$DAY.log"
exec >>"$LOG" 2>&1
echo "== $(date) nightly start"

: "${MOBIUM_SRC:=$HOME/mobium-public}"
: "${ANDROID_HOME:=/opt/homebrew/share/android-commandlinetools}"
: "${NIGHTLY_AVD:=mobium-test}"
: "${NIGHTLY_DEVICE:=emulator-5554}"
: "${NIGHTLY_MODELS:=claude-haiku-5-5:low}"
: "${NIGHTLY_INJECTION_MODELS:=claude-sonnet-5-5:low}"
: "${NIGHTLY_TASKS:=}"
: "${NIGHTLY_APK:=$HOME/mobium-app-public/android/app/build/outputs/apk/release/app-release.apk}"
: "${NIGHTLY_IOS:=1}"
# Simulators as name@runtime, comma-separated: by name, not UDID, so a
# recreated simulator is still found.
: "${NIGHTLY_IOS_SIMS:=iPhone 17 Pro@iOS-26-5,iPhone 18 Pro@iOS-27-0}"
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

# 2. A device: the one that answers, or the AVD booted headless.
BOOTED=""
if ! adb -s "$NIGHTLY_DEVICE" get-state >/dev/null 2>&1; then
  emulator -avd "$NIGHTLY_AVD" -no-window -no-audio -no-snapshot-save >/dev/null 2>&1 &
  BOOTED=1
  i=0; until [ "$(adb -s "$NIGHTLY_DEVICE" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
    i=$((i+1)); [ $i -gt 120 ] && fail "$NIGHTLY_AVD did not boot in 6 minutes"; sleep 3; done
fi
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
  [ -n "$BOOTED" ] && adb -s "$NIGHTLY_DEVICE" emu kill >/dev/null 2>&1
  rm -rf "$BUILD"
}
trap cleanup EXIT

# The emulator boots from its last saved snapshot, which can predate the
# app the tasks need: on 2026-10-26 it brought back a MobiumApp with no Inbox
# Demo. So the app is installed again each night, from the local build.
if [ -f "$NIGHTLY_APK" ]; then
  adb -s "$NIGHTLY_DEVICE" install -r "$NIGHTLY_APK" | tail -1 || fail "installing $NIGHTLY_APK"
else
  echo "no $NIGHTLY_APK: MobiumApp is whatever the emulator already has"
fi

cd "$HERE" || fail "cd $HERE"
WORST=0
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

WORSE_ON=""
run_platform android "$NIGHTLY_DEVICE" "$NIGHTLY_TASKS"
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
