# Build, install and update

The project helper follows the target interface used by the neighboring projects:

```sh
./build.sh build
./build.sh install
./build.sh update
./build.sh test
./build.sh check
./build.sh clean
./build.sh help
```

`build` creates a wheel, source archive, and runtime version constraints in `dist/`.
`install` builds and installs into `$HOME/.local/bin` by default, with an isolated
uv tool environment under `$HOME/.local/lib/gdocs-tools`. Override with
`prefix=/absolute/path` or `PREFIX`. Add the prefix's `bin` directory to PATH.

`update` rebuilds and reinstalls from this checkout, including local changes,
without pulling Git or upgrading dependency versions. Update the checkout separately
when you want newer source. Install and update use constraints exported from `uv.lock`.
If stale wheels from different versions remain, run `./build.sh clean install`.

Install [uv](https://docs.astral.sh/uv/) first. Python 3.11 or newer is required;
uv can provision it. Builds and dependency installation may use package registries.
`dev` installs development dependencies, while `test` and `check` run local tests
without Google login or live account access. `UV=/path/to/uv` overrides the tool.

`clean` removes only `dist/` and `build/`. It preserves `.venv`, installed tools,
OAuth credentials, profiles, snapshots, and operation journals. No target logs in,
changes Google files, or modifies your shell startup files.
