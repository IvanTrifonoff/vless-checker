import os, json, time, base64, requests, subprocess, concurrent.futures
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY')
SUB_PATH = os.getenv('SUB_PATH', 'sub.txt')
HISTORY_PATH = os.getenv('HISTORY_PATH', 'history.json')
GITHUB_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt"
THREADS = 10
TEST_FILE_URL = "https://cachefly.cachefly.net/5mb.test"

# Настройка прокси для Telegram API
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
    out = {
        "type": "vless", "tag": "proxy", "server": d['address'], "server_port": d['port'],
        "uuid": d['uuid']
    }
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
        
        start_lat = time.time()
        r_lat = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=5)
        if r_lat.status_code in [200, 204]:
            latency = int((time.time() - start_lat) * 1000)
            
            start_speed = time.time()
            r_dl = requests.get(TEST_FILE_URL, proxies=proxies, timeout=15, stream=True)
            size = 0
            if r_dl.status_code == 200:
                for chunk in r_dl.iter_content(chunk_size=65536):
                    if chunk: 
                        size += len(chunk)
                        if size > 5 * 1024 * 1024: break # Достаточно 5MB
                
                duration = time.time() - start_speed
                speed = round((size / 1024 / 1024) / (duration + 0.001), 2)
                
                if size > 300 * 1024: # Минимум 300KB для прохождения теста
                    res = {"url": url, "name": d['name'], "lat": latency, "speed": speed, "success": True}
        
        if not res:
            res = {"url": url, "name": d['name'], "success": False}
            
        proc.terminate(); proc.wait()
    except:
        res = {"url": url, "name": d['name'], "success": False}
    finally:
        if os.path.exists(cfg_p): os.remove(cfg_p)
    return res

def send_tg(text):
    if not TG_TOKEN or not TG_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
        r = tg_session.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            payload.pop("parse_mode")
            tg_session.post(url, json=payload, timeout=10)
    except: pass

def main():
    print(f"🚀 VLESS Stability Checker started at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    
    # 1. Загрузка истории
    history = {}
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r') as f:
                history = json.load(f)
        except: history = {}

    # 2. Получение новых ссылок
    try:
        resp = requests.get(GITHUB_URL, timeout=10)
        source_urls = [l.strip() for l in resp.text.splitlines() if l.startswith("vless://")]
    except:
        print("❌ Error fetching source URLs")
        return

    # 3. Список для теста: все из истории + новые из источника
    test_urls = list(set(source_urls + list(history.keys())))
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = [ex.submit(test_worker, u, i) for i, u in enumerate(test_urls)]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r: results.append(r)

    # 4. Обновление истории и статусов
    now_ts = int(time.time())
    updated_history = {}
    
    for r in results:
        url = r['url']
        is_ok = r['success']
        
        entry = history.get(url, {
            "success_count": 0,
            "fail_count": 0,
            "first_seen": now_ts,
            "name": r['name']
        })
        
        if is_ok:
            entry['success_count'] += 1
            entry['fail_count'] = 0 # Сбрасываем фейлы при успехе
            entry['last_speed'] = r['speed']
            entry['last_lat'] = r['lat']
        else:
            entry['fail_count'] += 1
            # При фейле success_count не сбрасываем, но и не увеличиваем
            
        entry['last_test'] = now_ts
        entry['name'] = r['name'] # Обновляем имя, если изменилось

        # Правило удаления: 2 провала подряд
        if entry['fail_count'] >= 2:
            continue # Удаляем из истории
            
        updated_history[url] = entry

    # 5. Формирование списков для выдачи
    ultra_stable = []
    working_now = []
    
    for url, entry in updated_history.items():
        # Если прошел текущий тест (fail_count == 0)
        if entry['fail_count'] == 0:
            if entry['success_count'] >= 5:
                ultra_stable.append((url, entry))
            else:
                working_now.append((url, entry))

    # Сортировка: сначала ультра, потом остальные (по скорости)
    ultra_stable.sort(key=lambda x: (-x[1].get('last_speed', 0), x[1].get('last_lat', 999)))
    working_now.sort(key=lambda x: (-x[1].get('last_speed', 0), x[1].get('last_lat', 999)))
    
    final_list = ultra_stable + working_now
    
    # 6. Отправка в Telegram
    now_str = datetime.now().strftime("%d.%m %H:%M")
    header = f"<b>💎 VLESS STABILITY REPORT</b>\n📅 {now_str}\n\n"
    header += f"🏆 Ultra Stable: {len(ultra_stable)}\n✅ Working: {len(working_now)}\n\n"
    
    # Берем топ-15 для сообщения в ТГ (чтобы не спамить)
    msg = header
    for i, (url, entry) in enumerate(final_list[:15], 1):
        status = "💎 ULTRA" if entry['success_count'] >= 5 else "✅ OK"
        name = entry['name'].replace('<', '').replace('>', '')
        msg += f"{i}. [{status}] {name}\n(<b>{entry.get('last_speed', 0)} MB/s</b> | {entry.get('last_lat', 0)}ms | S:{entry['success_count']})\n<code>{url}</code>\n\n"
    
    if len(final_list) > 15:
        msg += f"... и еще {len(final_list) - 15} рабочих конфигов в подписке."
    
    send_tg(msg)

    # 7. Сохранение
    # 7.1. Общая подписка в Base64 (все рабочие)
    sub_urls = [x[0] for x in final_list]
    with open(SUB_PATH, 'w') as f:
        f.write(base64.b64encode("\n".join(sub_urls).encode()).decode())
    
    # 7.2. Сегментация по странам
    country_groups = {}
    def get_country_code(name):
        n = name.lower()
        if "🇷🇺" in n or "russia" in n: return "ru"
        if "🇩🇪" in n or "germany" in n: return "de"
        if "🇺🇸" in n or "usa" in n or "united states" in n: return "us"
        if "🇳🇱" in n or "netherlands" in n: return "nl"
        if "🇬🇧" in n or "united kingdom" in n: return "gb"
        if "🇹🇷" in n or "turkey" in n: return "tr"
        if "🇫🇷" in n or "france" in n: return "fr"
        if "🇰🇿" in n or "kazakhstan" in n: return "kz"
        if "🇦🇪" in n or "uae" in n: return "ae"
        # Поиск по эмодзи флага (упрощенно)
        flags = {
            "🇩🇪": "de", "🇺🇸": "us", "🇷🇺": "ru", "🇳🇱": "nl", "🇹🇷": "tr", 
            "🇫🇷": "fr", "🇬🇧": "gb", "🇰🇿": "kz", "🇦🇪": "ae", "🇱🇹": "lt",
            "🇫🇮": "fi", "🇸🇪": "se", "🇵🇱": "pl"
        }
        for f, code in flags.items():
            if f in name: return code
        return "other"

    for url, entry in final_list:
        code = get_country_code(entry['name'])
        if code not in country_groups: country_groups[code] = []
        country_groups[code].append(url)
    
    # Сохраняем файлы для каждой страны
    for code, urls in country_groups.items():
        with open(f"sub_{code}.txt", 'w') as f:
            f.write(base64.b64encode("\n".join(urls).encode()).decode())
    
    # 7.3. История в JSON
    with open(HISTORY_PATH, 'w') as f:
        json.dump(updated_history, f, indent=2)
            
    print(f"✅ Done. Countries: {list(country_groups.keys())}", flush=True)

if __name__ == "__main__": main()
