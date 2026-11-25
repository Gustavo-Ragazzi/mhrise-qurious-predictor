"""Game icons extracted from the user's own install (.uvs atlases + .tex textures) as PNG data URLs.

Formats ported from wwylele/mhrice (MIT/Apache-2.0) src/uvs.rs and src/tex.rs, via
mhrise-set-builder's tools/extract_icons.py. Icons are cached next to the game data cache.
"""

from __future__ import annotations

import base64
import io
import json
import struct
from pathlib import Path

from mhrise_exporter.pak import open_game_paks

CACHE_VERSION = 4

# name -> (atlas, group, index)
SPRITES = {
    "slot1": ("Slot_Icon", 0, 0),
    "slot2": ("Slot_Icon", 0, 1),
    "slot3": ("Slot_Icon", 0, 2),
    "slot4": ("Slot_Icon_MR", 0, 1),
    "fire": ("state_icon", 0, 3),
    "water": ("state_icon", 0, 4),
    "thunder": ("state_icon", 0, 5),
    "ice": ("state_icon", 0, 6),
    "dragon": ("state_icon", 0, 7),
    "defense": ("state_icon", 0, 17),
    "defense_down": ("state_icon", 0, 18),
    "skill": ("message_window", 0, 170),  # the skill icon of the status screen (as in mhrice)
    "head": ("EquipIcon", 0, 0),
    "chest": ("EquipIcon", 0, 1),
    "arms": ("EquipIcon", 0, 2),
    "waist": ("EquipIcon", 0, 3),
    "legs": ("EquipIcon", 0, 4),
    "talisman": ("EquipIcon", 0, 5),
    "weapon": ("EquipIcon", 0, 15),
}
for _type, _index in enumerate((16, 15, 21, 19, 17, 23, 20, 18, 22, 25, 24, 26, 27, 28)):
    SPRITES[f"weapon{_type}"] = ("EquipIcon", 0, _index)


def _read_uvs(raw: bytes):
    if raw[:4] != b".SVU":
        raise ValueError("not a .uvs file")
    tex_count, group_count, _spr_count, anchors = struct.unpack_from("<IIII", raw, 4)
    tex_off, group_off, spr_off, str_off = struct.unpack_from("<QQQQ", raw, 24)

    def u16str(off):
        end = off
        while raw[end:end + 2] != b"\0\0":
            end += 2
        return raw[off:end].decode("utf-16-le")

    textures = []
    for t in range(tex_count):
        _id, path_off, *_ = struct.unpack_from("<QQQQQ", raw, tex_off + 40 * t)
        textures.append(u16str(str_off + path_off * 2))
    groups = [struct.unpack_from("<II", raw, group_off + 8 * g) for g in range(group_count)]
    pos = spr_off
    sprites = []
    for count, _start in groups:
        group = []
        for _ in range(count):
            _id, x0, y0, x1, y1, tex_index, anchor_count = struct.unpack_from("<QffffII", raw, pos)
            pos += 32 + (8 * anchor_count if anchors else 0)
            group.append((x0, y0, x1, y1, tex_index))
        sprites.append(group)
    return textures, sprites


def _read_tex(raw: bytes):
    import texture2ddecoder
    from PIL import Image

    if raw[:4] != b"TEX\0":
        raise ValueError("not a .tex file")
    _ver, width, height, _depth, _counts, fmt, layout = struct.unpack_from("<IHHHHII", raw, 4)
    if layout != 0xFFFFFFFF:
        raise ValueError("unsupported texture layout")
    offset, _len, len_padded = struct.unpack_from("<QII", raw, 40)
    data = raw[offset:offset + len_padded]
    decoders = {
        0x47: texture2ddecoder.decode_bc1, 0x48: texture2ddecoder.decode_bc1,
        0x4D: texture2ddecoder.decode_bc3, 0x4E: texture2ddecoder.decode_bc3,
        0x50: texture2ddecoder.decode_bc4, 0x53: texture2ddecoder.decode_bc5,
        0x62: texture2ddecoder.decode_bc7, 0x63: texture2ddecoder.decode_bc7,
    }
    if fmt in (0x1C, 0x1D):  # R8G8B8A8
        return Image.frombytes("RGBA", (width, height), data[:width * height * 4])
    if fmt not in decoders:
        raise ValueError(f"unsupported texture format {fmt:#x}")
    bgra = decoders[fmt](data, width, height)
    return Image.frombytes("RGBA", (width, height), bgra, "raw", "BGRA")


def extract(game_dir: Path) -> dict[str, str]:
    pak = open_game_paks(game_dir)
    out = {}
    try:
        atlases = {}
        for name, (atlas, g, i) in SPRITES.items():
            if atlas not in atlases:
                rel = f"gui/70_UVSequence/{atlas}"
                textures, sprites = _read_uvs(pak.read_any(rel + ".uvs", ["7"]))
                images = [_read_tex(pak.read_any(t.removesuffix(".tex") + ".tex", ["28", "30", "143221013"]))
                          for t in textures]
                atlases[atlas] = (images, sprites)
            images, sprites = atlases[atlas]
            x0, y0, x1, y1, ti = sprites[g][i]
            img = images[ti]
            crop = img.crop((round(x0 * img.width), round(y0 * img.height),
                             round(x1 * img.width), round(y1 * img.height)))
            buf = io.BytesIO()
            crop.save(buf, "PNG")
            out[name] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    finally:
        pak.close()
    return out


def load(game_dir: Path, cache_dir: Path, fingerprint: str) -> dict[str, str]:
    cache = cache_dir / "icons.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION and data.get("fingerprint") == fingerprint:
                return data["icons"]
        except (OSError, ValueError, KeyError):
            pass
    try:
        icons = extract(game_dir)
    except Exception:  # icons are cosmetic: the UI falls back to text/shapes
        return {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"version": CACHE_VERSION, "fingerprint": fingerprint, "icons": icons}),
                     encoding="utf-8")
    return icons
