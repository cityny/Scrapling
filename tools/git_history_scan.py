import re
import json
from git import Repo
from pathlib import Path

repo = Repo('.')
patterns = {
    'aws_key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'aws_secret': re.compile(r'(?i)aws_secret_access_key\s*[:=]\s*[\'\"]?([A-Za-z0-9/+=]+)[\'\"]?'),
    'private_key': re.compile(r'-----BEGIN (RSA |)PRIVATE KEY-----'),
    'pem_file': re.compile(r'\.pem$'),
    'rsa_file': re.compile(r'id_rsa$'),
    'token_like': re.compile(r'(?i)token\s*[:=]\s*([A-Za-z0-9\-._]{8,})'),
    'password_assign': re.compile(r'(?i)password\s*[:=]\s*[\'\"]?(.{1,60})[\'\"]?'),
    'apikey': re.compile(r'(?i)api[_-]?key\s*[:=]\s*[\'\"]?([A-Za-z0-9\-._]{8,})[\'\"]?')
}

out = []
seen = set()

for commit in repo.iter_commits('--all'):
    try:
        tree = commit.tree
    except Exception:
        continue
    for blob in tree.traverse():
        if blob.type != 'blob':
            continue
        path = blob.path
        key = (commit.hexsha, path)
        if key in seen:
            continue
        seen.add(key)
        try:
            data = blob.data_stream.read()
            try:
                txt = data.decode('utf-8', errors='ignore')
            except Exception:
                txt = ''
        except Exception:
            txt = ''
        for name, pat in patterns.items():
            for m in pat.finditer(txt):
                snippet = m.group(0)
                out.append({
                    'commit': commit.hexsha,
                    'author': commit.author.name,
                    'date': commit.committed_datetime.isoformat(),
                    'path': path,
                    'pattern': name,
                    'match': snippet[:200]
                })

# Save report
p = Path('git_history_secrets.json')
with p.open('w', encoding='utf-8') as fh:
    json.dump(out, fh, indent=2, ensure_ascii=False)
print(f"Found {len(out)} potential secrets. Report written to {p.resolve()}")
