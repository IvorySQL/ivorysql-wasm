rm -rf filesystem/
cp -r ../buildroot/build/filesystem .

jq -r '.fsroot | map(select(.[0] == "bzImage"))[0][6]' < filesystem/filesystem.json

