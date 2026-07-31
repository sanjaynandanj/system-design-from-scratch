"""URL shortener: base62 counter encoding + custom aliases.

Teaches: the simplest collision-free short code is just a monotonically
increasing ID written in base62 (0-9, a-z, A-Z) — no hashing, no
collision checks, and 62^7 ~ 3.5 trillion codes in 7 characters.
Key insight: hashing URLs can collide; a counter never can.
"""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode_base62(n: int) -> str:
    if n == 0:
        return ALPHABET[0]
    digits = []
    while n:
        n, rem = divmod(n, BASE)
        digits.append(ALPHABET[rem])
    return "".join(reversed(digits))  # remainders come out least-significant first


def decode_base62(code: str) -> int:
    n = 0
    for ch in code:
        n = n * BASE + ALPHABET.index(ch)
    return n


class URLShortener:
    def __init__(self, domain="https://sho.rt", start=100_000):
        # Start the counter high so early codes aren't embarrassingly short.
        self.domain = domain
        self.counter = start
        self.code_to_url = {}
        self.url_to_code = {}

    def shorten(self, url: str) -> str:
        if url in self.url_to_code:  # idempotent: same URL -> same code
            return f"{self.domain}/{self.url_to_code[url]}"
        code = encode_base62(self.counter)
        self.counter += 1
        self.code_to_url[code] = url
        self.url_to_code[url] = code
        return f"{self.domain}/{code}"

    def shorten_custom(self, url: str, alias: str) -> str:
        if alias in self.code_to_url:
            raise ValueError(f"alias '{alias}' is already taken")
        # Custom aliases share the same namespace as generated codes;
        # generated ones can't collide with future counters either,
        # unless the alias happens to decode to an upcoming counter —
        # real systems reserve a charset or prefix. We just check.
        self.code_to_url[alias] = url
        self.url_to_code[url] = alias
        return f"{self.domain}/{alias}"

    def resolve(self, short_url: str) -> str:
        code = short_url.rsplit("/", 1)[-1]
        url = self.code_to_url.get(code)
        if url is None:
            raise KeyError(f"unknown short code '{code}'")
        return url


if __name__ == "__main__":
    svc = URLShortener()
    urls = [
        "https://example.com/very/long/path?utm_source=newsletter",
        "https://docs.python.org/3/library/hashlib.html",
        "https://en.wikipedia.org/wiki/Base62",
        "https://github.com/anthropics/claude-code",
        "https://news.ycombinator.com/item?id=12345678",
    ]

    print("=== Shortening 5 URLs (counter starts at 100000) ===")
    shorts = []
    for url in urls:
        short = svc.shorten(url)
        shorts.append(short)
        print(f"  {short}  <-  {url[:55]}")

    print("\n=== Base62 math for the first code ===")
    code = shorts[0].rsplit("/", 1)[-1]
    n = decode_base62(code)
    print(f"  counter {n} -> '{code}':")
    remaining, steps = n, []
    while remaining:
        remaining, rem = divmod(remaining, 62)
        steps.append(f"    {remaining * 62 + rem} = {remaining}*62 + {rem} "
                     f"-> '{ALPHABET[rem]}'")
    print("\n".join(steps))
    print(f"  read remainders bottom-up -> '{code}', "
          f"decode_base62('{code}') = {n}")

    print("\n=== Resolving ===")
    for short in shorts[:3]:
        print(f"  {short} -> {svc.resolve(short)[:60]}")

    print("\n=== Idempotency and custom aliases ===")
    print(f"  shorten(same URL again) -> {svc.shorten(urls[0])}  (same code)")
    print(f"  custom: {svc.shorten_custom('https://example.org', 'launch')}")
    try:
        svc.shorten_custom("https://other.com", "launch")
    except ValueError as e:
        print(f"  taking 'launch' again -> ValueError: {e}")
    print(f"\n  capacity: 62^7 = {62**7:,} codes in just 7 characters")
