"""Rendering a MachineConfig into NixOS configuration text.

A pure function over text, so it is tested directly: the output either is valid Nix
expressing the right options, or a machine fails to rebuild.
"""

import pytest

from nixync_client.nix import InvalidPackageName, render
from nixync_client.protocol import LocalUser, MachineConfig, SystemSettings


def test_an_empty_config_still_renders_a_valid_module():
    """A machine nobody has configured must not produce a broken file."""
    text = render(MachineConfig())

    # A NixOS module is a function of its arguments, then an attribute set. The file
    # opens with a comment, so check the module shape rather than the first character.
    assert "{ config, lib, pkgs, ... }:" in text
    assert text.rstrip().endswith("}")
    assert text.count("{") == text.count("}"), "braces balance"
    assert "environment.systemPackages" in text


def test_packages_are_rendered_as_a_pkgs_list():
    text = render(MachineConfig(packages=["git", "htop"]))

    assert "environment.systemPackages = with pkgs; [ git htop ];" in text


def test_packages_keep_the_order_they_were_given():
    """The server already sorts them; re-sorting here would hide a real diff."""
    text = render(MachineConfig(packages=["zsh", "atop"]))

    assert "[ zsh atop ]" in text


def test_a_package_name_that_could_inject_nix_is_rejected():
    """The server is unauthenticated in this MVP, so a bad name is hostile or a typo."""
    with pytest.raises(InvalidPackageName, match="git; evil"):
        render(MachineConfig(packages=["git; evil"]))


@pytest.mark.parametrize("name", ['a"b', "a b", "a$b", "a\nb", "${x}", "../etc"])
def test_package_names_are_validated_not_escaped(name):
    with pytest.raises(InvalidPackageName):
        render(MachineConfig(packages=[name]))


@pytest.mark.parametrize("name", ["git", "python3.13", "foo-bar", "foo_bar", "gcc14"])
def test_ordinary_nixpkgs_names_are_accepted(name):
    assert name in render(MachineConfig(packages=[name]))


def test_settings_are_rendered_as_nixos_options():
    text = render(
        MachineConfig(
            settings=SystemSettings(
                hostname="lab-05",
                timezone="Europe/London",
                firewall=True,
                open_tcp_ports=[22, 80],
                ssh=True,
                ssh_root_login="prohibit-password",
                docker=True,
            )
        )
    )

    # Scalars carry lib.mkDefault so they cannot clash with the machine's own
    # configuration; see test_scalar_settings_are_emitted_as_defaults.
    assert 'networking.hostName = lib.mkDefault "lab-05";' in text
    assert 'time.timeZone = lib.mkDefault "Europe/London";' in text
    assert "networking.firewall.enable = lib.mkDefault true;" in text
    assert "networking.firewall.allowedTCPPorts = [ 22 80 ];" in text, "lists merge"
    assert "services.openssh.enable = lib.mkDefault true;" in text
    assert (
        'services.openssh.settings.PermitRootLogin = lib.mkDefault "prohibit-password";'
    ) in text
    assert "virtualisation.docker.enable = lib.mkDefault true;" in text


def test_booleans_render_as_nix_booleans_not_python_ones():
    """"True" is not valid Nix."""
    text = render(MachineConfig(settings=SystemSettings(firewall=False, docker=False)))

    assert "networking.firewall.enable = lib.mkDefault false;" in text
    assert "True" not in text and "False" not in text


def test_users_become_user_accounts():
    text = render(
        MachineConfig(
            settings=SystemSettings(
                users=[
                    LocalUser(name="ann", full_name="Ann Smith", admin=True),
                    LocalUser(name="bob"),
                ]
            )
        )
    )

    assert "users.users.ann" in text
    assert 'description = "Ann Smith";' in text
    assert '"wheel"' in text, "an admin is in the wheel group"
    assert "users.users.bob" in text


def test_a_non_admin_user_is_not_in_wheel():
    text = render(MachineConfig(settings=SystemSettings(users=[LocalUser(name="bob")])))

    bob = text[text.index("users.users.bob"):]
    assert "wheel" not in bob.split("};")[0]


def test_no_password_value_ever_reaches_the_rendered_nix():
    """Passwords are set on the device and hashed there. This is a hard boundary.

    Checked against the NixOS options that would carry one — the bare word "password"
    also appears in `services.openssh.settings.PasswordAuthentication`, which is an
    SSH toggle, not a secret.
    """
    text = render(
        MachineConfig(settings=SystemSettings(users=[LocalUser(name="ann", admin=True)]))
    )

    for option in ("hashedPassword", "initialPassword", "passwordFile", "initialHashedPassword"):
        assert option not in text


def test_a_username_that_could_inject_nix_is_rejected():
    with pytest.raises(InvalidPackageName):
        render(MachineConfig(settings=SystemSettings(users=[LocalUser(name="ann; evil")])))


def test_a_config_with_no_settings_renders_only_packages():
    text = render(MachineConfig(packages=["git"]))

    assert "git" in text
    assert "networking.hostName" not in text, "nothing was configured, so claim nothing"


def test_an_empty_hostname_is_omitted_rather_than_set_to_nothing():
    """`networking.hostName = ""` is a real setting and not what anyone meant."""
    text = render(MachineConfig(settings=SystemSettings(hostname="")))

    assert "networking.hostName" not in text


def test_the_output_says_it_is_generated():
    """Someone will find this file on a machine and wonder where it came from."""
    assert "Nixync" in render(MachineConfig())


def test_the_output_parses_as_real_nix(tmp_path):
    """The strongest check available: hand it to Nix itself.

    Every other test here matches substrings, which cannot tell valid Nix from a
    plausible-looking string. Skipped where the Nix tooling is not installed.
    """
    import shutil
    import subprocess

    if not shutil.which("nix-instantiate"):
        pytest.skip("nix-instantiate is not installed")

    config = MachineConfig(
        packages=["git", "htop"],
        settings=SystemSettings(
            hostname="lab-05",
            nameservers=["9.9.9.9"],
            open_tcp_ports=[22, 80],
            users=[
                LocalUser(name="ann", full_name='Ann "Quote" Smith', admin=True),
                LocalUser(name="bob"),
            ],
        ),
    )
    path = tmp_path / "nixync.nix"
    path.write_text(render(config))

    result = subprocess.run(
        ["nix-instantiate", "--parse", str(path)], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "config",
    [
        MachineConfig(),
        MachineConfig(packages=["git"]),
        MachineConfig(settings=SystemSettings(hostname="h")),
        MachineConfig(settings=SystemSettings(users=[LocalUser(name="ann")])),
    ],
    ids=["empty", "packages-only", "settings-no-users", "users-only"],
)
def test_every_shape_of_config_parses_as_nix(config, tmp_path):
    import shutil
    import subprocess

    if not shutil.which("nix-instantiate"):
        pytest.skip("nix-instantiate is not installed")

    path = tmp_path / "nixync.nix"
    path.write_text(render(config))

    result = subprocess.run(
        ["nix-instantiate", "--parse", str(path)], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr


# -- coexisting with a machine's own configuration --------------------------


def test_scalar_settings_are_emitted_as_defaults():
    """NixOS refuses two definitions of a scalar option, even identical ones.

    Emitting these bare broke a real machine: its configuration.nix already set
    nixpkgs.config.allowUnfree, so every rebuild failed once nixync.nix was imported.
    """
    text = render(MachineConfig(settings=SystemSettings(hostname="lab-05")))

    for option in (
        "networking.hostName",
        "networking.firewall.enable",
        "time.timeZone",
        "services.openssh.enable",
        "services.openssh.settings.PasswordAuthentication",
        "services.openssh.settings.PermitRootLogin",
        "hardware.bluetooth.enable",
        "services.pipewire.enable",
        "virtualisation.docker.enable",
        "nixpkgs.config.allowUnfree",
    ):
        line = next(l for l in text.splitlines() if l.strip().startswith(option))
        assert "lib.mkDefault" in line, f"{option} would conflict with an existing config"


def test_packages_are_not_forced_so_they_add_to_what_the_machine_has():
    """systemPackages is a list: lists merge, so the operator keeps their own."""
    text = render(MachineConfig(packages=["git"]))

    packages = next(l for l in text.splitlines() if "systemPackages" in l)
    assert "mkDefault" not in packages


def test_lib_is_in_scope_for_mkdefault():
    """Using lib.mkDefault without taking lib as a module argument is a Nix error."""
    assert "{ config, lib, pkgs, ... }:" in render(MachineConfig())


def test_the_module_coexists_with_a_configuration_that_sets_the_same_options(tmp_path):
    """Evaluated by the Nix module system, which is what rejected the old output."""
    import shutil
    import subprocess

    if not shutil.which("nix-instantiate"):
        pytest.skip("nix-instantiate is not installed")

    (tmp_path / "theirs.nix").write_text(
        "{ config, pkgs, ... }:\n"
        '{ nixpkgs.config.allowUnfree = true;\n  networking.hostName = "their-box"; }\n'
    )
    (tmp_path / "nixync.nix").write_text(
        render(MachineConfig(settings=SystemSettings(hostname="lab-05")))
    )
    (tmp_path / "eval.nix").write_text(
        "let pkgs = import <nixpkgs> {}; lib = pkgs.lib;\n"
        "  r = lib.evalModules { specialArgs = { pkgs = pkgs; }; modules = [\n"
        "    { options.networking.hostName = lib.mkOption { type = lib.types.str; default = \"\"; };\n"
        "      options.nixpkgs.config.allowUnfree = lib.mkOption { type = lib.types.bool; default = false; };\n"
        "      options.networking.nameservers = lib.mkOption { type = lib.types.listOf lib.types.str; default = []; };\n"
        "      options.networking.firewall.enable = lib.mkOption { type = lib.types.bool; default = true; };\n"
        "      options.networking.firewall.allowedTCPPorts = lib.mkOption { type = lib.types.listOf lib.types.int; default = []; };\n"
        "      options.time.timeZone = lib.mkOption { type = lib.types.str; default = \"UTC\"; };\n"
        "      options.services.openssh.enable = lib.mkOption { type = lib.types.bool; default = false; };\n"
        "      options.services.openssh.settings.PasswordAuthentication = lib.mkOption { type = lib.types.bool; default = true; };\n"
        "      options.services.openssh.settings.PermitRootLogin = lib.mkOption { type = lib.types.str; default = \"no\"; };\n"
        "      options.hardware.bluetooth.enable = lib.mkOption { type = lib.types.bool; default = false; };\n"
        "      options.services.pipewire.enable = lib.mkOption { type = lib.types.bool; default = false; };\n"
        "      options.virtualisation.docker.enable = lib.mkOption { type = lib.types.bool; default = false; };\n"
        "      options.environment.systemPackages = lib.mkOption { type = lib.types.listOf lib.types.package; default = []; };\n"
        "      options.users.users = lib.mkOption { type = lib.types.attrs; default = {}; }; }\n"
        "    ./theirs.nix ./nixync.nix ];\n"
        "  };\n"
        "in r.config.networking.hostName\n"
    )

    result = subprocess.run(
        ["nix-instantiate", "--eval", "--strict", str(tmp_path / "eval.nix")],
        capture_output=True, text=True, cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "their-box" in result.stdout, "the machine's own setting wins over mkDefault"
