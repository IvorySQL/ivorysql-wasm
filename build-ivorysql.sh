#!/bin/bash
#
# 一键编译新版本 IvorySQL 浏览器在线体验镜像
#
# 用法:
#   ./build-ivorysql.sh <IvorySQL版本号> [缓存目录]
#
# 示例:
#   ./build-ivorysql.sh 5.7
#   ./build-ivorysql.sh 5.7 /data/cache
#
# 缓存目录(默认为项目根目录)中可预置:
#   - dl-seed.tar.gz          dl/ 源码缓存(加速编译)
#   - IvorySQL_<版本>.tar.gz  IvorySQL 源码包
# 找到则直接使用,找不到则打印日志并执行原有的下载/报错逻辑。
#
# 自动完成的步骤:
#   1. 若 packages/buildroot/dl/ 为空,解开 dl-seed 源码缓存(加速编译)
#   2. 更新 packages/buildroot/build.sh 中的 IVORYSQL_VERSION
#   3. 在 config/board/pg-browser/IvorySQL/ 下新建版本目录(以最新版本为模板)
#   4. 获取 IvorySQL_<版本>.tar.gz 到 dl/postgresql/(优先缓存目录,否则从 GitHub 下载)
#   5. 计算 sha256 并生成 postgresql.hash(含从包内提取的 COPYRIGHT license hash)
#   6. 执行 packages/buildroot/build.sh:构建镜像并打开构建容器
#      (进入容器后手动执行 make -j8 开始编译)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BR="$ROOT/packages/buildroot"
BOARD="$BR/config/board/pg-browser/IvorySQL"
GH_URL_BASE="https://github.com/IvorySQL/IvorySQL/archive/refs/tags"
GH_PROXY="https://ghfast.top/"   # GitHub 加速代理,失效时自动回退直连

VERSION="${1:-}"
CACHE_DIR="${2:-$ROOT}"

if [ -z "$VERSION" ]; then
    echo "用法: $0 <IvorySQL版本号> [缓存目录]" >&2
    echo "示例: $0 5.7" >&2
    exit 1
fi
if [ ! -d "$CACHE_DIR" ]; then
    echo "ERROR: 缓存目录不存在: $CACHE_DIR" >&2
    exit 1
fi
CACHE_DIR="$(cd "$CACHE_DIR" && pwd)"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: 版本号格式不正确: $VERSION(应形如 5.7)" >&2
    exit 1
fi

PKG_NAME="IvorySQL_${VERSION}.tar.gz"

echo "==> [1/6] 准备 dl/ 源码缓存"
if [ -d "$BR/dl" ] && [ -n "$(ls -A "$BR/dl" 2>/dev/null)" ]; then
    echo "    dl/ 已有缓存,跳过 dl-seed(如需强制重建请清空 $BR/dl)"
else
    DL_SEED="$CACHE_DIR/dl-seed.tar.gz"
    if [ ! -f "$DL_SEED" ]; then
        echo "ERROR: 缓存目录中找不到 dl-seed.tar.gz: $CACHE_DIR" >&2
        echo "       可先用 (cd packages/buildroot && tar czf ../../dl-seed.tar.gz --exclude='*.lock' dl/) 生成" >&2
        exit 1
    fi
    echo "    使用缓存目录中的 dl-seed: $DL_SEED"
    tar xzf "$DL_SEED" -C "$BR"
fi

echo "==> [2/6] build.sh 设置 IVORYSQL_VERSION=$VERSION"
sed -i "s/^export IVORYSQL_VERSION=.*/export IVORYSQL_VERSION=$VERSION/" "$BR/build.sh"

echo "==> [3/6] 准备版本配置目录 $BOARD/$VERSION"
if [ -d "$BOARD/$VERSION" ]; then
    echo "    目录已存在,复用(将重新生成 postgresql.hash)"
else
    template="$(ls -d "$BOARD"/*/ | sort -V | tail -1)"
    echo "    以 $template 为模板"
    mkdir -p "$BOARD/$VERSION"
    cp "$template/postgresql.mk" "$template/postgresql.hash" "$BOARD/$VERSION/"
fi

echo "==> [4/6] 获取 $PKG_NAME"
mkdir -p "$BR/dl/postgresql"
PKG_FILE="$BR/dl/postgresql/$PKG_NAME"
if [ -f "$PKG_FILE" ] && tar tzf "$PKG_FILE" >/dev/null 2>&1; then
    echo "    dl/postgresql/ 中已存在且完整,跳过"
elif [ -f "$CACHE_DIR/$PKG_NAME" ] && tar tzf "$CACHE_DIR/$PKG_NAME" >/dev/null 2>&1; then
    echo "    使用缓存目录中的 $PKG_NAME: $CACHE_DIR/$PKG_NAME"
    cp "$CACHE_DIR/$PKG_NAME" "$PKG_FILE"
else
    echo "    缓存目录未找到可用的 $PKG_NAME,执行下载逻辑"
    rm -f "$PKG_FILE"
    ok=0
    for url in "${GH_PROXY}${GH_URL_BASE}/${PKG_NAME}" "${GH_URL_BASE}/${PKG_NAME}"; do
        echo "    尝试: $url"
        if curl -fL --retry 3 --connect-timeout 15 -o "$PKG_FILE" "$url" \
            && tar tzf "$PKG_FILE" >/dev/null 2>&1; then
            ok=1; break
        fi
        echo "    该源失败,换下一个"
    done
    if [ "$ok" != 1 ]; then
        rm -f "$PKG_FILE"
        echo "ERROR: $PKG_NAME 下载失败(代理与直连均不可用)" >&2
        exit 1
    fi
fi

echo "==> [5/6] 生成 postgresql.hash"
PKG_HASH="$(sha256sum "$PKG_FILE" | cut -d' ' -f1)"
# 前两行(下载来源注释 + 源码包 hash)按新版本生成;
# 第 3 行起(license 文件 hash 等)沿用模板,与历史版本目录的做法一致
HASH_TAIL="$(tail -n +3 "$BOARD/$VERSION/postgresql.hash")"
cat > "$BOARD/$VERSION/postgresql.hash" <<EOF
# From ${GH_URL_BASE}/${PKG_NAME}
sha256  ${PKG_HASH}  ${PKG_NAME}
${HASH_TAIL}
EOF
echo "    sha256($PKG_NAME) = $PKG_HASH"

echo "==> [6/6] 构建镜像并打开容器(进入后执行 make -j8 开始编译)"
cd "$BR"
exec ./build.sh
