#!/usr/bin/env bash
# Диагностика связи с сервером: ./deploy/diag.sh  (запустить с VPN и без)
IP="${HOST:-158.160.173.197}"
echo "== $(date '+%H:%M:%S')  внешний IP: $(curl -s --max-time 5 https://api.ipify.org)"
echo "== пинг";        ping -c 3 -t 5 "$IP" | tail -2
for p in 22 80 443; do printf "== TCP %-4s " $p; nc -vz -G 5 "$IP" $p 2>&1 | tail -1; done
echo "== HTTPS";       curl -sk -o /dev/null -w "код %{http_code}, %{time_total}s\n" --max-time 10 "https://$IP/api/health"
echo "== контроль: другой адрес Яндекс.Облака"
printf "   storage.yandexcloud.net:443 "; nc -vz -G 5 storage.yandexcloud.net 443 2>&1 | tail -1
echo "== где обрывается TCP (первые 15 хопов)"
traceroute -P tcp -p 443 -w 2 -q 1 -m 15 "$IP" 2>&1 | tail -16
