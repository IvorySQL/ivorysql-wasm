FROM rastasheep/ubuntu-sshd:18.04

# Buildroot version to use
ARG BUILD_ROOT_RELEASE=2022.08

# Root password for SSH
ARG ROOT_PASSWORD=browser-vm
# Setup SSH (for Windows users) and prepare apt-get
# 方案 5：apt 源换清华 bionic 镜像（原 mirror:// 选点慢且不稳定）
RUN echo 'root:${ROOT_PASSWORD}' | chpasswd; \
    # Install all Buildroot deps
    sed -i -E 's#https?://(us\.)?(archive|security)\.ubuntu\.com/ubuntu/#https://mirrors.tuna.tsinghua.edu.cn/ubuntu/#g; s#mirror://mirrors\.ubuntu\.com/mirrors\.txt#https://mirrors.tuna.tsinghua.edu.cn/ubuntu#g' /etc/apt/sources.list; \
    dpkg --add-architecture i386; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get -q update;

# Install all Buildroot deps and prepare buildroot
WORKDIR /root

RUN DEBIAN_FRONTEND=noninteractive apt-get -q -y install \
    bc \
    build-essential \
    bzr \
    cpio \
    cvs \
    git \
    unzip \
    wget \
    libc6:i386 \
    libncurses5-dev \
    libssl-dev \
    vim \
    rsync; \
    wget -c http://buildroot.org/downloads/buildroot-${BUILD_ROOT_RELEASE}.tar.gz; \
    tar axf buildroot-${BUILD_ROOT_RELEASE}.tar.gz;

# 修复 kconfig 在 output/ 为挂载点时 rename() 跨文件系统失败（EXDEV）导致
# syncconfig 报 "Error during update of the configuration" 的问题：
# 让 conf_write_autoconf() 把临时文件写到 output/ 内的目标文件旁边
COPY patches/kconfig-autoconf-crossfs.patch /tmp/
RUN patch -p1 -d /root/buildroot-${BUILD_ROOT_RELEASE} < /tmp/kconfig-autoconf-crossfs.patch

# configure the locales
ENV LANG='C' \
    LANGUAGE='en_US:en' \
    LC_ALL='C' \
    NOTVISIBLE="in users profile" \
    TERM=xterm

# Buildroot will place built artifacts here at the end.
VOLUME /build

WORKDIR /root/buildroot-${BUILD_ROOT_RELEASE}

COPY config /config

RUN cp -r /config/* /config/.config .

# oreo add for ivorysql version
# ARG 下移到 apt/wget 层之后：改版本号不再使前序镜像层缓存全部失效
ARG IVORYSQL_VERSION
RUN echo "Building IvorySQL ${IVORYSQL_VERSION}"
RUN cp -r /config/board/pg-browser/IvorySQL/${IVORYSQL_VERSION}/* package/postgresql
ENTRYPOINT ["bash"]
