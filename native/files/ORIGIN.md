# Yazi source extraction

Upstream: https://github.com/sxyazi/yazi
Commit: 7c45837d553b6cb8032bd7fec2106fdb628e4017 (the existing vendor/yazi checkout).

natsort.rs is copied unchanged from yazi-shared/src/natsort.rs, with its original copyright and algorithm attribution. LICENSE-Yazi preserves the upstream MIT license. lib.rs is the Cosmos-owned C ABI; no Yazi executable or TUI is launched. Build with bash dev/build_files.sh (installed Rust is sufficient for this extracted std-only module; building the complete upstream workspace is not required).

This first extraction covers natural filename ordering only. Directory-first ordering, listing and presentation are Cosmos adapters around it. It does not claim Yazi feature parity or extract Yazi's task/VFS implementation yet.
