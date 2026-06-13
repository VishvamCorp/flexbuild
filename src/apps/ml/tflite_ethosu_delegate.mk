# Copyright 2023-2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

# TensorFlow Lite Ethos-u Delegate on imx93

# DEPEND: tensorflow-lite ethosu-driver-stack libpython3.11-dev


tflite_ethosu_delegate: tflite ethosu_driver_stack
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = tiny -o $(DISTROVARIANT) = base ] && exit || \
	 $(call repo-mngr,fetch,tflite_ethosu_delegate,apps/ml) && \
	 if [ ! -f $(DESTDIR)/usr/lib/libtensorflow-lite.so ]; then \
	     bld tflite -r $(DISTROTYPE):$(DISTROVARIANT) -a $(DESTARCH); \
	 fi && \
	 if [ ! -f $(DESTDIR)/usr/lib/libethosu.so ]; then \
	     bld ethosu_driver_stack -r $(DISTROTYPE):$(DISTROVARIANT) -a $(DESTARCH); \
	 fi && \
	 $(call fbprint_b,"tflite_ethosu_delegate") && \
	 cd $(MLDIR)/tflite_ethosu_delegate && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 mkdir -p build_$(DISTROTYPE)_$(ARCH) && \
	 cmake  -S $(MLDIR)/tflite_ethosu_delegate \
		-B $(MLDIR)/tflite_ethosu_delegate/build_$(DISTROTYPE)_$(ARCH) \
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
		-DCMAKE_CXX_FLAGS="--sysroot=$(RFSDIR) -I$(DESTDIR)/usr/include -I$(RFSDIR)/usr/include -I$(RFSDIR)/usr/include/python3.11" \
		-DCMAKE_EXE_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu -Wl,-rpath-link,$(DESTDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DCMAKE_SHARED_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu -Wl,-rpath-link,$(DESTDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DFETCHCONTENT_FULLY_DISCONNECTED=OFF \
		-DFETCHCONTENT_SOURCE_DIR_TENSORFLOW=$(MLDIR)/tflite \
		-DTFLITE_LIB_LOC=$(DESTDIR)/usr/lib/libtensorflow-lite.so \
		-DPython_INCLUDE_DIRS=$(RFSDIR)/usr/include/python3.11 \
		-DPython_EXECUTABLE=/usr/bin/python3.11 \
		-DPython_LIBRARY=$(RFSDIR)/usr/lib/aarch64-linux-gnu/libpython3.11.so $(LOG_MUTE) && \
	 $(MAKE) -j$(JOBS) -C build_$(DISTROTYPE)_$(ARCH) ethosu_delegate $(LOG_MUTE) && \
	 $(CROSS_COMPILE)strip build_$(DISTROTYPE)_$(ARCH)/libethosu_delegate.so && \
	 install -m 0644 build_$(DISTROTYPE)_$(ARCH)/libethosu_delegate.so $(DESTDIR)/usr/lib && \
	 $(call fbprint_d,"tflite_ethosu_delegate")
