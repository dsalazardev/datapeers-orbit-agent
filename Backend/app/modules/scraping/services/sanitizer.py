from bs4 import BeautifulSoup

UNSAFE_TAGS = {"script", "style", "iframe", "noscript", "link", "meta"}


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(UNSAFE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on"):
                del tag.attrs[attr]
    return str(soup)