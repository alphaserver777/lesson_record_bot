# Фрагмент Для Nix Dev Shell

Добавьте следующие части в `/home/admsys/Nixos/nixos-config/flake.nix`.

## 1. Добавить `pkgs` внутри `let`

```nix
    pkgs = import nixpkgs {
      inherit system;
      config.allowUnfree = true;
    };
```

## 2. Добавить dev shell в итоговый output attrset

```nix
    devShells.${system}.lesson-record-bot = pkgs.mkShell {
      packages = with pkgs; [
        python311
        uv
        nodejs_20
        sqlite
        git
        gcc
        gnumake
        pkg-config
      ];

      shellHook = ''
        export PROJECT_ROOT=/home/admsys/lesson_record_bot
        export PYTHONDONTWRITEBYTECODE=1
        export PIP_DISABLE_PIP_VERSION_CHECK=1
        export npm_config_update_notifier=false

        echo "lesson-record-bot dev shell"
        echo "project: $PROJECT_ROOT"
        echo "python: $(python --version 2>&1)"
        echo "node: $(node --version 2>&1)"
      '';
    };
```

## Использование

```bash
nix develop /home/admsys/Nixos/nixos-config#lesson-record-bot
cd /home/admsys/lesson_record_bot
uv pip install -r requirements.txt
cd miniapp && npm install
```
