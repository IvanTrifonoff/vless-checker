import os, json, time, base64, requests, subprocess, concurrent.futures
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY')
SUB_PATH = os.getenv('SUB_PATH', 'sub.txt')
HISTORY_PATH = os.getenv('HISTORY_PATH', 'history.json')
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/AirLinkVPN1/AirLinkVPN/refs/heads/main/rkn_white_list"
]
THREADS = 15
TEST_FILE_URL = "https://cachefly.cachefly.net/5mb.test"

tg_session = requests.Session()
if TELEGRAM_PROXY:
    tg_session.proxies = {'http': TELEGRAM_PROXY, 'https': TELEGRAM_PROXY}

def parse_vless(url):
    try:
        p = urlparse(url)
        params = {k: v[0] for k, v in parse_qs(p.query).items()}
        return {
            "url": url, "uuid": p.username, "address": p.hostname,
            "port": int(p.port) if p.port else 443, "params": params,
            "name": unquote(p.fragment) if p.fragment else "Untitled"
        }
    except: return None

def generate_config(d, port):
    p = d['params']
    sec = p.get('security', '').lower()
    sni = p.get('sni', p.get('peer', d['address']))
    out = {"type": "vless", "tag": "proxy", "server": d['address'], "server_port": d['port'], "uuid": d['uuid']}
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
    return {"log": {"level": "error"}, "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": port}], "outbounds": [out]}

def test_worker(url, idx):
    d = parse_vless(url)
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
    if sc >= 5: new_name = f"🥇 trfnv_checked_{code}_{sc}"
    elif sc >= 2: new_name = f"✅ trfnv_verified_{code}_{sc}"
    else: new_name = f"🆕 trfnv_new_{code}"
    
    # СТРОГОЕ СТРОКОВОЕ МАНИПУЛИРОВАНИЕ (НИКАКОГО URLPARSE)
    # Это гарантирует 100% сохранность параметров подключения
    if '#' in url:
        return url.rsplit('#', 1)[0] + "#" + new_name
    return url + "#" + new_name

def main():
    print(f"🚀 VLESS Stability Checker started at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    history = {}
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r') as f: history = json.load(f)
        except: history = {}

    source_urls = []
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, timeout=10)
            links = [l.strip() for l in resp.text.splitlines() if l.startswith("vless://")]
            source_urls.extend(links)
        except: pass

    test_urls = list(set(source_urls))
    
    # Добавляем ссылки из истории (чтобы продолжать тестировать те, что пропали из источника)
    for base_url, entry in history.items():
        full_url = f"{base_url}#{entry.get('name', 'Untitled')}"
        if full_url not in test_urls and base_url not in [u.split('#')[0] for u in test_urls]:
            test_urls.append(full_url)
            
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = [ex.submit(test_worker, u, i) for i, u in enumerate(test_urls)]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r: results.append(r)

    now_ts = int(time.time())
    updated_history = {}
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
        entry['name'] = r['name'] # Обновляем имя
        
        if entry['fail_count'] >= 2: continue
        updated_history[base_url] = entry

    working = [(base_url, e) for base_url, e in updated_history.items() if e.get('fail_count', 0) == 0]
    working.sort(key=lambda x: (-x[1].get('success_count', 0), -x[1].get('last_speed', 0)))
    
    # Общая подписка
    all_urls = [add_medals(u, e) for u, e in working]
    with open(SUB_PATH, 'w') as f: f.write(base64.b64encode("\n".join(all_urls).encode()).decode())
    
    # По странам
    country_groups = {}
    for u, e in working:
        if e.get('success_count', 0) < 2: continue
        code = get_country_code(e.get('name', ''))
        if code not in country_groups: country_groups[code] = []
        country_groups[code].append(add_medals(u, e))
    for code, urls in country_groups.items():
        with open(f"sub_{code}.txt", 'w') as f: f.write(base64.b64encode("\n".join(urls).encode()).decode())
    
    with open(HISTORY_PATH, 'w') as f: json.dump(updated_history, f, indent=2)
    print(f"✅ Done. Total: {len(working)}", flush=True)

if __name__ == "__main__": main()
