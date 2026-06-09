import os, json, time, base64, requests, subprocess, concurrent.futures, html
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY')
SUB_PATH = os.getenv('SUB_PATH', 'sub.txt')
HISTORY_PATH = os.getenv('HISTORY_PATH', 'history.json')
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/26.txt",
    "https://raw.githubusercontent.com/AirLinkVPN1/AirLinkVPN/refs/heads/main/rkn_white_list"
]
THREADS = 15
TEST_FILE_URL = "https://cachefly.cachefly.net/5mb.test"
CLEANUP_DAYS = 7 
MAX_RUNTIME = int(os.getenv('MAX_RUNTIME', 540)) # 9 минут по умолчанию

tg_session = requests.Session()
if TELEGRAM_PROXY:
    tg_session.proxies = {'http': TELEGRAM_PROXY, 'https': TELEGRAM_PROXY}

def parse_proxy(url):
    try:
        p = urlparse(url)
        scheme = p.scheme.lower()
        name = unquote(p.fragment) if p.fragment else "Untitled"
        
        if scheme == "vless" or (scheme == "ss" and "security=reality" in url):
            params = {k: v[0] for k, v in parse_qs(p.query).items()}
            return {
                "type": "vless", "url": url, "uuid": p.username, "address": p.hostname,
                "port": int(p.port) if p.port else 443, "params": params, "name": name
            }
        elif scheme == "vmess":
            try:
                b64_data = url[8:].split('#')[0]
                data = json.loads(base64.b64decode(b64_data + "==").decode())
                return {
                    "type": "vmess", "url": url, "uuid": data['id'], "address": data['add'],
                    "port": int(data['port']), "name": data.get('ps', name),
                    "params": {
                        "net": data.get('net'), "path": data.get('path'), "tls": data.get('tls'),
                        "sni": data.get('sni'), "host": data.get('host'), "scy": data.get('scy', 'auto')
                    }
                }
            except: return None
        elif scheme == "ss":
            try:
                user_info = p.username
                if not user_info: return None
                decoded = base64.b64decode(user_info + "==").decode()
                if ':' not in decoded: return None
                method, password = decoded.split(":", 1)
                return {
                    "type": "shadowsocks", "url": url, "method": method, "password": password,
                    "address": p.hostname, "port": int(p.port), "name": name
                }
            except: return None
        elif scheme == "hysteria2":
            params = {k: v[0] for k, v in parse_qs(p.query).items()}
            return {
                "type": "hysteria2", "url": url, "password": p.username, "address": p.hostname,
                "port": int(p.port) if p.port else 443, "params": params, "name": name
            }
    except: return None

def generate_config(d, port):
    t = d['type']
    out = {"tag": "proxy"}
    
    if t == "vless":
        p = d['params']
        sec = p.get('security', '').lower()
        sni = p.get('sni', p.get('peer', d['address']))
        out.update({"type": "vless", "server": d['address'], "server_port": d['port'], "uuid": d['uuid']})
        if p.get('flow'): out['flow'] = p.get('flow')
        if sec == 'reality':
            out['tls'] = {
                "enabled": True, "server_name": sni,
                "utls": {"enabled": True, "fingerprint": p.get('fp', 'chrome')},
                "reality": {"enabled": True, "public_key": p.get('pbk', ''), "short_id": p.get('sid', '')}
            }
        elif sec == 'tls' or d['port'] == 443:
            out['tls'] = {"enabled": True, "server_name": sni, "utls": {"enabled": True}, "insecure": True}
        tt = p.get('type', 'tcp')
        if tt == 'ws': out['transport'] = {"type": "ws", "path": p.get('path', '/'), "headers": {"Host": p.get('host', sni)}}
        elif tt == 'grpc': out['transport'] = {"type": "grpc", "service_name": p.get('serviceName', '')}
        elif tt in ['xhttp', 'httpupgrade']: out['transport'] = {"type": "httpupgrade", "path": p.get('path', '/'), "host": p.get('host', sni)}

    elif t == "vmess":
        p = d['params']
        out.update({"type": "vmess", "server": d['address'], "server_port": d['port'], "uuid": d['uuid'], "security": p.get('scy', 'auto'), "alter_id": 0})
        if p.get('tls') == 'tls':
            out['tls'] = {"enabled": True, "server_name": p.get('sni', p.get('host', d['address'])), "insecure": True}
        if p.get('net') == 'ws':
            out['transport'] = {"type": "ws", "path": p.get('path', '/'), "headers": {"Host": p.get('host', p.get('sni', ''))}}

    elif t == "shadowsocks":
        out.update({"type": "shadowsocks", "server": d['address'], "server_port": d['port'], "method": d['method'], "password": d['password']})

    elif t == "hysteria2":
        p = d['params']
        out.update({"type": "hysteria2", "server": d['address'], "server_port": d['port'], "password": d['password'], "tls": {"enabled": True, "server_name": p.get('sni', d['address']), "insecure": True}})
        if p.get('obfs') == 'salamander':
            out['obfs'] = {"type": "salamander", "password": p.get('obfs-password', '')}

    return {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": port}],
        "outbounds": [out]
    }

def test_worker(url, idx):
    d = parse_proxy(url)
    if not d: return None
    port = 32000 + idx
    cfg_p = f"cfg_{idx}.json"
    with open(cfg_p, 'w') as f: json.dump(generate_config(d, port), f)
    res = None
    try:
        proc = subprocess.Popen(['sing-box', 'run', '-c', cfg_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        proxies = {'http': f'socks5h://127.0.0.1:{port}', 'https': f'socks5h://127.0.0.1:{port}'}
        r_lat = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=5)
        if r_lat.status_code in [200, 204]:
            latency = int((time.time() - time.time() + 0.1) * 1000)
            r_dl = requests.get(TEST_FILE_URL, proxies=proxies, timeout=15, stream=True)
            size = 0
            if r_dl.status_code == 200:
                for chunk in r_dl.iter_content(chunk_size=65536):
                    if chunk: 
                        size += len(chunk)
                        if size > 512 * 1024: break
                if size > 300 * 1024:
                    res = {"url": url, "name": d['name'], "lat": latency, "speed": 1.0, "success": True}
        if not res: res = {"url": url, "name": d['name'], "success": False}
        proc.terminate(); proc.wait()
    except: res = {"url": url, "name": d['name'], "success": False}
    finally:
        if os.path.exists(cfg_p): os.remove(cfg_p)
    return res

def get_country_code(name):
    n = name.lower()
    flags = {"🇩🇪": "de", "🇺🇸": "us", "🇷🇺": "ru", "🇳🇱": "nl", "🇹🇷": "tr", "🇫🇷": "fr", "🇬🇧": "gb", "🇰🇿": "kz", "🇦🇪": "ae"}
    for f, code in flags.items():
        if f in name: return code
    if "germany" in n: return "de"
    if "usa" in n: return "us"
    if "russia" in n: return "ru"
    return "other"

def add_medals(url, entry):
    code = get_country_code(entry.get('name', '')).upper()
    sc = entry.get('success_count', 1)
    wl_mark = "🛡️WL_" if "@51.250." in url else ""
    
    if sc >= 5: new_name = f"🥇 {wl_mark}trfnv_checked_{code}_{sc}"
    elif sc >= 2: new_name = f"✅ {wl_mark}trfnv_verified_{code}_{sc}"
    else: new_name = f"🆕 {wl_mark}trfnv_new_{code}"
    
    if '#' in url:
        return url.rsplit('#', 1)[0] + "#" + new_name
    return url + "#" + new_name

def main():
    start_time = time.time()
    print(f"🚀 Proxy Stability Checker started at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    history = {}
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r') as f: history = json.load(f)
        except: history = {}

    now_ts = int(time.time())
    source_urls = []
    supported_schemes = ("vless://", "vmess://", "ss://", "hysteria2://")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, timeout=10)
            text = html.unescape(resp.text)
            links = [l.strip() for l in text.splitlines() if l.strip().startswith(supported_schemes)]
            source_urls.extend(links)
        except Exception as e:
            print(f"⚠️ Error fetching {url}: {e}")

    all_candidates = list(set(source_urls))
    for base_url, entry in history.items():
        full_url = f"{base_url}#{entry.get('name', 'Untitled')}"
        if base_url not in [u.split('#')[0] for u in all_candidates]:
            if now_ts - entry.get('last_test', 0) < 86400 * 3:
                all_candidates.append(full_url)

    test_urls = []
    for u in all_candidates:
        base_url = u.split('#')[0]
        if base_url in history and history[base_url].get('fail_count', 0) >= 2:
            continue
        test_urls.append(u)

    print(f"📊 Total candidates: {len(all_candidates)}, skipping known dead. Testing: {len(test_urls)}", flush=True)

    results = []
    # Постепенная обработка результатов для возможности выхода по таймауту
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(test_worker, u, i): u for i, u in enumerate(test_urls)}
        for f in concurrent.futures.as_completed(futs):
            if time.time() - start_time > MAX_RUNTIME:
                print(f"⏰ Time limit reached ({MAX_RUNTIME}s). Saving partial results...", flush=True)
                break
            try:
                r = f.result()
                if r: results.append(r)
            except: pass

    # Обновляем историю только теми результатами, которые успели получить
    updated_history = history.copy()
    for r in results:
        full_url = r['url']
        base_url = full_url.split('#')[0] if '#' in full_url else full_url
        is_ok = r['success']
        
        entry = history.get(base_url, {"success_count": 0, "fail_count": 0, "first_seen": now_ts, "name": r['name']})
        if is_ok:
            entry['success_count'] += 1
            entry['fail_count'] = 0
            entry['last_speed'] = r.get('speed', 0)
            entry['last_lat'] = r.get('lat', 0)
        else:
            entry['fail_count'] += 1
        entry['last_test'] = now_ts
        entry['name'] = r['name']
        updated_history[base_url] = entry

    # Очистка старых записей
    final_history = {}
    for base_url, entry in updated_history.items():
        if now_ts - entry.get('last_test', 0) < 86400 * CLEANUP_DAYS:
            final_history[base_url] = entry

    # Формируем списки рабочих прокси (только на основе полной истории)
    working = [(base_url, e) for base_url, e in final_history.items() if e.get('fail_count', 0) == 0]
    working.sort(key=lambda x: (-x[1].get('success_count', 0), -x[1].get('last_speed', 0)))
    
    all_urls = [add_medals(u, e) for u, e in working]
    with open(SUB_PATH, 'w') as f: f.write(base64.b64encode("\n".join(all_urls).encode()).decode())
    
    country_groups = {}
    for u, e in working:
        if e.get('success_count', 0) < 2: continue
        code = get_country_code(e.get('name', ''))
        if code not in country_groups: country_groups[code] = []
        country_groups[code].append(add_medals(u, e))
    for code, urls in country_groups.items():
        with open(f"sub_{code}.txt", 'w') as f: f.write(base64.b64encode("\n".join(urls).encode()).decode())
    
    with open(HISTORY_PATH, 'w') as f: json.dump(final_history, f, indent=2)
    print(f"✅ Done. Results in this run: {len(results)}. Total working: {len(working)}", flush=True)

if __name__ == "__main__": main()
