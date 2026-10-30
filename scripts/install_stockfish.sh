#!/usr/bin/env sh
# Installe Stockfish 17.1 dans bin/ selon le système et l'architecture (Linux, macOS, Termux).
set -eu
cd "$(dirname "$0")/.."
mkdir -p bin
if [ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux ]; then
  echo "Termux détecté : pkg install stockfish"
  pkg install -y stockfish
  ln -sf "$(command -v stockfish)" bin/stockfish
  exit 0
fi
os="$(uname -s)"; arch="$(uname -m)"
if [ "$os" = "Darwin" ]; then
  case "$arch" in
    arm64)  asset=stockfish-macos-m1-apple-silicon ;;
    x86_64) asset=stockfish-macos-x86-64-avx2 ; sysctl -n machdep.cpu.leaf7_features 2>/dev/null | grep -qi avx2 || asset=stockfish-macos-x86-64 ;;
    *) echo "architecture macOS non gérée : $arch — brew install stockfish"; exit 1 ;;
  esac
else
  case "$arch" in
    x86_64)  asset=stockfish-ubuntu-x86-64-avx2 ; grep -q avx2 /proc/cpuinfo 2>/dev/null || asset=stockfish-ubuntu-x86-64 ;;
    aarch64|arm64) asset=stockfish-android-armv8 ;;
    armv7l)  asset=stockfish-android-armv7 ;;
    *) echo "architecture non gérée : $arch — installe stockfish via ton gestionnaire de paquets"; exit 1 ;;
  esac
fi
url="https://github.com/official-stockfish/Stockfish/releases/download/sf_17.1/$asset.tar"
echo "téléchargement $url"
tmp=$(mktemp -d)
curl -sSL "$url" -o "$tmp/sf.tar"
tar -xf "$tmp/sf.tar" -C "$tmp"
bin=$(find "$tmp" -type f -name "stockfish*" ! -name "*.tar" | head -1)
cp "$bin" bin/stockfish-bin && chmod +x bin/stockfish-bin
rm -rf "$tmp"
printf 'uci\nquit\n' | bin/stockfish-bin | head -1
