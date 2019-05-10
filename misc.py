from functools import partial


def nestget(data, *path, default):
    """Getter for data in nested dicts/lists/"itemgettables"."""
    for key_or_index in path:
        try:
            data = data[key_or_index]
        except (KeyError, IndexError, TypeError):
            return default
    return data


nestget_str = partial(nestget, default="")
