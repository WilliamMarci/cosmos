#!/usr/bin/env bash
# Executed by release builders, never by the user's installer.
set -euo pipefail
tier=${COSMOS_GLIBC_TIER:-2.28}
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
kind=${1:?pdf or rime}
build_library_path=${LD_LIBRARY_PATH:-}
work="$root/.build/optional-$kind"
mkdir -p "$work/sources"
stage="$work/stage"
rm -rf "$stage"
mkdir -p "$stage/vendor/$kind" "$stage/licenses/$kind"
prefix="$stage/vendor/$kind"
clone() {
    local url=$1 revision=$2 destination=$3
    if [[ ! -d $destination/.git ]]; then
        git init -q "$destination"
        git -C "$destination" remote add origin "$url"
    fi
    git -C "$destination" fetch --depth=1 origin "$revision"
    git -C "$destination" checkout --detach FETCH_HEAD
}
if [[ $kind == pdf ]]; then
    # Build the AlmaLinux source RPM, applying its maintained security patches.
    dnf download --source --destdir "$work/sources" poppler
    source_rpm=$(find "$work/sources" -name 'poppler-*.src.rpm' -print -quit)
    rpmkeys --checksig "$source_rpm"
    mkdir -p "$work/rpm"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
    rpm -i --define "_topdir $work/rpm" "$source_rpm"
    rpmbuild -bp --nodeps --define "_topdir $work/rpm" "$work/rpm/SPECS/poppler.spec"
    source=$(find "$work/rpm/BUILD" -mindepth 1 -maxdepth 1 -type d -name 'poppler-*' | head -1)
    cmake -S "$source" -B "$work/build" -DCMAKE_BUILD_TYPE=MinSizeRel -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib \
        -DENABLE_UTILS=ON -DENABLE_CPP=OFF -DENABLE_GLIB=OFF -DENABLE_QT5=OFF -DENABLE_QT6=OFF \
        -DBUILD_GTK_TESTS=OFF -DBUILD_QT5_TESTS=OFF -DBUILD_QT6_TESTS=OFF -DBUILD_CPP_TESTS=OFF \
        -DENABLE_NSS3=OFF -DENABLE_GPGME=OFF -DENABLE_LIBCURL=OFF -DENABLE_GOBJECT_INTROSPECTION=OFF
    cmake --build "$work/build" --parallel 2
    cmake --install "$work/build"
    find "$prefix/bin" -type f ! -name pdfinfo ! -name pdftoppm ! -name pdftotext -delete
    cp "$source/COPYING" "$stage/licenses/pdf/POPLER-COPYING"
else
    if [[ $tier == 2.34 ]]; then
        # EL9 repositories do not provide these development packages.
        # Build fixed upstream revisions privately, never on the user's host.
        clone https://github.com/s-yata/marisa-trie.git e54f296bb52d16693931c8b963744931ef1e37f7 "$work/sources/marisa"
        (cd "$work/sources/marisa" && autoreconf -i && ./configure --prefix="$prefix" --libdir="$prefix/lib" --disable-static && make -j2 && make install)
        clone https://github.com/BYVoid/OpenCC.git 556ed22496d650bd0b13b6c163be9814637970ae "$work/sources/opencc"
        cmake -S "$work/sources/opencc" -B "$work/opencc-build" -DCMAKE_BUILD_TYPE=MinSizeRel -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_PREFIX_PATH="$prefix" -DCMAKE_CXX_FLAGS="-I$prefix/include" -DUSE_SYSTEM_MARISA=ON -DENABLE_GTEST=OFF -DBUILD_DOCUMENTATION=OFF
        cmake --build "$work/opencc-build" --parallel 2
        cmake --install "$work/opencc-build"
        cp "$work/sources/marisa/COPYING.md" "$stage/licenses/rime/MARISA-LICENSE"
        cp "$work/sources/opencc/LICENSE" "$stage/licenses/rime/OPENCC-LICENSE"
        export CMAKE_PREFIX_PATH="$prefix${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
        export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
    # AlmaLinux 8's Boost is older than librime's minimum; build only regex.
    if [[ ! -f $work/boost/lib/libboost_regex.a ]]; then
        curl -fL --retry 3 https://archives.boost.io/release/1.83.0/source/boost_1_83_0.tar.bz2.json -o "$work/sources/boost.json"
        curl -fL --retry 3 https://archives.boost.io/release/1.83.0/source/boost_1_83_0.tar.bz2 -o "$work/sources/boost.tar.bz2"
        python3 - "$work/sources" <<'BOOST'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); expected=json.load(open(p/'boost.json'))['sha256']
assert hashlib.sha256((p/'boost.tar.bz2').read_bytes()).hexdigest()==expected
BOOST
        tar -xjf "$work/sources/boost.tar.bz2" -C "$work"
        (cd "$work/boost_1_83_0" && ./bootstrap.sh --with-libraries=regex --prefix="$work/boost" && ./b2 link=static cxxflags=-fPIC -j2 install)
    fi
    clone https://github.com/rime/librime.git 1b3417d2b6a11b5e50e0e1fa9dc396056aa11dce "$work/sources/librime"
    clone https://github.com/hchunhui/librime-lua.git 6da5d6cedb853380ed1b5b9b6979cb1a9c028353 "$work/sources/librime/plugins/lua"
    clone https://github.com/iDvel/rime-ice.git 99662ba01e3affa6a0f009174ca530b887bac3b6 "$work/sources/rime-ice"
    cmake -S "$work/sources/librime" -B "$work/build" -DCMAKE_BUILD_TYPE=MinSizeRel \
        -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_TEST=OFF \
        -DBUILD_MERGED_PLUGINS=ON -DENABLE_LOGGING=OFF -DBOOST_ROOT="$work/boost" -DBoost_NO_SYSTEM_PATHS=ON -DBoost_NO_BOOST_CMAKE=ON -DBoost_USE_STATIC_LIBS=ON
    cmake --build "$work/build" --parallel 2
    cmake --install "$work/build"
    mkdir -p "$prefix/share/rime-data"
    tar -C "$work/sources/rime-ice" --exclude=.git -cf - . | tar -C "$prefix/share/rime-data" -xf -
    printf 'patch:\n  schema_list:\n    - schema: rime_ice\n' > "$prefix/share/rime-data/default.custom.yaml"
    export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    mkdir -p "$prefix/share/rime-data/build"
    "$prefix/bin/rime_deployer" --build "$prefix/share/rime-data" "$prefix/share/rime-data" "$prefix/share/rime-data/build"
    test -f "$prefix/share/rime-data/build/rime_ice.schema.yaml"
    cp "$work/sources/librime/LICENSE" "$stage/licenses/rime/LIBRIME-LICENSE"
    cp "$work/sources/librime/plugins/lua/LICENSE" "$stage/licenses/rime/LIBRIME-LUA-LICENSE"
    find "$work/sources/rime-ice" -maxdepth 1 -iname '*license*' -exec cp {} "$stage/licenses/rime/" \;
    rm -rf "$prefix/bin" "$prefix/include" "$prefix/lib/pkgconfig" "$prefix/lib/cmake"
fi
export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python3 - "$root" "$stage" "$kind" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / 'packaging'))
from assemble import closure, copy, check_abi
stage, kind = Path(sys.argv[2]), sys.argv[3]
prefix = stage / 'vendor' / kind
# Dereference library symlinks: optional archives contain regular files only.
for library in list(prefix.rglob('*.so*')):
    if library.is_symlink():
        target = library.resolve(); library.unlink(); copy(target, library)
for binary in list((prefix / 'bin').glob('*')) + list((prefix / 'lib').glob('*.so*')):
    if binary.is_file():
        closure(binary, prefix / 'lib')
        check_abi(binary)
PY
find "$prefix" -type f -name '*.a' -delete
find "$prefix" -type f \( -name '*.so*' -o -path '*/bin/*' \) -exec env LD_LIBRARY_PATH="$build_library_path" strip --strip-unneeded {} +
# Preserve corresponding source alongside GPL/other optional binaries.
mkdir -p "$root/dist"
tar -C "$work/sources" --exclude=.git --exclude='*/build' -czf "$root/dist/cosmos-0.2.1-$kind-glibc$tier-sources.tar.gz" .
python3 "$root/packaging/assemble.py" "$kind" "$stage"
