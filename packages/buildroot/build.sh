export IVORYSQL_VERSION=5.6
sed -i "s/const version = \".*\"/const version = \"$IVORYSQL_VERSION\"/g" ../runtime/index.html
# 方案 6：预下载 IvorySQL 源码到持久化 dl/ 缓存，绕开 github 直连不稳定问题
# （buildroot 会直接复用 dl/postgresql/ 下的同名文件，跳过下载）
mkdir -p dl/postgresql output ccache
if [ ! -f "dl/postgresql/IvorySQL_${IVORYSQL_VERSION}.tar.gz" ]; then
    curl -fL --retry 3 --connect-timeout 15 \
        -o "dl/postgresql/IvorySQL_${IVORYSQL_VERSION}.tar.gz" \
        "https://github.com/IvorySQL/IvorySQL/archive/refs/tags/IvorySQL_${IVORYSQL_VERSION}.tar.gz" \
        || echo "WARNING: IvorySQL 预下载失败，buildroot 构建时会自行重试"
fi

#add for ivorysql version
docker build --build-arg IVORYSQL_VERSION=$IVORYSQL_VERSION -t buildroot .

# 方案 1~3：把 dl/（下载缓存）、output/（增量编译产物）、ccache/ 挂载出来，
# 容器退出后缓存保留，第二次构建不再全量重下/重编
docker run \
    --rm \
    -v $PWD/tools:/tools \
    -v $PWD/build:/build \
    -v $PWD/config:/config \
    -v $PWD/dl:/root/buildroot-2022.08/dl \
    -v $PWD/output:/root/buildroot-2022.08/output \
    -v $PWD/ccache:/root/.buildroot-ccache \
    -e IVORYSQL_VERSION=$IVORYSQL_VERSION \
    -ti \
    --platform linux/amd64 \
    buildroot