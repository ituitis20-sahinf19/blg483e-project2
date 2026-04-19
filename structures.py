import threading
import http.server
import socketserver
import json
from urllib.parse import urlparse, parse_qs
import queue # Standard library, thread-safe queue for demonstration of frontier_queue

# --- Thread-Safe Data Structures ---

class ThreadSafeVisitedSet:
    """
    A thread-safe set to store URLs that have been visited.
    This fulfills the "Uniqueness Guarantee" (F.1.2) by ensuring no single URL
    is crawled or processed more than once, and adheres to "Concurrency and Thread Safety" (5.1)
    by using native Python threading locks.
    """
    def __init__(self):
        self._visited = set()
        self._lock = threading.Lock()

    def add(self, url: str) -> bool:
        """
        Adds a URL to the set if it hasn't been visited before.
        Returns True if the URL was added, False if it was already present.
        Ensures atomic operation using a lock.
        """
        with self._lock:
            if url in self._visited:
                return False
            self._visited.add(url)
            return True

    def contains(self, url: str) -> bool:
        """
        Checks if a URL is present in the visited set.
        Performs a read operation under a lock.
        """
        with self._lock:
            return url in self._visited

    def size(self) -> int:
        """
        Returns the number of unique URLs currently in the visited set.
        """
        with self._lock:
            return len(self._visited)

    def __len__(self) -> int:
        """Allows len(visited_set) for convenience."""
        return self.size()

    def __contains__(self, url: str) -> bool:
        """Allows 'url in visited_set' for convenience."""
        return self.contains(url)

    def __str__(self):
        """String representation for debugging."""
        with self._lock:
            return f"ThreadSafeVisitedSet(size={len(self._visited)})"

class ThreadSafeIndexMap:
    """
    A thread-safe inverted index mapping keywords to a list of
    (relevant_url, origin_url, depth) triples.
    This supports "Live Indexing Support" (F.2.2) by allowing the Searcher
    to read while the Indexer actively writes, preventing data corruption
    through "Concurrency and Thread Safety" (5.1).
    """
    def __init__(self):
        # Structure: { keyword: [(relevant_url, origin_url, depth), ...] }
        # This structure aligns with the "Searcher (Query Engine)" requirement (F.2.1)
        # to return a structured list of results formatted as a triple.
        self._index = {}
        # A single lock is used for simplicity and safety, ensuring atomicity for both
        # read and write operations on the index, as specified in (5.1).
        self._lock = threading.Lock()

    def add(self, keyword: str, relevant_url: str, origin_url: str, depth: int):
        """
        Adds a keyword-URL mapping to the index. Keywords are normalized to lowercase
        for consistent indexing and searching.
        """
        if not keyword:
            return # Skip empty keywords

        keyword = keyword.lower() # Standardize keyword casing

        # The URL info tuple matches the required search result format (F.2.1).
        url_info = (relevant_url, origin_url, depth)

        with self._lock:
            if keyword not in self._index:
                self._index[keyword] = []
            self._index[keyword].append(url_info)

    def search(self, query_keyword: str) -> list[tuple[str, str, int]]:
        """
        Searches the index for the given keyword and returns a list of
        (relevant_url, origin_url, depth) triples.
        Returns an empty list if no matches are found. The results are a copy
        to prevent external modification of the internal index state.
        """
        if not query_keyword:
            return []

        query_keyword = query_keyword.lower() # Standardize query keyword casing

        with self._lock:
            # Return a copy of the list to ensure thread safety and prevent
            # external modifications while the lock is released.
            return list(self._index.get(query_keyword, []))

    def size(self) -> int:
        """
        Returns the total number of unique keywords currently in the index.
        """
        with self._lock:
            return len(self._index)

    def total_entries(self) -> int:
        """
        Returns the total count of (keyword, url_info) mappings across all keywords.
        """
        with self._lock:
            return sum(len(v) for v in self._index.values())

    def __str__(self):
        """String representation for debugging."""
        with self._lock:
            return f"ThreadSafeIndexMap(keywords={len(self._index)}, entries={self.total_entries()})"


# --- Localhost API Structural Design ---

class VibeCrawlerHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Custom HTTP Server designed to run exclusively on localhost (5.4 Execution Environment).
    It uses `socketserver.ThreadingMixIn` to handle incoming requests concurrently,
    demonstrating "Concurrency Management" (2. Project Goals).
    This server holds references to the shared `ThreadSafeVisitedSet` and `ThreadSafeIndexMap`,
    making them accessible to request handlers.
    """
    daemon_threads = True # Allows server threads to exit when the main program exits cleanly.

    def __init__(self, server_address, RequestHandlerClass, visited_set, index_map, frontier_queue=None):
        super().__init__(server_address, RequestHandlerClass)
        self.visited_set = visited_set
        self.index_map = index_map
        # The frontier_queue is included for dashboard metrics ("Current Queue Depth")
        # as per "System Visibility & UI (Dashboard)" requirements.
        self.frontier_queue = frontier_queue # Assumes a thread-safe queue instance will be passed.

class VibeCrawlerRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    Request handler for the VibeCrawler's "Search API" (6. High-Level Architecture Flow, Step 7)
    and "System Visibility & UI (Dashboard)".
    It processes GET requests for search queries and system metrics.
    """
    def _set_headers(self, status_code=200, content_type='application/json'):
        """Helper to set common HTTP response headers."""
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        """Handles GET requests for different API endpoints."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)

        if path == '/search':
            self._handle_search(query_params)
        elif path == '/dashboard':
            self._handle_dashboard()
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not Found'}).encode('utf-8'))

    def _handle_search(self, query_params):
        """
        Handles search requests, fulfilling "Real-Time Querying" (F.2.1).
        Accepts a 'q' query parameter and returns a structured list of results
        from the live index. Relevancy ranking logic would be applied here (F.2.3).
        """
        query = query_params.get('q', [None])[0]
        if not query:
            self._set_headers(400)
            self.wfile.write(json.dumps({'error': 'Missing query parameter "q"'}).encode('utf-8'))
            return

        # Access the shared index_map from the server instance.
        results = self.server.index_map.search(query)

        # "Relevancy Ranking" (F.2.3): A baseline heuristic would be applied here.
        # For this foundational structure, we return the raw matches.
        # Further development would involve sorting/filtering 'results' based on
        # keyword frequency, HTML Title tag matching, or other criteria.

        formatted_results = []
        for relevant_url, origin_url, depth in results:
            formatted_results.append({
                'relevant_url': relevant_url,
                'origin_url': origin_url,
                'depth': depth
            })

        self._set_headers(200)
        self.wfile.write(json.dumps({'query': query, 'results': formatted_results}).encode('utf-8'))

    def _handle_dashboard(self):
        """
        Handles requests for the "Real-time Dashboard" (System Visibility & UI).
        It collects and displays "Metrics to Track" from the system's live state.
        """
        metrics = {}

        # Current Indexing Progress: total URLs processed vs. URLs currently queued.
        metrics['visited_urls_count'] = self.server.visited_set.size()
        metrics['indexed_keywords_count'] = self.server.index_map.size()
        metrics['indexed_entries_count'] = self.server.index_map.total_entries()

        # Current Queue Depth: live size of the Frontier Queue.
        metrics['frontier_queue_depth'] = 0
        if self.server.frontier_queue:
            try:
                metrics['frontier_queue_depth'] = self.server.frontier_queue.qsize()
            except AttributeError:
                metrics['frontier_queue_depth'] = 'N/A' # In case of a custom queue without qsize()

        # Back-pressure/Throttling Status: indicator.
        # This status is managed by the crawler's workload regulation (F.1.3).
        # It's a system-wide state, represented here as a placeholder.
        metrics['throttling_status'] = 'Pending (System to report active throttling)'

        self._set_headers(200)
        self.wfile.write(json.dumps({'dashboard_metrics': metrics}).encode('utf-8'))

# --- Example Usage and Server Setup (Demonstration) ---
if __name__ == "__main__":
    # 1. Initialize the thread-safe data structures
    visited_urls_set = ThreadSafeVisitedSet()
    inverted_index_map = ThreadSafeIndexMap()
    frontier_queue_instance = queue.Queue() # Using native queue.Queue for frontier (is thread-safe)

    # 2. Simulate some data for demonstration (Indexer activity)
    print("--- Simulating Indexer Activity ---")
    visited_urls_set.add("http://example.com/page1")
    visited_urls_set.add("http://example.com/page2")
    visited_urls_set.add("http://example.com/page1") # This addition should be ignored (uniqueness)
    visited_urls_set.add("http://example.com/about")

    inverted_index_map.add("web", "http://example.com/page1", "http://example.com", 1)
    inverted_index_map.add("crawler", "http://example.com/page1", "http://example.com", 1)
    inverted_index_map.add("search", "http://example.com/page2", "http://example.com", 2)
    inverted_index_map.add("system", "http://example.com/page2", "http://example.com", 2)
    inverted_index_map.add("web", "http://example.com/about", "http://example.com", 2) # Another entry for 'web'

    frontier_queue_instance.put("http://example.com/next_crawl_1")
    frontier_queue_instance.put("http://example.com/next_crawl_2")

    print(f"Visited Set State: {visited_urls_set}")
    print(f"Index Map State: {inverted_index_map}")
    print(f"Frontier Queue Depth: {frontier_queue_instance.qsize()}")

    # 3. Simulate Searcher activity directly
    print("\n--- Simulating Direct Searcher Query ---")
    search_query = "web"
    search_results = inverted_index_map.search(search_query)
    print(f"Search results for '{search_query}': {search_results}")
    assert len(search_results) == 2
    assert ("http://example.com/page1", "http://example.com", 1) in search_results
    assert ("http://example.com/about", "http://example.com", 2) in search_results

    search_query_none = "nonexistent"
    search_results_none = inverted_index_map.search(search_query_none)
    print(f"Search results for '{search_query_none}': {search_results_none}")
    assert len(search_results_none) == 0

    # 4. Set up and run the Localhost API Server
    HOST = '127.0.0.1' # Adheres to (5.4) constraint: localhost only.
    PORT = 8000

    print(f"\n--- Starting VibeCrawler Localhost API Server ---")
    print(f"Server will be accessible at http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"Search API: http://{HOST}:{PORT}/search?q=web")
    print("Press Ctrl+C to stop the server.")

    # Instantiate the custom server with references to the shared data structures.
    server = VibeCrawlerHTTPServer((HOST, PORT), VibeCrawlerRequestHandler,
                                   visited_urls_set, inverted_index_map, frontier_queue_instance)

    # Run the server in a separate thread to keep the main script responsive
    # and allow for a clean shutdown. Daemon thread ensures it doesn't prevent exit.
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    try:
        # Keep the main thread alive indefinitely to allow the server_thread to run.
        # Use a non-busy wait for efficiency.
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        print("\n--- Stopping VibeCrawler Server ---")
        server.shutdown() # Shuts down the server, stopping the serve_forever loop.
        server.server_close() # Closes the server socket.
        print("Server gracefully stopped.")
