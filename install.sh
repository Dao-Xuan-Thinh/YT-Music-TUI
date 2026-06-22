#!/usr/bin/env bash
# Installs a global `yttui` command (macOS / Linux).
# Run once per machine after cloning:   ./install.sh
set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
mkdir -p "$BIN"

# Launcher just execs run.sh (which self-heals the venv and launches from REPO).
cat > "$BIN/yttui" <<EOF
#!/usr/bin/env bash
exec "$REPO/run.sh" "\$@"
EOF
chmod +x "$BIN/yttui"
echo "Installed launcher: $BIN/yttui  ->  $REPO"

# Ensure ~/.local/bin is on PATH (persist in the right shell rc, idempotently).
case ":$PATH:" in
    *":$BIN:"*)
        echo "$BIN is already on your PATH."
        ;;
    *)
        rc="$HOME/.profile"
        case "$(basename "${SHELL:-}")" in
            zsh)  rc="$HOME/.zshrc" ;;
            bash) rc="$HOME/.bashrc" ;;
        esac
        line='export PATH="$HOME/.local/bin:$PATH"'
        if ! grep -qF "$line" "$rc" 2>/dev/null; then
            printf '\n# added by YT-Music-TUI install.sh\n%s\n' "$line" >> "$rc"
            echo "Added $BIN to PATH in $rc"
        fi
        echo "Open a NEW terminal (or run: source \"$rc\") to pick up the change."
        ;;
esac

echo "Done. From anywhere, run:  yttui"
