export IVORYSQL_VERSION=5.1
sed -i "s/const version = \".*\"/const version = \"$IVORYSQL_VERSION\"/g" ../runtime/index.html
#add for ivorysql version
docker build --build-arg IVORYSQL_VERSION=$IVORYSQL_VERSION -t buildroot .

docker run \
    --rm \
    -v $PWD/tools:/tools \
    -v $PWD/build:/build \
    -v $PWD/config:/config \
    -e IVORYSQL_VERSION=$IVORYSQL_VERSION \
    -ti \
    --platform linux/amd64 \
    buildroot