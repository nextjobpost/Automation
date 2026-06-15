import requests, json, sys
if sys.stdout.encoding != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except: pass

API_URL = 'https://nextjobpost-backend.onrender.com/api/jobs'
ADMIN_URL = 'https://nextjobpost-backend.onrender.com/api/admin/login'
API_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZjFhM2I0YzllOGE3ZDZlNWY0YzNiMiIsInVzZXJuYW1lIjoiYWRtaW4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODAxOTU0NDB9.QVqxcZLumH_FOjPG2xgvlCoVfSuzJVd-4uEHe8UI7ok'

r = requests.post(ADMIN_URL, json={'username':'admin','password':'admin123'}, timeout=10)
if r.status_code == 200:
    API_TOKEN = r.json().get('token', API_TOKEN)
    print('Login OK')
headers = {'Authorization': f'Bearer {API_TOKEN}'}

r = requests.get(f'{API_URL}?limit=300&status=all', headers=headers, timeout=25)
if r.status_code != 200:
    print(f'Failed: {r.status_code}')
    sys.exit(1)

jobs = r.json().get('data', [])
print(f'Total jobs fetched: {len(jobs)}')

thin = []
for j in jobs:
    desc = j.get('jobDescription', '') or ''
    has_table = '<table' in desc.lower()
    if not desc or len(desc) < 1000 or not has_table:
        thin.append({
            'id': j.get('_id'),
            'title': j.get('title','')[:65],
            'descLen': len(desc),
            'hasTable': has_table,
            'sourceUrl': j.get('sourceUrl',''),
            'slug': j.get('slug','')
        })

print(f'\nThin / empty posts: {len(thin)}')
print('-' * 90)
for i, t in enumerate(thin[:50], 1):
    src = t['sourceUrl'][:55] if t['sourceUrl'] else '(no source)'
    print(f'{i:2}. [{t["descLen"]:5d} chars] {t["title"]}')
    print(f'        src: {src}')

with open('thin_jobs_audit.json', 'w', encoding='utf-8') as f:
    json.dump(thin, f, ensure_ascii=False, indent=2)
print(f'\nSaved full list to thin_jobs_audit.json')
