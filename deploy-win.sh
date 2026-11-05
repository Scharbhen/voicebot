#!/usr/bin/env bash
# Деплой на Windows-сервер одной командой (с Мака):
#   ./deploy-win.sh            собрать код, отправить, обновить, перезапустить, проверить
#   ./deploy-win.sh rollback   вернуть предыдущую версию
#   ./deploy-win.sh status     состояние и последние строки лога
#   ./deploy-win.sh logs       лог в реальном времени (Ctrl+C — выход)
#   ./deploy-win.sh key        показать ключ для deploy\windows\enable-ssh.ps1 (создаст, если нет)
# Настройки — в deploy/windows/target.env (создаётся при первом запуске).
set -euo pipefail
cd "$(dirname "$0")"
CFG=deploy/windows/target.env
if [ ! -f "$CFG" ]; then
  cat > "$CFG" <<'CFGEOF'
# Куда деплоить
WIN_HOST=gpuwinsrv01.domain.corp
# Пользователь Windows (администратор сервера). Для доменной учётки: user@domain.corp
WIN_USER=
# Папка проекта на сервере
WIN_DIR=C:/voicebot
CFGEOF
fi
# shellcheck disable=SC1090
source "$CFG"
KEY="$HOME/.ssh/id_ed25519"
cmd="${1:-deploy}"

if [ "$cmd" = "key" ]; then
  [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -f "$KEY" -C "voicebot-deploy"
  echo "Скопируйте строку ниже и на сервере выполните (PowerShell от администратора, в $WIN_DIR):"
  echo "  powershell -ExecutionPolicy Bypass -File deploy\\windows\\enable-ssh.ps1 -PublicKey \"$(cat "$KEY.pub")\""
  exit 0
fi

[ -n "${WIN_USER:-}" ] || { echo "Впишите WIN_USER в $CFG"; exit 1; }
TARGET="$WIN_USER@$WIN_HOST"
WINDIR_BS="${WIN_DIR//\//\\}"
SSH=(ssh -o ConnectTimeout=10 -o BatchMode=yes "$TARGET")
ps() { "${SSH[@]}" "powershell -NoProfile -ExecutionPolicy Bypass -File $WINDIR_BS\\deploy\\windows\\$1"; }

case "$cmd" in
  deploy)
    TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
    echo "→ Собираю архив"
    zip -qr "$TMP/update.zip" app static kb scripts requirements.txt .env.example README.md deploy/windows \
      -x '*__pycache__*' '*.pyc' 'deploy/windows/serve.cmd' 'deploy/windows/target.env' '*.DS_Store'
    echo "→ Отправляю на $WIN_HOST"
    scp -q -o ConnectTimeout=10 -o BatchMode=yes "$TMP/update.zip" "$TARGET:$WIN_DIR/update.zip"
    # update.ps1 берём свежий из архива — на случай, если он сам изменился
    "${SSH[@]}" "powershell -NoProfile -Command \"Expand-Archive -Force $WINDIR_BS\\update.zip $WINDIR_BS\\data\\_upd; Copy-Item -Force $WINDIR_BS\\data\\_upd\\deploy\\windows\\update.ps1 $WINDIR_BS\\deploy\\windows\\update.ps1; Remove-Item -Recurse -Force $WINDIR_BS\\data\\_upd\""
    ps "update.ps1 -Zip $WINDIR_BS\\update.zip"
    ;;
  rollback) ps "update.ps1 -Rollback" ;;
  status)   ps "voicebot.ps1 status" ;;
  logs)     ssh -t "$TARGET" "powershell -NoProfile -Command Get-Content $WINDIR_BS\\data\\server.log -Tail 50 -Wait" ;;
  *) echo "Команды: deploy | rollback | status | logs | key"; exit 1 ;;
esac
