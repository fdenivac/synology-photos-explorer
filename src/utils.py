"""
    some common utilities
"""


def seconds_tostring(seconds, **kwargs):
    """
    convert seconds to string
    format returned :
        [H:]MM:SS[.pp]
    kwargs :
        fract : control decimals number
    """
    stime = []
    seconds = float(seconds)
    if seconds // 3600 > 0:
        stime.append(f"{int(seconds // 3600)}:")
    stime.append(f"{int((seconds // 60) % 60):02}:")
    stime.append(f"{int(seconds % 60):02}")
    if kwargs.get("fract", 0):
        fmt = f"%.{kwargs.get('fract', 0)}f"
        fract = fmt % (seconds % 1)
        fract = fract[1:]
        stime.append(fract)
    return "".join(stime)


def smart_unit(value, unit):
    """convert number in smart form : KB, MB, GB, TB"""
    if value == None:
        return f"- K{unit}"
    if isinstance(value, str):
        value = int(value)
    if value > 1000 * 1000 * 1000 * 1000:
        return f"{(value / (1000 * 1000 * 1000 * 1000.0)):.2f} T{unit}"
    if value > 1000 * 1000 * 1000:
        return f"{(value / (1000 * 1000 * 1000.0)):.2f} G{unit}"
    if value > 1000 * 1000:
        return f"{(value / (1000 * 1000.0)):.2f} M{unit}"
    if value > 1000:
        return f"{(value / (1000.0)):.2f} K{unit}"
