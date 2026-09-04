# Packaging

wattop ships as **one `py3-none-any` wheel**. There is no compiled extension
anywhere in the tree, so the same file serves Windows x64 and ARM64, Linux
x86-64 and aarch64. Nothing here needs a per-platform build matrix, and nothing
here needs a frozen binary.

Every channel below is one the maintainer owns and can publish to alone. Getting
into the Debian, Ubuntu or Fedora archives is deliberately not attempted: those
need a sponsor and a release cycle, and the recipes here reach the same users
sooner.

## Status

| Channel | Recipe | Tested |
|---|---|---|
| PyPI | `pyproject.toml` | wheel and sdist build; `twine check` passes |
| AUR | `aur/PKGBUILD` | **built and installed with `makepkg` on Arch**, ran from system Python |
| Fedora COPR | `copr/wattop.spec` | **built, installed and ran in a `fedora:44` container** |
| Scoop | `scoop/wattop.json` | zipapp runs on Windows ARM64 and Linux; install script verified |
| openSUSE Build Service | not written | — |

## PyPI

The release workflow publishes on a `v*` tag through Trusted Publishing, so
there is no API token to store. It has to be configured once, by hand, at
<https://pypi.org/manage/project/wattop/settings/publishing/>:

* Owner `sravanpannala`, repository `wattop`
* Workflow `release.yml`, environment `pypi`

## AUR

Package name is `wattop`, not `python-wattop`: the Arch guidelines reserve that
prefix for library modules and for tools coupled to the Python ecosystem.

```console
$ git clone ssh://aur@aur.archlinux.org/wattop.git
$ cp packaging/aur/PKGBUILD wattop/ && cd wattop
$ updpkgsums && makepkg --printsrcinfo > .SRCINFO
$ git add PKGBUILD .SRCINFO && git commit -m "initial import" && git push
```

Pushes go to `master`, and a missing or malformed `.SRCINFO` is rejected by the
server. That is the only gate; there is no review and no star threshold.

Every dependency is already in Arch `extra`, at versions matching the lockfile.

## Fedora COPR

No quality bar, no sponsor, aarch64 available with no request.

```console
$ copr-cli create wattop --chroot fedora-44-x86_64 --chroot fedora-44-aarch64 \
                          --chroot fedora-45-x86_64 --chroot fedora-rawhide-x86_64
$ copr-cli build wattop dist/wattop-0.1.0.tar.gz
```

Then wire the GitHub webhook for automatic rebuilds. **The tag-name catch:**
COPR's tag trigger expects `PKGNAME-VERSION`, but the tags here are `v0.1.0`
because that is what the AUR recipe and the release workflow use. Append the
package name to the webhook URL to bypass the pattern rather than changing the
tag convention.

Skip EPEL: its Python is older than the 3.11 floor.

End users type:

```console
$ sudo dnf copr enable sravanpannala/wattop && sudo dnf install wattop
```

## Scoop

Publish `scoop/wattop.json` to a personal bucket. The official buckets want
several hundred stars; a bucket you own has no gate at all.

```console
$ scoop bucket add sravanpannala https://github.com/sravanpannala/scoop-bucket
$ scoop install wattop
```

The artifact is `wattop.pyz`, a zipapp built by the release workflow. It is
about 3 MB, contains only Python, and runs on every processor Scoop supports
from one file, so the manifest needs no per-processor block. It is not a frozen
binary: nothing is compiled, and there is no bootloader for a virus scanner to
object to, which is what makes the Windows packaging channels straightforward.

`packaging/scoop/stamp.py` writes the version and hash into the manifest during
a release, so updating the bucket is copying one file.

## What is deliberately skipped

* **Debian, Ubuntu and Fedora archives** — sponsor-gated, months of latency.
  A `.deb` or `.rpm` attached to a GitHub release reaches the same people. The
  one real argument for building them later is that a package can ship a udev
  rule granting read access to Intel RAPL, which `energy_uj` denies to
  non-root since the PLATYPUS mitigation; a `pip install` cannot do that.
* **Homebrew core** — needs 225 stars for a self-submission plus a macOS CI
  pass, and macOS is not supported.
* **Flathub** — rejects console software by written policy.
* **Snap** — the default confinement grants directory listing but not file
  reads under `/sys/class`, so wattop would enumerate every sensor and display
  zeros. `hardware-observe` fixes it but does not auto-connect, which turns
  installation into three commands.
* **WinGet** — no notability bar, but it requires a hashed installer, and a
  zipapp is not one.
