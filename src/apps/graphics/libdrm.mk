# Copyright 2017-2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

libdrm:
	@[ $(SOCFAMILY) != IMX -a $${MACHINE:0:7} != ls1028a -o \
	   $(DISTROVARIANT) = base -o $(DISTROVARIANT) = tiny ] && exit || \
	 $(call fbprint_b,"libdrm") && \
	 $(call repo-mngr,fetch,libdrm,apps/graphics) && \
	 cd $(GRAPHICSDIR)/libdrm && \
	 build_opts="\
		--prefix=/usr \
		--default-library=shared --buildtype=release \
		-Dcairo-tests=disabled \
		-Dinstall-test-programs=true \
		-Dman-pages=disabled \
		-Dtests=true \
		-Dudev=false \
		-Dvalgrind=disabled \
		-Dc_link_args=\"-pthread\""; \
	 if [ "$(MACHINE)" = imx8mpcartzy ]; then \
	     build_opts="$$build_opts \
		-Damdgpu=disabled \
		-Detnaviv=enabled \
		-Dexynos=disabled \
		-Dfreedreno=disabled \
		-Dfreedreno-kgsl=false \
		-Dintel=disabled \
		-Dnouveau=disabled \
		-Domap=disabled \
		-Dradeon=disabled \
		-Dtegra=disabled \
		-Dvc4=disabled \
		-Dvivante=true \
		-Dvmwgfx=disabled"; \
	 else \
	     build_opts="$$build_opts \
		-Damdgpu=enabled \
		-Detnaviv=enabled \
		-Dexynos=disabled \
		-Dfreedreno=enabled \
		-Dfreedreno-kgsl=false \
		-Dintel=enabled \
		-Dnouveau=enabled \
		-Domap=enabled \
		-Dradeon=enabled \
		-Dtegra=disabled \
		-Dvc4=enabled \
		-Dvivante=true \
		-Dvmwgfx=enabled"; \
	 fi && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 sed -e 's%@TARGET_CROSS@%$(CROSS_COMPILE)%g' -e 's%@STAGING_DIR@%$(RFSDIR)%g' \
	     -e 's%@DESTDIR@%$(DESTDIR)%g' $(FBDIR)/src/system/meson.cross > meson.cross && \
	 PYTHONNOUSERSITE=y PKG_CONFIG_SYSROOT_DIR=$(RFSDIR) \
	 meson setup build_$(DISTROTYPE)_$(ARCH) \
		--cross-file=meson.cross $$build_opts $(LOG_MUTE) && \
	 PYTHONNOUSERSITE=y DESTDIR=$(DESTDIR) \
	 ninja -j$(JOBS) install -C build_$(DISTROTYPE)_$(ARCH) $(LOG_MUTE) && \
	 $(call fbprint_d,"libdrm")
