import os, json, time, base64, requests, subprocess, concurrent.futures
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

TG_TOKEN = os.getenv('TG_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY')

# Настройка прокси для Telegram API
if TELEGRAM_PROXY:
    from requests import Session
    from urllib3 import PoolManager, ProxyManager
    
    class ProxySession(Session):
        def __init__(self, proxy):
            super().__init__()
            self.proxy = proxy
        
        def request(self, method, url, **kwargs):
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
            kwargs['proxies'] = proxies
            return super().request(method, url, **kwargs)
    
    tg_session = ProxySession(TELEGRAM_PROXY)
else:
    tg_session = requests.Session()
GITHUB_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt"
SUB_PATH = os.getenv('SUB_PATH', '/var/www/html/sub.txt')
WEB_SUB_URL = "https://panel.trfnv.ru/sub.txt"
THREADS = 5
TEST_FILE_URL = "https://cachefly.cachefly.net/5mb.test"

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

def test_worker(url, idx, total):
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
            r_dl = requests.get(TEST_FILE_URL, proxies=proxies, timeout=20, stream=True)
            size = 0
            if r_dl.status_code == 200:
                for chunk in r_dl.iter_content(chunk_size=65536):
                    if chunk: size += len(chunk)
                
                duration = time.time() - start_speed
                speed = round((size / 1024 / 1024) / (duration + 0.001), 2)
                
                if size > 512 * 1024:
                    res = {"url": url, "name": d['name'], "lat": latency, "speed": speed}
        
        proc.terminate(); proc.wait()
    except: pass
    finally:
        if os.path.exists(cfg_p): os.remove(cfg_p)
    return res

def send_tg(text):
    print(f"📤 Sending to Telegram... (Length: {len(text)})", flush=True)
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
        r = tg_session.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"❌ TG ERROR: {r.text}", flush=True)
            payload.pop("parse_mode")
            tg_session.post(url, json=payload, timeout=10)
        else:
            print("✅ TG OK", flush=True)
    except Exception as e:
        print(f"❌ TG EXCEPTION: {e}", flush=True)

def main():
    print(f"🚀 Starting VLESS Checker at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    try:
        resp = requests.get(GITHUB_URL, timeout=10)
        urls = [l.strip() for l in resp.text.splitlines() if l.startswith("vless://")]
        total = len(urls)
    except Exception as e:
        print(f"❌ Fetch Error: {e}", flush=True)
        return

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = [ex.submit(test_worker, u, i, total) for i, u in enumerate(urls)]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r: results.append(r)

    if results:
        # Сортируем все результаты по скорости (основной критерий) и латентности
        results.sort(key=lambda x: (-x['speed'], x['lat']))
        
        # Функция для определения страны (извлечение из флага или текста в имени)
        def get_country(name):
            n = name.lower()
            if "russia" in n or "🇷🇺" in n: return "RU"
            if "anycast" in n or "🌐" in n: return "ANY"
            # Пытаемся найти эмодзи флага или название страны
            parts = name.split('|')
            return parts[0].strip() if parts else name

        diverse_top = []
        seen_countries = set()
        others = []

        # 1. Сначала берем по одному лучшему из каждой "другой" страны
        for r in results:
            country = get_country(r['name'])
            if country not in ["RU", "ANY"] and country not in seen_countries:
                diverse_top.append(r)
                seen_countries.add(country)
            else:
                others.append(r)
        
        # 2. Дополняем список лучшими из оставшихся (включая RU и ANY) до 20 штук
        needed = 20 - len(diverse_top)
        if needed > 0:
            diverse_top.extend(others[:needed])
        
        # Итоговая сортировка ТОП-20 по скорости
        diverse_top.sort(key=lambda x: (-x['speed'], x['lat']))
        top = diverse_top[:20]
        
        now = datetime.now().strftime("%d.%m %H:%M")
        
        # Разбиваем ТОП-20 на два сообщения по 10 штук
        for block_idx in range(0, 20, 10):
            block = top[block_idx:block_idx+10]
            header = f"<b>🚀 TOP {block_idx+1}-{block_idx+len(block)} DIVERSE VLESS</b>\n📅 {now}\n\n"
            msg = header
            for i, r in enumerate(block, block_idx+1):
                name = r['name'].replace('<', '').replace('>', '')
                msg += f"{i}. {name} (<b>{r['speed']} MB/s</b> | {r['lat']}ms)\n<code>{r['url']}</code>\n\n"
            
            if block_idx == 10: # Добавляем ссылку только в последнее сообщение
                msg += f"🔗 <b>Web:</b> {WEB_SUB_URL}"
            
            send_tg(msg)

        sub_content = "\n".join([r['url'] for r in top])
        with open(SUB_PATH, 'w') as f:
            f.write(base64.b64encode(sub_content.encode()).decode())
            
        print(f"✅ Done. Found {len(results)} working. Saved {len(top)} to {SUB_PATH}", flush=True)

if __name__ == "__main__": main()
