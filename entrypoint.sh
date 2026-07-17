#!/bin/sh
/usr/local/bin/generate-nginx-upstream.sh
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
