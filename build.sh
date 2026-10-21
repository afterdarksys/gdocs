#!/bin/sh
# Build and install gdocs from this checkout using its locked runtime dependencies.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
uv_cmd=${UV:-uv}
prefix=${PREFIX:-"$HOME/.local"}
target_count=0

usage() {
    cat <<'EOF'
Usage: ./build.sh [target ...] [prefix=/absolute/path]

Targets:
  build         Build wheel, source archive, and locked constraints in dist/ (default).
  install       Build and install gdocs into prefix/bin with an isolated environment.
  update        Rebuild and reinstall from this checkout using the current lockfile.
  dev           Sync the development environment, including test dependencies.
  test          Sync locked development dependencies and run local tests.
  check         Check shell syntax and run local tests.
  clean         Remove generated dist/ and build/ output; preserve .venv and settings.
  help          Show this help without requiring uv.

Options:
  prefix=PATH   Absolute install prefix (default: $HOME/.local; also PREFIX env).
  UV=PATH      Environment override for the uv executable.

Examples:
  ./build.sh
  ./build.sh test
  ./build.sh install
  ./build.sh update prefix="$HOME/.local"
  ./build.sh clean build

Requires uv and Python >=3.11 (uv can provision Python). Builds/installations may
access package registries. Tests do not log in or access live Google accounts.
Update uses the local checkout: it does not pull Git changes or upgrade uv.lock.
Add prefix/bin to PATH to run gdocs. OAuth credentials and profiles are untouched.
EOF
}

fail() { echo "build.sh: $*" >&2; exit 2; }
need_uv() { command -v "$uv_cmd" >/dev/null 2>&1 || fail "uv is required; install it from https://docs.astral.sh/uv/"; }

for argument in "$@"; do
    case "$argument" in
        prefix=*) prefix=${argument#prefix=} ;;
        build|install|update|dev|test|check|clean) target_count=$((target_count+1)) ;;
        help|-h|--help) ;;
        *) fail "unknown target or option: $argument (use help)" ;;
    esac
done
for argument in "$@"; do
    case "$argument" in help|-h|--help) usage; exit 0 ;; esac
done
case "$prefix" in /*) ;; *) fail "prefix must be an absolute path" ;; esac

build_project() {
    need_uv
    [ ! -L dist ] || fail "dist must not be a symlink"
    mkdir -p dist
    "$uv_cmd" export --locked --no-dev --no-emit-project --no-hashes --output-file dist/constraints.txt >/dev/null
    "$uv_cmd" build --sdist --wheel --no-build-logs --out-dir dist
}

install_project() {
    build_project
    # Select the current project's wheel, refusing stale mixed-version output.
    set -- "$project_dir"/dist/gdocs-*.whl
    [ "$#" -eq 1 ] && [ -f "$1" ] || fail "expected one gdocs wheel; run clean then install"
    UV_TOOL_DIR="$prefix/lib/gdocs-tools" UV_TOOL_BIN_DIR="$prefix/bin" \
        "$uv_cmd" tool install --force --reinstall-package gdocs --constraints "$project_dir/dist/constraints.txt" "$1"
    echo "Installed: $prefix/bin/gdocs"
    echo "Ensure $prefix/bin is on PATH."
}

dev_project() { need_uv; "$uv_cmd" sync --locked --extra dev; }
test_project() { dev_project; "$uv_cmd" run --locked --extra dev --no-sync python -m pytest; }

run_target() {
    case "$1" in
        build) build_project ;;
        install|update) install_project ;;
        dev) dev_project ;;
        test) test_project ;;
        check) sh -n "$project_dir/build.sh"; test_project ;;
        clean)
            [ ! -L dist ] && [ ! -L build ] || fail "refusing to clean symlink output directories"
            rm -rf -- "$project_dir/dist" "$project_dir/build"
            echo "Removed generated build output."
            ;;
    esac
}

if [ "$target_count" -eq 0 ]; then run_target build; fi
for argument in "$@"; do
    case "$argument" in prefix=*) ;; *) run_target "$argument" ;; esac
done
