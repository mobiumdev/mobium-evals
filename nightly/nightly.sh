#!/bin/sh
# The nightly eval: Mobium's origin/main against the tasks, with nobody at the
# keyboard. Controls first, which spend no tokens and check that the graders
# can still tell pass from fail; then each task once under an agent, and the
# injection task (t26) under a second model. Each night writes
# nightly/out/<date>.md and compares with the night before; anything worse —
# a control not as expected, a task that passed and now fails, an agent that
# obeyed the injection — posts a macOS notification and exits 1.
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
cleanup() {
  "$MOBIUM_BIN" daemon stop >/dev/null 2>&1
  [ -n "$BOOTED" ] && adb -s "$NIGHTLY_DEVICE" emu kill >/dev/null 2>&1
  rm -rf "$BUILD"
}
trap cleanup EXIT

cd "$HERE" || fail "cd $HERE"
TASKS_ARG=""; [ -n "$NIGHTLY_TASKS" ] && TASKS_ARG="--tasks $NIGHTLY_TASKS"

# 3. Controls: the graders still tell pass from fail.
uv run mobium-evals --device "$NIGHTLY_DEVICE" $TASKS_ARG --seed "$SEED" controls; CONTROLS=$?
CONTROLS_RUN=$(ls -d runs/*-controls | tail -1)

# 4. Each task once under an agent; the injection task under a second model.
uv run mobium-evals --device "$NIGHTLY_DEVICE" $TASKS_ARG --seed "$SEED" run --models "$NIGHTLY_MODELS"
AGENT_RUN=$(ls -d runs/*-agent | tail -1)
uv run mobium-evals --device "$NIGHTLY_DEVICE" --tasks t26 --seed "$SEED" run --models "$NIGHTLY_INJECTION_MODELS" --repeats 2
INJECTION_RUN=$(ls -d runs/*-agent | tail -1)

# 5. The night's report, and what got worse since the last one.
uv run python nightly/summarize.py --day "$DAY" --commit "$COMMIT" --controls "$CONTROLS" \
  --controls-run "$CONTROLS_RUN" --agent-run "$AGENT_RUN" --injection-run "$INJECTION_RUN" --out "$OUT"
WORSE=$?
echo "== $(date) nightly done: controls=$CONTROLS worse=$WORSE"
if [ "$CONTROLS" -ne 0 ] || [ "$WORSE" -ne 0 ]; then
  notify "worse than last night — see nightly/out/$DAY.md"; exit 1
fi
exit 0
