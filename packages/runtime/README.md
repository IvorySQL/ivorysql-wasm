
# Postgres Browser

> Web shell to interact with [PostgreSQL](https://www.postgresql.org/) in the browser

## :zap: Getting started

1. Run `npx serve` and go to `http://localhost:3000`
2. There is no step 2

## :hammer_and_wrench: Update the filesystem

1. Run the build process in the [buildroot](/packages/buildroot/README.md#getting-started) package

2. Synchronize the new filesystem using:

```bash
./scripts/sync-fs.sh
```

3. [Cold boot and save a new snapshot](#cold-boot-and-saving-a-new-snapshot)

## :snowflake: Cold boot and saving a new snapshot

1. Go the `http://localhost:3000?boot=true`

2. Once the boot is completed, clear the cache and start psql (the runtime assumes psql is running when it loads a snapshot):
 `echo 3 > /proc/sys/vm/drop_caches && echo 3 > /proc/sys/kernel/printk && reset && psql -U postgres -d ivorysql -p 1521`

3. Save the state to a file clicking the `Save state to file` button

4. Put the state file into the `state` folder and compress it using [zstd](https://github.com/facebook/zstd):

```bash
zstd --ultra -22 state/v86state.bin && rm state/v86state.bin
```

5. Go to `http://localhost:3000`, instant boot!

## Tests

From `packages/runtime`, run the upload regression tests with Node.js 18 or newer:

```bash
node --test tests/upload-files.test.cjs
```

These tests exercise the page's upload handler and check the bytes passed to the
emulator. They use Node's Blob API for file reads and a recording emulator stub;
they do not boot a VM or run a database restore.

