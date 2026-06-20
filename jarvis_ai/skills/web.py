"""Web skills: search, open URLs, and fetch+read a page for summarizing."""
import urllib.parse
import webbrowser


def web_search(query: str) -> str:
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Searching the web for {query}."


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."


def fetch_page(url: str) -> str:
    """Fetch a web page and return its readable text (for summarizing)."""
    import requests
    from bs4 import BeautifulSoup
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[:4000] if text else "No readable text found."
    except Exception as e:
        return f"Fetch error: {e}"


SKILLS = [
    ({"name": "web_search",
      "description": "Search the web for a query in the default browser.",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string"}}, "required": ["query"]}}, web_search),
    ({"name": "open_url",
      "description": "Open a website URL in the default browser.",
      "parameters": {"type": "object",
                     "properties": {"url": {"type": "string"}}, "required": ["url"]}}, open_url),
    ({"name": "fetch_page",
      "description": "Fetch the readable text of a web page so it can be summarized or queried.",
      "parameters": {"type": "object",
                     "properties": {"url": {"type": "string"}}, "required": ["url"]}}, fetch_page),
]
