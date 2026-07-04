#!/usr/bin/env bash
# mobile-fork has no desktop app (this branch is iOS-only) — so instead of
# launching the TUI, this helper switches you to a desktop branch and hands
# off to THAT branch's run.sh (the real venv launcher).
#
#   ./run.sh            # asks which branch, then switches + launches
#   ./run.sh master     # switch straight to master and launch
#   ./run.sh test       # switch straight to test and launch
set -e
cd "$(dirname "$0")"

branch="${1:-}"
if [ -z "$branch" ]; then
    echo "This is the iOS-only branch (mobile-fork) — the desktop app lives on master/test."
    echo
    echo "  1) master  (release)"
    echo "  2) test    (dev)"
    echo "  q) stay on mobile-fork"
    echo
    printf "Switch to: "
    read -r pick
    case "$pick" in
        1|master) branch=master ;;
        2|test)   branch=test ;;
        *)        echo "Staying on mobile-fork."; exit 0 ;;
    esac
else
    shift
fi

case "$branch" in
    master|test) ;;
    *) echo "Unknown branch '$branch' — expected master or test."; exit 1 ;;
esac

git switch "$branch"
# The switched-to branch has the real desktop launcher at this same path;
# exec a fresh copy of it (never keep running a file that just changed).
exec ./run.sh "$@"
