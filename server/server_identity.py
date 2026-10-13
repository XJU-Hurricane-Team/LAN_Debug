"""Read the server's Avahi name without changing its configuration or state."""
import configparser
import json
import re
import socket
import subprocess


def _valid_hostname(name):
    return bool(name and len(name) <= 253 and all(
        re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
        for label in name.split('.')))


def _avahi_call(method):
    result = subprocess.run(
        ['busctl', '--system', 'call', 'org.freedesktop.Avahi', '/',
         'org.freedesktop.Avahi.Server', method],
        capture_output=True, text=True, timeout=1, check=True,
    )
    return result.stdout.strip()


def get_server_identity(config_path='/etc/avahi/avahi-daemon.conf'):
    try:
        # RUNNING == 2; a configured name may differ after collision handling.
        if _avahi_call('GetState') == 'i 2':
            reply = _avahi_call('GetHostNameFqdn')
            name = json.loads(reply[2:]) if reply.startswith('s ') else ''
            if isinstance(name, str) and _valid_hostname(name):
                return {'name': name, 'source': 'avahi-runtime'}
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    config = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        config.read(config_path, encoding='utf-8')
        if config.has_section('server'):
            if config.getboolean('server', 'host-name-from-machine-id', fallback=False):
                return {'name': '', 'source': 'unavailable'}
            host = config.get('server', 'host-name', fallback='').strip()
            host = host or socket.gethostname().split('.')[0]
            domain = config.get('server', 'domain-name', fallback='local').strip()
            name = f'{host}.{domain}'
            if _valid_hostname(name):
                return {'name': name, 'source': 'avahi-config'}
    except (OSError, configparser.Error, ValueError):
        pass
    return {'name': '', 'source': 'unavailable'}
