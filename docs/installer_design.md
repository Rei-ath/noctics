# Adaptive Installer Design

## Goals
- Ship a single bootstrap executable or script that installs Noctics on the
  user's machine regardless of OS/architecture.
- Detect host platform and fetch the matching prebuilt payload (PyInstaller
  bundle or wheel) from the release CDN.
- Place binaries and models in the appropriate per-user location and expose the
  `noctics` CLI via the system PATH.
- Persist a global configuration file so the runtime can discover defaults
  without extra commands.
- On first launch, trigger the instrument wizard (handled separately).

## Supported Targets (Initial)
- Linux x86_64 (PyInstaller bundle)
- Linux arm64 (PyInstaller bundle)
- macOS arm64 (PyInstaller bundle)
- Windows x86_64 (PyInstaller bundle)
- Optional: universal source wheel fallback when no bundle is available.

## Quick start (binary install)
```bash
curl -fsSL https://raw.githubusercontent.com/noctics/noctics/main/installer/noctics | bash
noctics --setup
```

The helper pulls `bootstrap.py` directly from GitHub, downloads the manifest
(`https://github.com/noctics/noctics/releases/latest/download/installer_manifest.json`),
detects the host GPU VRAM, and selects the most appropriate bundle (defaults to
`nano` on machines without a discrete GPU). Add the printed shim directory to
`PATH`, then either complete the wizard or set
`OPENAI_API_KEY`/`NOCTICS_SECRETS_FILE` ahead of time to skip it.

## Artifact Layout
- Publish compressed archives per target:
  - `noctics-core-linux-x86_64.tar.gz`
  - `noctics-core-linux-arm64.tar.gz`
  - `noctics-core-macos-arm64.zip`
  - `noctics-core-windows-x86_64.zip`
- Each archive contains:
  - `noctics-core` launcher (or `noctics-core.exe` on Windows)
  - `_internal/` payload (PyInstaller assets)
  - `licenses/THIRD_PARTY_LICENSES.md`
  - `README.txt` with quick instructions
- SHA256 manifest published alongside each archive.

## Bootstrapper Responsibilities
1. **Platform Detection**
   - Use Python's `platform` module (preferred) or a small Go/Rust binary to
     detect OS (`linux`, `darwin`, `windows`) and architecture (`x86_64`,
     `arm64`).
   - Map detection to artifact slug (e.g. `linux-x86_64`).

2. **Download & Verify**
   - Fetch archive URL (configurable via release metadata or JSON manifest).
   - Validate SHA256 sum against the published manifest before extraction.

3. **Installation Layout**
   - Default root: `~/.local/share/noctics` (Linux),
     `~/Library/Application Support/Noctics` (macOS),
     `%APPDATA%\Noctics` (Windows).
   - Extract archive contents into `runtime/` subdirectory.
   - Symlink or copy launcher to `~/.local/bin/noctics` (Linux/macOS) or create a
     shim batch file in `%USERPROFILE%\AppData\Local\Microsoft\WindowsApps`.

4. **Global Config**
   - Write `config/noctics.toml` with keys:
     ```toml
     [runtime]
     install_root = "<resolved path>"
     binary = "<path to launcher>"
     model = "centi-nox"

     [instrument]
     provider = ""
     api_key_path = ""
     ```
   - Expose location via env var `NOCTICS_CONFIG_HOME` pointing to the config
     directory.

5. **Post-install Hooks**
   - Print next steps and how to run `noctics-core` or `noctics tui`.
   - Optionally trigger first launch automatically (`noctics-core --setup`).

## Distribution Steps
1. Run `./scripts/build_release.sh` (or the model-specific variants) on the
   target platform. When the build succeeds the helper now invokes
   `scripts/package_installer_artifacts.py` to emit the installer archive and
   refresh the manifest.
2. Collect the generated files under `dist/`:
   - `noctics-core-<slug>.tar.gz` or `.zip` depending on the platform.
   - `installer_manifest.json` with per-slug metadata. Entries may contain a
     `variants` object (e.g. `nano`, `micro`, `centi`) so the bootstrapper can
     select the right bundle after VRAM detection. Each variant records
     `url`, `sha256`, archive `size`, the bundle `version`, and an optional
     `build` identifier (commit hash or CI build number).
   - `noctics-core.SHA256SUMS` for in-archive checksums (existing step).
3. Upload the archive(s) and manifest to release storage (GitHub Releases, S3,
   or your CDN). Set `NOCTICS_INSTALLER_URL_PREFIX` when rebuilding to pre-bake
   CDN URLs into the manifest.
4. Bootstrapper downloads this manifest to locate the correct asset:
   ```json
{
  "linux-x86_64": {
    "default": "nano",
    "variants": {
      "nano": {
        "url": "https://github.com/noctics/noctics/releases/download/v0.1.39/noctics-core-nano-linux-x86_64.tar.gz",
        "sha256": "…",
        "size": 123456789,
        "version": "0.1.39",
        "build": "abc1234"
      },
      "micro": {
        "url": "https://github.com/noctics/noctics/releases/download/v0.1.39/noctics-core-micro-linux-x86_64.tar.gz",
        "sha256": "…",
        "size": 234567890,
        "version": "0.1.39",
        "build": "abc1234"
      }
    }
  }
}
   ```

### Packaging knobs
- `NOCTICS_SKIP_INSTALLER_PACKAGING=1` – disable archive creation during the build.
- `NOCTICS_INSTALLER_SLUG`, `NOCTICS_INSTALLER_OS`, `NOCTICS_INSTALLER_ARCH` –
  override host detection when cross-packaging.
- `NOCTICS_INSTALLER_ARCHIVE_PREFIX` – change the filename stem (default:
  `noctics-core`).
- `NOCTICS_INSTALLER_MANIFEST` – explicit path for installer manifest output
  (defaults to `dist/installer_manifest.json`).
- `NOCTICS_INSTALLER_URL_PREFIX` – prefix appended to artifact names when
  writing manifest URLs.
- `NOCTICS_INSTALLER_ARTIFACT_URL` – full URL override for situations where the
  CDN path is not derived from the filename.
- `NOCTICS_INSTALLER_README_TEMPLATE` – path to a template used when the build
  needs to regenerate `README.txt`.
- `NOCTICS_INSTALLER_VERSION` – override the detected runtime version for
  manifest entries and README placeholders.
- `NOCTICS_INSTALLER_BUILD` – supply a CI build id or git hash recorded in the
  manifest for traceability.

The autogenerated `README.txt` accepts a `{VERSION}` placeholder that resolves
to the detected or overridden version.

Manual packaging remains available:

```bash
python scripts/package_installer_artifacts.py \
  --dist-dir dist/noctics-core \
  --url-prefix https://github.com/noctics/noctics/releases/download/v0.1.39 \
  --version 0.1.39 \
  --variant nano
```

## Validation workflow
1. Build and package: `./scripts/build_release.sh`.
2. Confirm archives: `ls dist/noctics-core-*.{tar.gz,zip}` and inspect the
   manifest entries inside `dist/installer_manifest.json`.
3. Dry run the bootstrapper against the local manifest:
   ```bash
   python installer/bootstrap.py --manifest dist/installer_manifest.json --slug "$(python - <<'PY'\nimport platform, sys\nos_name = 'macos' if sys.platform == 'darwin' else ('windows' if sys.platform in ('win32', 'cygwin') else 'linux')\narch = platform.machine().lower()\nprint(f\"{os_name}-{arch}\")\nPY)"
   ```
   Use `--force` to validate repeated installs.
4. Launch the installed shim (`~/.local/bin/noctics` on Linux/macOS) and run
   `noctics --setup` to make sure the instrument wizard appears when no
   provider is configured.

## Telemetry follow-up
The bootstrapper records a local install heartbeat that captures version, slug,
build id, and timestamp inside `memory/telemetry/metrics.json`. The next phase
is wiring a periodic runtime ping (once the telemetry service ships) so both
installer flows and in-app usage share anonymised counts.

## Prototype
- Script: `python installer/bootstrap.py --manifest <url-or-path>`
- Options:
  - `--slug` overrides auto-detected platform (for testing).
  - `--force` removes any existing installation before unpacking the new
    runtime.

## Open Questions
- Where to host the archives (private CDN vs GitHub).
- Whether to ship an installer per platform (MSI/pkg) in addition to the
  bootstrapper.
- Handling GPU-specific model variants (optional download step post install).
