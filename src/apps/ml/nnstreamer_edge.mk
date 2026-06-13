# Copyright 2023-2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

# NNStreamer-Edge library
# Remote source nodes for NNStreamer pipelines without GStreamer dependencies

# NNStreamer LICENSE: Apache-2.0

# DEPENDS: gtest

nnstreamer_edge:
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = tiny -o $(DISTROVARIANT) = base ] && exit || \
	 $(call fbprint_b,"nnstreamer_edge") && \
	 $(call repo-mngr,fetch,nnstreamer_edge,apps/ml) && \
	 cd $(MLDIR)/nnstreamer_edge && \
	 export PKG_CONFIG_LIBDIR=$(RFSDIR)/usr/lib/aarch64-linux-gnu/pkgconfig && \
	 export PKG_CONFIG_PATH=$(RFSDIR)/usr/share/pkgconfig && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 mkdir -p build_$(DISTROTYPE)_$(ARCH) && \
	 cmake  -S $(MLDIR)/nnstreamer_edge \
		-B build_$(DISTROTYPE)_$(ARCH) \
		-DCMAKE_BUILD_TYPE=release \
		-DCMAKE_SYSTEM_NAME=Linux \
		-DCMAKE_SYSTEM_PROCESSOR=aarch64 \
		-DCMAKE_C_COMPILER=$(CROSS_COMPILE)gcc \
		-DCMAKE_CXX_COMPILER=$(CROSS_COMPILE)g++ \
		-DCMAKE_SYSROOT=$(RFSDIR) \
		-DCMAKE_FIND_ROOT_PATH="$(RFSDIR);$(DESTDIR)" \
		-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
		-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
		-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
		-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
		-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
		-DCMAKE_C_FLAGS="--sysroot=$(RFSDIR) -I$(DESTDIR)/usr/include -I$(RFSDIR)/usr/include" \
		-DCMAKE_CXX_FLAGS="--sysroot=$(RFSDIR) -I$(DESTDIR)/usr/include -I$(RFSDIR)/usr/include" \
		-DCMAKE_EXE_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DCMAKE_SHARED_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DENABLE_TEST=OFF $(LOG_MUTE) && \
	 cmake --build build_$(DISTROTYPE)_$(ARCH) -j$(JOBS) --target all $(LOG_MUTE) && \
	 cmake --install build_$(DISTROTYPE)_$(ARCH) --prefix /usr $(LOG_MUTE) && \
	 mkdir -p $(RFSDIR)/usr/local/include/nnstreamer && \
	 mv $(DESTDIR)/usr/local/include/nnstreamer/nnstreamer-edge.h $(DESTDIR)/usr/include && \
	 mv $(DESTDIR)/pkgconfig/nnstreamer-edge.pc $(DESTDIR)/usr/lib/pkgconfig/ && \
	 rm -rf $(DESTDIR)/pkgconfig && \
	 $(call fbprint_d,"nnstreamer_edge")
