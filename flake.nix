{
  description = "Toolkit for preprocessing, aligning, rendering, and naming rhythm-game video recordings across external and direct device captures.";

  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pre-commit-hooks.url = "github:cachix/git-hooks.nix";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [
        inputs.pre-commit-hooks.flakeModule
      ];
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          system,
          ...
        }:
        {
          pre-commit.settings = {
            src = ./.;
            hooks = {
              nixfmt-rfc-style.enable = true;
              ruff.enable = true;
              ruff-format.enable = true;
            };
          };
          devShells = {
            default = pkgs.mkShellNoCC {
              buildInputs = with pkgs; [
                ffmpeg
                mlt
                python314
                uv
                pythonManylinuxPackages.manylinux2014Package
              ];
              NIX_LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
                pkgs.stdenv.cc.cc
                pkgs.pythonManylinuxPackages.manylinux2014Package
              ];
              NIX_LD = builtins.readFile "${pkgs.stdenv.cc}/nix-support/dynamic-linker";

              shellHook = ''
                # install pre-commit hooks
                ${config.pre-commit.installationScript}

                uv venv --allow-existing
                . .venv/bin/activate
                uv sync
              '';
            };
          };
        };
    };
}
