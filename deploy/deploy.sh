#!/usr/bin/env bash
# Деплой/обновление демо на ВМ одной командой с вашего компьютера:
#   ./deploy/deploy.sh                 (по умолчанию HOST=158.160.173.197)
#   HOST=1.2.3.4 ./deploy/deploy.sh
# Копирует код и .env по SSH, ставит зависимости, обновляет systemd-сервис и Caddy (HTTPS).
# ВМ не пересоздаётся, метаданные не нужны. Секреты едут только по SSH из вашего локального .env.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-158.160.173.197}"
USER_="${SSH_USER:-ubuntu}"
KEY="${SSH_KEY:-deploy/voicebot_ssh}"
# По умолчанию сайт открывается прямо по IP (sslip.io из России без VPN часто не резолвится).
# Для своего домена: DOMAIN=voicebot.example.ru ./deploy/deploy.sh
DOMAIN="${DOMAIN:-$HOST}"
# TLS_MODE: self     — свой самоподписанный сертификат на 2 года (по умолчанию; разрешить в браузере один раз);
#           internal — самоподписанный от Caddy (живёт 12 часов и меняется — браузеру придётся разрешать заново);
#           auto     — Let's Encrypt (нужен доступ к ВМ из-за рубежа на 80/443);
#           files    — свой сертификат: положите deploy/certs/cert.pem и deploy/certs/key.pem
TLS_MODE="${TLS_MODE:-self}"
case "$TLS_MODE" in
  self)     TLS_LINE="tls /etc/caddy/certs/self.crt /etc/caddy/certs/self.key" ;;
  internal) TLS_LINE="tls internal" ;;
  auto)     TLS_LINE="" ;;
  files)    TLS_LINE="tls /etc/caddy/certs/cert.pem /etc/caddy/certs/key.pem" ;;
  *) echo "TLS_MODE должен быть self|internal|auto|files"; exit 1 ;;
esac
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new)

chmod 600 "$KEY"
[ -f .env ] || { echo "Нет .env — заполните его по образцу .env.example"; exit 1; }

echo "→ Копирую код на $HOST"
rsync -az --delete \
  --exclude .venv --exclude data --exclude .env --exclude deploy --exclude tests \
  --exclude __pycache__ --exclude .git --exclude mock_log.json \
  -e "ssh ${SSH_OPTS[*]}" ./ "$USER_@$HOST:/tmp/voicebot-src/"
sed "s#__TLS__#$TLS_LINE#" deploy/Caddyfile > /tmp/voicebot.Caddyfile
scp "${SSH_OPTS[@]}" -q deploy/voicebot.service "$USER_@$HOST:/tmp/"
scp "${SSH_OPTS[@]}" -q /tmp/voicebot.Caddyfile "$USER_@$HOST:/tmp/Caddyfile"
if [ "$TLS_MODE" = files ]; then
  ssh "${SSH_OPTS[@]}" "$USER_@$HOST" 'mkdir -p /tmp/vbcerts'
  scp "${SSH_OPTS[@]}" -q deploy/certs/cert.pem deploy/certs/key.pem "$USER_@$HOST:/tmp/vbcerts/"
fi
{ cat .env; printf '\nPUBLIC_BASE_URL=https://%s\n' "$DOMAIN"; } | ssh "${SSH_OPTS[@]}" "$USER_@$HOST" 'cat > /tmp/voicebot.env'

echo "→ Устанавливаю и перезапускаю сервисы"
ssh "${SSH_OPTS[@]}" "$USER_@$HOST" "sudo DOMAIN=$DOMAIN bash -s" <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
mkdir -p /opt/voicebot
rsync -a --delete --exclude .venv --exclude data --exclude .env /tmp/voicebot-src/ /opt/voicebot/
install -m 600 /tmp/voicebot.env /opt/voicebot/.env && rm -f /tmp/voicebot.env
[ -x /opt/voicebot/.venv/bin/uvicorn ] || python3 -m venv /opt/voicebot/.venv
/opt/voicebot/.venv/bin/pip install -q -r /opt/voicebot/requirements.txt
command -v caddy >/dev/null || { apt-get update -q; apt-get install -y -q caddy; }

# убираем самодельный юнит caddy от первой попытки — используем штатный из пакета
rm -f /etc/systemd/system/caddy.service /etc/systemd/system/multi-user.target.wants/caddy.service
mkdir -p /var/lib/caddy && chown -R caddy:caddy /var/lib/caddy   # хранилище сертификатов должно принадлежать caddy
# свой самоподписанный сертификат: создаём один раз (или если сменился адрес) — 2 года без замены
if grep -q "/etc/caddy/certs/self.crt" /tmp/Caddyfile; then
  mkdir -p /etc/caddy/certs
  if ! openssl x509 -in /etc/caddy/certs/self.crt -noout -ext subjectAltName 2>/dev/null | grep -q "$DOMAIN"; then
    if [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then SAN="IP:$DOMAIN"; else SAN="DNS:$DOMAIN"; fi
    openssl req -x509 -newkey rsa:2048 -nodes -days 730 -subj "/CN=$DOMAIN" -addext "subjectAltName=$SAN" \
      -keyout /etc/caddy/certs/self.key -out /etc/caddy/certs/self.crt 2>/dev/null
    echo "Создан новый самоподписанный сертификат для $DOMAIN (действует 2 года)"
  fi
  chown -R caddy:caddy /etc/caddy/certs && chmod 600 /etc/caddy/certs/self.key
fi
if [ -d /tmp/vbcerts ]; then
  mkdir -p /etc/caddy/certs && install -o caddy -g caddy -m 600 /tmp/vbcerts/*.pem /etc/caddy/certs/ && rm -rf /tmp/vbcerts
fi
sed "s/__DOMAIN__/$DOMAIN/" /tmp/Caddyfile > /etc/caddy/Caddyfile
install -m 644 /tmp/voicebot.service /etc/systemd/system/voicebot.service
systemctl daemon-reload

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable -q voicebot caddy
systemctl restart voicebot
if ! systemctl restart caddy; then
  echo "!!! Caddy не запустился:"; journalctl -u caddy -n 40 --no-pager; exit 1
fi
systemctl is-active voicebot caddy
REMOTE

echo "→ Проверяю https://$DOMAIN (первый выпуск сертификата может занять до минуты)"
CURL_K=""; { [ "$TLS_MODE" = internal ] || [ "$TLS_MODE" = self ]; } && CURL_K="-k"
for i in $(seq 1 12); do
  if curl -fsS $CURL_K "https://$DOMAIN/api/health"; then echo; echo "✓ Готово: https://$DOMAIN"; exit 0; fi
  sleep 5
done
echo "HTTPS пока не отвечает. Логи: ssh ${SSH_OPTS[*]} $USER_@$HOST 'sudo journalctl -u caddy -n 50 --no-pager'"
exit 1
