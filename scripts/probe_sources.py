"""Inspect public image-source metadata; does not call any model API."""
import json
from pathlib import Path
import requests

cache = Path(__file__).resolve().parents[1] / 'data/cache/mixed'
cache.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers['User-Agent'] = 'ImageRag-local-demo/0.2 (image retrieval test)'

for name, url, params in [
    ('screenspot', 'https://datasets-server.huggingface.co/rows', {'dataset':'bevaya/ScreenSpot','config':'default','split':'test','offset':0,'length':100}),
    ('commons', 'https://commons.wikimedia.org/w/api.php', {'action':'query','generator':'categorymembers','gcmtitle':'Category:Anime illustrations','gcmtype':'file','gcmlimit':30,'prop':'imageinfo','iiprop':'url|size|extmetadata','iiurlwidth':1280,'format':'json'}),
]:
    response=session.get(url,params=params,timeout=(20,60))
    print(name, response.status_code, response.headers.get('Content-Type'), flush=True)
    if response.status_code != 200:
        continue
    data=response.json()
    (cache/f'{name}-probe.json').write_text(json.dumps(data),encoding='utf-8')
    if name=='screenspot':
        rows=data.get('rows',[])
        print('rows',len(rows),'total',data.get('num_rows_total'),'keys', list(rows[0]['row']) if rows else [], flush=True)
        print('sources', sorted({row['row'].get('data_source','') for row in rows}),flush=True)
    else:
        pages=list(data.get('query',{}).get('pages',{}).values())
        print('pages',len(pages),'sample',[page['title'] for page in pages[:5]],flush=True)
