# Local build from a LocalMind source checkout on CachyOS / Arch.
pkgname=localmind
pkgver=1.0.0rc3
pkgrel=2
pkgdesc='Local, offline-capable desktop AI assistant'
arch=('x86_64')
license=('LicenseRef-Unspecified')
depends=('python' 'python-fastapi' 'uvicorn' 'python-httpx' 'python-dotenv'
         'python-python-multipart' 'python-pypdf' 'python-pillow' 'python-psutil'
         'python-nvidia-ml-py' 'pyside6' 'qt6-webengine' 'qt6-wayland')
optdepends=('ollama: local language model server'
            'ollama-cuda: local language model server with NVIDIA acceleration'
            'pipewire-pulse: microphone and playback through Qt WebEngine'
            'wireplumber: PipeWire session manager'
            'libsecret: Home Assistant token storage through Secret Service'
            'hyprland: supported Wayland window controls')
options=('!strip')

package() {
    local target="$pkgdir/usr/lib/localmind"
    install -d "$target"
    cp -r "$startdir/config" "$startdir/static" "$target/"
    install -Dm644 "$startdir/start.py" "$target/start.py"
    install -m644 "$startdir/requirements.txt" "$startdir/requirements-voice.txt" "$target/"
    for source_file in "$startdir"/localmind/*.py; do
        install -Dm644 "$source_file" "$target/localmind/${source_file##*/}"
    done
    install -Dm755 "$startdir/installer/linux/localmind" "$pkgdir/usr/bin/localmind"
    install -Dm644 "$startdir/installer/linux/localmind.desktop" \
        "$pkgdir/usr/share/applications/localmind.desktop"
    install -Dm644 "$startdir/static/assets/localmind.png" \
        "$pkgdir/usr/share/icons/hicolor/256x256/apps/localmind.png"
}
