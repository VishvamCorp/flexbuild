# Copyright 2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

# https://github.com/google/flatbuffers
# Memory Efficient Serialization Library

# The native version 2.0.8 of Debian 12 libflatbuffers-dev doesn't match the required version 23.5.26 used for NNStreamer build.


flatbuffers:
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = tiny -o $(DISTROVARIANT) = base ] && exit || \
	 $(call fbprint_b,"flatbuffers") && \
	 $(call repo-mngr,fetch,flatbuffers,apps/ml) && \
	 cd $(MLDIR)/flatbuffers && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 mkdir -p build_$(DISTROTYPE)_$(ARCH) && \
	 cmake  -S $(MLDIR)/flatbuffers \
		-B $(MLDIR)/flatbuffers/build_$(DISTROTYPE)_$(ARCH) \
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
		-DFLATBUFFERS_BUILD_TESTS=OFF \
		-DFLATBUFFERS_BUILD_SHAREDLIB=ON $(LOG_MUTE) && \
	 cmake --build $(MLDIR)/flatbuffers/build_$(DISTROTYPE)_$(ARCH) -j$(JOBS) --target all $(LOG_MUTE) && \
	 cmake --install build_$(DISTROTYPE)_$(ARCH) --prefix /usr $(LOG_MUTE) && \
	 $(call fbprint_d,"flatbuffers")
