"""Google-facing skills that do not require storing a Google password."""
from urllib.parse import urlencode
import webbrowser


def open_google_maps(destination: str, origin: str = "") -> str:
    """Open Google Maps directions in the default browser."""
    destination = (destination or "").strip()
    if not destination:
        return "Tell me where you want to go."
    params = {"api": "1", "destination": destination, "travelmode": "driving"}
    if origin.strip():
        params["origin"] = origin.strip()
    webbrowser.open("https://www.google.com/maps/dir/?" + urlencode(params))
    return f"Opening Google Maps directions to {destination}."


def search_google_maps(query: str) -> str:
    """Search Google Maps for a place or business."""
    query = (query or "").strip()
    if not query:
        return "Tell me what place to search for."
    webbrowser.open("https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query}))
    return f"Searching Google Maps for {query}."


SKILLS = [
    ({"name": "open_google_maps",
      "description": "Open driving directions in Google Maps to a destination.",
      "parameters": {"type": "object", "properties": {
          "destination": {"type": "string"}, "origin": {"type": "string"}
      }, "required": ["destination"]}}, open_google_maps),
    ({"name": "search_google_maps",
      "description": "Search Google Maps for a place, shop, restaurant, or address.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"}
      }, "required": ["query"]}}, search_google_maps),
]
