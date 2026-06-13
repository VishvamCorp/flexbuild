#!/usr/bin/env python3

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: patch_gst_plugins_bad_wayland.py <meson.build> <protocols_dir>",
            file=sys.stderr,
        )
        return 2

    path = Path(sys.argv[1])
    protocols_dir = sys.argv[2]
    text = path.read_text()

    old = "  protocols_datadir = wl_protocol_dep.get_variable('pkgdatadir')"
    marker_block = """  # cartzy-cross-wayland-protocols-fallback
  protocols_datadir = join_paths(get_option('prefix'),
    get_option('datadir'), 'wayland-protocols')"""
    new = f"""  # cartzy-cross-wayland-protocols-fallback
  protocols_datadir = '{protocols_dir}'"""

    if old in text:
        text = text.replace(old, new, 1)
    elif marker_block in text:
        text = text.replace(marker_block, new, 1)
    elif new in text:
        pass
    else:
        print("wayland protocols block not found in meson.build", file=sys.stderr)
        return 1

    path.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
