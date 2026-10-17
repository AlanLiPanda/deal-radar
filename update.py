#!/usr/bin/env python3
"""从 Flipp 抓本周折扣 + 实时汇率，写入 data.json（图片内嵌成 data URI）。

用法：python3 update.py [目录]
商品和邮编在目录里的 products.json 改，结果写到同目录的 data.json。默认是本脚本所在目录。
"""
import base64, io, json, os, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0'}
MAX_DEALS = 10


def get(url, raw=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        data = r.read()
    return data if raw else json.loads(data)


def words(s):
    return [w.strip().lower() for w in (s or '').split(',') if w.strip()]


def thumb(url):
    """下载图片缩到 120px，返回 data URI。Mac 上用自带的 sips，其他系统用 Pillow。失败返回空字符串。"""
    if not url:
        return ''
    try:
        raw = get(url, raw=True)
        if shutil.which('sips'):
            with tempfile.TemporaryDirectory() as d:
                src, out = os.path.join(d, 'in'), os.path.join(d, 'out.jpg')
                open(src, 'wb').write(raw)
                subprocess.run(['sips', '-Z', '120', '-s', 'format', 'jpeg', '-s', 'formatOptions', '70',
                                src, '--out', out], check=True, capture_output=True)
                jpg = open(out, 'rb').read()
        else:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            im.thumbnail((120, 120))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=70)
            jpg = buf.getvalue()
        return 'data:image/jpeg;base64,' + base64.b64encode(jpg).decode()
    except Exception:
        return ''


def deals_for(p, postal, now):
    q = urllib.parse.urlencode({'locale': 'en-ca', 'postal_code': postal, 'q': p['q']})
    items = get('https://backflipp.wishabi.com/flipp/items/search?' + q).get('items') or []
    must, ex = words(p.get('must')), words(p.get('ex'))
    seen, out = set(), []
    for it in items:
        nm = (it.get('name') or '').lower()
        if not all(w in nm for w in must) or any(w in nm for w in ex):
            continue
        if not it.get('valid_to') or datetime.fromisoformat(it['valid_to']) < now:
            continue
        key = (it.get('merchant_name'), nm, it.get('current_price'), it.get('sale_story'))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: it.get(k) for k in ('name', 'merchant_name', 'current_price', 'original_price',
                                           'sale_story', 'pre_price_text', 'post_price_text',
                                           'valid_from', 'valid_to', 'clean_image_url')})
    out.sort(key=lambda d: (d['current_price'] is None, d['current_price'] or 0, d['valid_to']))
    out = out[:MAX_DEALS]
    for d in out:
        d['img'] = thumb(d.pop('clean_image_url'))
    return out


def main():
    cfg = json.load(open(os.path.join(HERE, 'products.json')))
    now = datetime.now(timezone.utc)
    rate = None
    try:
        rate = round(get('https://open.er-api.com/v6/latest/CAD')['rates']['CNY'], 3)
    except Exception as e:
        print('汇率读取失败:', e)
    products = []
    for p in cfg['products']:
        p = dict(p)
        if p.get('q'):
            try:
                p['deals'] = deals_for(p, cfg['postal'], now)
            except Exception as e:
                p['deals'], p['error'] = [], str(e)
        products.append(p)
        print(f"{p['zh']}: {'手动' if not p.get('q') else len(p['deals'])}")
    data = {'fetchedAt': now.isoformat(), 'postal': cfg['postal'], 'rate': rate, 'products': products}
    json.dump(data, open(os.path.join(HERE, 'data.json'), 'w'), ensure_ascii=False)
    print('data.json', os.path.getsize(os.path.join(HERE, 'data.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()
