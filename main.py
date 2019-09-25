import os
import threading
import time
from base64 import b64decode
from datetime import timedelta

import netaddr
import tenable.errors
from tenable.sc import TenableSC

from config import validate_config_file
from getkey import getKey
from term_colors import color as c


def main():
    config, err = validate_config_file('config.ini')

    if config:
        config_to_lower = {}
        for items in config:
            config_to_lower[items.lower()] = items

        url = config[config_to_lower['securitycenter']]['hostname']
        username = config[config_to_lower['user']]['username']
        try:
            password = b64decode(config[config_to_lower['user']]['password64']).decode('utf-8')
        except:
            password = config[config_to_lower['user']]['password']

        del config_to_lower, config, err
    else:
        raise err

    start = time.time()
    connected = False
    SC = None

    while time.time() < start + 60:
        import logging
        try:
            logging.getLogger().setLevel(logging.NOTSET)
            print(f"Looking for SecurityCenter at: '{url}' ... ", end='')
            SC = TenableSC(url)
            print('Found.')
            print(f"Attempting to log in as: '{username}' ... ", end='')
            SC.login(user=username, passwd=password)
            if 'X-SecurityCenter' in SC._session.headers.keys():
                print('Logged In.')
                connected = True
                del username, password
                break
            else:
                print("")
        except tenable.errors.ConnectionError as err:
            print(f'{err.msg}\tRetrying for {round(start + 60 - time.time())} more seconds.')
            time.sleep(2)
        except tenable.errors.APIError as err:
            print(err.response.json()['error_msg'])
            break
        except Exception as err:
            raise err
        finally:
            logging.getLogger().setLevel(logging.WARNING)

    if not connected:
        print(f'Unable to connect to {url}')
        if isinstance(SC, tenable.sc.TenableSC) and 'X-SecurityCenter' in SC.session.headers:
            SC.logout()
        exit(1)

    del url

    def loop():
        global exit_loop
        while True:
            key = getKey()
            if key == 'q':
                with threading.Lock():
                    exit_loop = True
                    print('Quitting ...')
                    break

    thread = threading.Thread(name='GetKey Thread', target=loop, daemon=True)
    display = None

    thread.start()
    global exit_loop
    exit_loop = False
    while True:
        current_loop = time.time()
        if display:
            os.system('cls' if os.name == 'nt' else 'clear')
            print(display, end='\r\n')
            print("Press 'q' to quit.", end='\r\n')
        display_updated = False

        while time.time() < current_loop + 5:
            if not display_updated:
                if not exit_loop:
                    running_scans = SC.get('scanResult?filter=running&fields=id').json()['response']['manageable']
                if not exit_loop:
                    try:
                        running_scans = [SC.scan_instances.details(int(scan_id['id'])) for scan_id in running_scans]
                    except tenable.errors.APIError:
                        running_scans = []
                if not exit_loop:
                    for index in range(len(running_scans)):
                        try:
                            running_scans[index]['scan'] = SC.scans.details(running_scans[index]['scan']['id'])
                        except tenable.errors.APIError:
                            pass
                if not exit_loop:
                    display = all_scans_display(running_scans=running_scans)
                    display_updated = True
            if exit_loop:
                if 'X-SecurityCenter' in SC._session.headers:
                    SC.logout()
                    exit()


def all_scans_display(running_scans) -> str:
    display = ''

    for scan in running_scans:
        # --- DISPLAY SCAN HEADER BAR ---
        progress = scan['progress']
        initiator_name = f"{scan['initiator']['firstname']} {scan['initiator']['lastname']}"
        timerunning = timedelta(seconds=time.time() - int(scan['startTime'])) \
            if int(scan['startTime']) >= 0 else 0
        start_time = time.strftime('%H:%M %a %b %d', time.localtime(int(scan['startTime']))) \
            if int(scan['startTime']) >= 0 else '<Initializing>'
        # creation_start_same = False
        if 'scan' in scan.keys() and 'schedule' in scan['scan'].keys() and 'nextRun' in scan['scan']['schedule'].keys():
            creation_start_same = scan['createdTime'] == scan['scan']['schedule']['nextRun']
        display += f"{c.get(c.BG_255(34), c.FG_RGB(0, 0, 0))}" \
                   f"{scan['name']:50.50} "
        if scan['status'] == 'Paused':
            display += f"{c.get(c.BLINK_SLOW)}{c.get(c.INVERSE_VIDEO)}" \
                       f"--PAUSED--" \
                       f"{c.get(c.INVERSE_OFF)}{c.get(c.BLINK_OFF)}"
        display += f"{c.get(c.FG_RGB(255, 255, 0))}" \
                   f"{int(progress['completedIPs']):>10,} " \
                   f"{c.get(c.FG_BLACK)}" \
                   f"IP(s) scanned " \
                   f"{c.get(c.FG_RGB(0, 255, 255))}"
        if int(progress['totalChecks']) and int(progress['completedChecks']):
            display += f"({float(progress['completedChecks']) / float(progress['totalChecks']):7.2%} Completed)"
        else:
            display += f"({float(progress['completedIPs']) / float(progress['totalIPs']):7.2%} Completed)"
        display += f"{c.get(c.FG_BR_WHITE, c.BG_BLACK)}" \
                   f"{' ' * 5}" \
                   f"Run by: {initiator_name} " \
                   f"at {start_time} " \
                   f"for {str(timerunning).split('.')[0]}\r\n"
        display += c.get(c.END)

        # Find longest scanner name
        scanner_name_length = 0
        for scanner in progress['scanners']:
            scanner_name_length = \
                len(scanner['name']) if len(scanner['name']) > scanner_name_length else scanner_name_length

        # --- DISPLAY EACH SCANNER INFO ---
        for scanner in scan['progress']['scanners']:
            ips = netaddr.IPSet()
            chunks = []
            for chunk in scanner['chunks']:
                if len(chunk['ips'].split(',')) > 1:
                    chunks.extend(chunk['ips'].split(','))
                else:
                    chunks.append(chunk['ips'])
            for chunk in chunks:
                if '-' in chunk:
                    ips.add(netaddr.IPRange(chunk.split('-')[0], chunk.split('-')[1]))
                else:
                    ips.add(netaddr.IPAddress(chunk))
            range_string = [str(ip_range) for ip_range in ips.iter_ipranges()]
            for index in range(len(range_string)):
                if len(netaddr.IPRange(start=range_string[index].split('-')[0],
                                       end=range_string[index].split('-')[1]).cidrs()) == 1:
                    range_string[index] = str(
                        netaddr.IPRange(start=range_string[index].split('-')[0],
                                        end=range_string[index].split('-')[1]).cidrs()[0]
                    ).split('/32')[0]
            range_string = ', '.join(range_string)

            if range_string:
                for index in range(len(range_string.split(','))):
                    if index == 0:
                        display += f"\t{scanner['name']:<{scanner_name_length}} - {range_string.split(',')[index]}\r\n"
                    else:
                        display += f"\t{'':<{scanner_name_length + 3}}{range_string.split(',')[index].strip()}\r\n"

    return display or "No scans found"


if __name__ == '__main__':
    main()
