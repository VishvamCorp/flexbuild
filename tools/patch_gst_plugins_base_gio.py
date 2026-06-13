#!/usr/bin/env python3

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_gst_plugins_base_gio.py <meson.build>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    text = path.read_text()

    marker = "# cartzy-cross-gio-fallback"
    if marker in text:
        return 0

    old = """if gio_dep.type_name() == 'pkgconfig'
    core_conf.set_quoted('GIO_MODULE_DIR',
        gio_dep.get_variable('giomoduledir'))
    core_conf.set_quoted('GIO_LIBDIR',
        gio_dep.get_variable('libdir'))
    core_conf.set_quoted('GIO_PREFIX',
        gio_dep.get_variable('prefix'))
else
    core_conf.set_quoted('GIO_MODULE_DIR', join_paths(get_option('prefix'),
      get_option('libdir'), 'gio/modules'))
    core_conf.set_quoted('GIO_LIBDIR', join_paths(get_option('prefix'),
      get_option('libdir')))
    core_conf.set_quoted('GIO_PREFIX', join_paths(get_option('prefix')))
endif"""

    new = """# cartzy-cross-gio-fallback
core_conf.set_quoted('GIO_MODULE_DIR', join_paths(get_option('prefix'),
  get_option('libdir'), 'gio/modules'))
core_conf.set_quoted('GIO_LIBDIR', join_paths(get_option('prefix'),
  get_option('libdir')))
core_conf.set_quoted('GIO_PREFIX', join_paths(get_option('prefix')))"""

    if old not in text:
        print("gio config block not found in meson.build", file=sys.stderr)
        return 1

    path.write_text(text.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
