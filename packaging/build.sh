#!/usr/bin/env bash
# Build in an AlmaLinux 8 (glibc 2.28) environment for official release assets.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
component=${1:-core}
case "$component" in
    core)
        if [[ ! -x .build/tmux-install/bin/tmux ]]; then
            git clone https://github.com/tmux/tmux.git .build/tmux-source
            git -C .build/tmux-source checkout --detach 0dac7fe434d029a4f0b819cba8eb7963df291990
            python3 packaging/patches/tmux-process-title.py .build/tmux-source
            (cd .build/tmux-source && sh autogen.sh && ./configure --prefix="$root/.build/tmux-install" && make -j2 && make install)
        fi
        cargo build --release --locked
        bash dev/build_files.sh
        mkdir -p .build/release-native
        cc -shared -fPIC -Wall -Wextra -Werror -Os terminal_agent/native/readline.c -o .build/release-native/terminal-agent-readline.so -ldl
        strip target/release/cosmos .build/libcosmos_files.so .build/release-native/terminal-agent-readline.so
        command -v uv >/dev/null || { echo 'Build dependency missing: uv' >&2; exit 1; }
        export UV_PYTHON_INSTALL_DIR="$root/.build/release-python"
        uv python install 3.12
        python_runtime=$(uv python find --managed-python 3.12)
        python_home=$(dirname -- "$(dirname -- "$python_runtime")")
        [[ -x .venv/bin/python ]] || uv venv --python "$python_runtime" .venv
        rm -rf .build/release-deps
        uv pip install --python "$python_runtime" --target .build/release-deps --only-binary :all: --require-hashes -r packaging/requirements.lock
        python3 packaging/assemble.py core "$python_home"
        ;;
    agent)
        stage="$root/.build/release-agent"
        mkdir -p "$stage"
        bash packaging/build_agent.sh "$stage"
        python3 packaging/assemble.py agent "$stage"
        ;;
    pdf|rime)
        bash packaging/build_optional.sh "$component"
        ;;
    -h|--help)
        echo 'Usage: packaging/build.sh [core|agent|pdf|rime]'
        echo 'Build-time dependencies only; end-user archives contain Python and precompiled native components.'
        ;;
    *) echo "Unknown component: $component" >&2; exit 2 ;;
esac
