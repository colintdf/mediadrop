"""Conservative filename suggestions; existing tags and explicit clears win."""
from pathlib import Path
import re


DASH = r'[-\u2013\u2014]'


def infer_filename(filename):
    name = ' '.join(Path(filename).stem.replace('_', ' ').split())
    name = re.sub(r'^(?:CD|Disc)\s*\d+\s*[-_. ]+\s*', '', name, count=1, flags=re.I)
    # Explicit disc-track and track prefixes. Do not strip numeric artist names
    # such as 50 Cent, 808 State, 10cc, or a title consisting only of a year.
    name = re.sub(r'^\d{1,2}[-.]\d{1,3}\s+' + DASH + r'\s+', '', name, count=1)
    name = re.sub(r'^\d{1,3}(?:\s+' + DASH + r'\s+|[.)]\s*|[-]\s*)(?=\S)', '', name, count=1)
    name = re.sub(r'^0\d\s+(?=\S)', '', name, count=1).strip()
    if not name:
        return {}
    parts = re.split(r'\s+' + DASH + r'\s+', name, maxsplit=1)
    if len(parts) == 2 and any(c.isalpha() for c in parts[0]) and any(c.isalnum() for c in parts[1]):
        title = re.sub(r'^\d{1,3}(?:\s+' + DASH + r'\s+|[.)]\s*)(?=\S)', '', parts[1], count=1).strip()
        return {'artist': parts[0].strip(), 'title': title}
    return {'title': name}


def metadata_from_filename(filename, tags, blocked=()):
    inferred = {key: value for key, value in infer_filename(filename).items()
                if key not in blocked and not str(tags.get(key) or '').strip()}
    return {**tags, **inferred}, inferred
