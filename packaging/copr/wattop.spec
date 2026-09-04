# Package name is `wattop`, not `python3-wattop`: the Fedora Python guidelines
# reserve the prefix for importable library modules, while packages that
# primarily provide an executable keep their upstream name.
#
# BuildArch: noarch because the wheel is py3-none-any -- no compiled extension.

Name:           wattop
Version:        0.1.0
Release:        1%{?dist}
Summary:        btop-style terminal power monitor

License:        Apache-2.0
URL:            https://github.com/sravanpannala/wattop
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel

%description
A terminal power monitor that reads measured watts: charger in, battery out,
per-rail SoC power, volts and amps, with processor and memory load beside them.

Needs no administrator rights, no kernel driver and no signed helper. On Linux
it reads hwmon, powercap and the power supply class; on Windows it reads the
Energy Meter performance counters and the battery IOCTL.

%prep
%autosetup -n %{name}-%{version}

# Dependencies are read from pyproject.toml rather than hand-listed here, so
# they cannot drift apart from what the package actually imports.
%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l wattop

%check
%pyproject_check_import

%files -f %{pyproject_files}
%doc README.md CHANGELOG.md config.example.toml
# Entry-point scripts are not covered by %%pyproject_files, so list it.
%{_bindir}/wattop

%changelog
* Fri Sep 04 2026 Sravan Pannala <sra.djoker@gmail.com> - 0.1.0-1
- Initial package
