# syntax=docker/dockerfile:1
FROM debian:bookworm

ARG http_proxy
ENV http_proxy=$http_proxy
ARG https_proxy
ENV https_proxy=$https_proxy
ARG no_proxy
ENV no_proxy=$no_proxy
# Optional apt-cacher-ng to speed up rebuilds (e.g. http://host.docker.internal:3142).
ARG APT_CACHE_PROXY
ENV DEBIAN_FRONTEND=noninteractive
ENV DEBCONF_NONINTERACTIVE_SEEN=true
RUN echo "Acquire::http::proxy \"$http_proxy\";" | tee -a /etc/apt/apt.conf && \
    echo "Acquire::https::proxy \"$https_proxy\";" | tee -a /etc/apt/apt.conf && \
    if [ -n "$APT_CACHE_PROXY" ]; then \
        echo "Acquire::http::Proxy \"$APT_CACHE_PROXY\";" > /etc/apt/apt.conf.d/01proxy && \
        echo "Acquire::https::Proxy \"$APT_CACHE_PROXY\";" >> /etc/apt/apt.conf.d/01proxy; \
    fi && \
    echo 'PS1="[\u@\h \W]\$ "' | tee -a /root/.bashrc 1>/dev/null && \
    echo syntax on > /root/.vimrc
RUN rm -rf /var/lib/apt/lists/* && apt autoclean
RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt/lists \
    apt-get update --fix-missing && apt-get install -y locales && \
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8 && export LANG=en_US.utf8 && \
    apt-get install -y \
        u-boot-tools device-tree-compiler autoconf automake dh-autoreconf libssl-dev zip \
        openssl curl flex bison bc git gcc vim ethtool wget ftp make makedev tclsh ccache \
        binfmt-support qemu-system-common qemu-user-static debootstrap sudo ncurses-dev  \
        gcc-arm-linux-gnueabihf crossbuild-essential-arm64 gcc-aarch64-linux-gnu file    \
        build-essential gdb u-boot-tools device-tree-compiler python3 python3-dev python3-pip \
        libxml2-dev libsensors4-dev libssl-dev libedit-dev liblzma-dev tree binutils-dev \
        libnuma-dev libpcap-dev libtool mtd-utils libncurses5-dev libelf-dev net-tools   \
        libcunit1-dev pkg-config autotools-dev crossbuild-essential-armhf openssh-server \
        openssh-client crossbuild-essential-armhf qemu-utils kmod g++-aarch64-linux-gnu  \
	cpp-arm-linux-gnueabihf dosfstools ruby iputils-ping cpio rsync libtclap-dev     \
	parted rpm2cpio lsb-release xutils-dev libwayland-bin cmake locales texinfo gawk \
	chrpath diffstat scons libgflags-dev libhdf5-serial-dev python3-numpy python3-wheel \
	python3-h5py ninja-build bmap-tools pigz

RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt/lists \
    echo "deb http://deb.debian.org/debian bookworm-backports main" > /etc/apt/sources.list.d/backports.list && \
    apt-get update && \
    apt-get install -y -t bookworm-backports bdebstrap && \
    apt-get install -y eatmydata

# Pre-install flexbuild host-dependent packages so the container is ready immediately
# on first start, instead of spending ~20 min running 'bld host-dep' in the entrypoint.
COPY configs/debian/extra_packages_list /tmp/extra_packages_list
RUN --mount=type=cache,target=/var/cache/apt --mount=type=cache,target=/var/lib/apt/lists \
    . /tmp/extra_packages_list && \
    apt-get update && \
    apt-get install -y $host_dependent_packages && \
    # Do NOT rm /var/lib/apt/lists here: it lives in a BuildKit cache mount
    # shared with later rebuilds; wiping it would defeat the cache.
    rm -f /tmp/extra_packages_list && \
    mkdir -p /var/lib/cartzy && \
    touch /var/lib/cartzy/.host-deps-installed

RUN git config --global user.email  "debian@nxp.com" && \
    git config --global user.name "NXP debian"
