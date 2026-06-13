# Copyright 2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause


# OpenSSL Provider for NXP EdgeLock secure element SE05X (SE050_C, SE051_E)

# An OpenSSL provider for NXP EdgeLock SE05x secure element product family

# generates libsssProvider.so


APPLET         ?= "SE05X_C"
APPLET_VERSION ?= "07_02"
APPLET_AUTH    ?= "None"


openssl_provider_se05x:
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = base -o $(DISTROVARIANT) = tiny ] && exit || \
	 $(call fbprint_b,"openssl_provider_se05x") && \
	 $(call repo-mngr,fetch,openssl_provider_se05x,apps/security) && \
	 cd $(SECDIR)/openssl_provider_se05x && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 mkdir -p build_$(DISTROTYPE)_$(ARCH) && \
	 cmake  -S $(SECDIR)/openssl_provider_se05x \
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
		-DPTMW_Applet=$(APPLET) \
		-DPTMW_SE05X_Ver=$(APPLET_VERSION) \
		-DPTMW_SE05X_Auth=$(APPLET_AUTH) \
		-DPTMW_HostCrypto=OPENSSL $(LOG_MUTE) && \
	 cmake --build build_$(DISTROTYPE)_$(ARCH) -j$(JOBS) --target all $(LOG_MUTE) && \
	 cmake --install build_$(DISTROTYPE)_$(ARCH) --prefix /usr $(LOG_MUTE) && \
	 $(call fbprint_d,"openssl_provider_se05x")
