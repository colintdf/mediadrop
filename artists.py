"""Interpret explicit semicolon-separated artist credits without rewriting tags."""


def split_artists(value):
    result = []
    seen = set()
    for part in str(value or '').split(';'):
        name = part.strip()
        key = name.casefold()
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def primary_artist(tags, fallback=''):
    for value in (tags.get('album_artist'), tags.get('artist'), fallback):
        names = split_artists(value)
        if names:
            return names[0]
    return ''


def credited_artists(tags, fallback=''):
    names = []
    seen = set()
    for value in (tags.get('album_artist'), tags.get('artist')):
        for name in split_artists(value):
            if name.casefold() not in seen:
                names.append(name)
                seen.add(name.casefold())
    return names or split_artists(fallback) or ['Unknown artist']
