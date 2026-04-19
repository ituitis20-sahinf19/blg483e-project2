import threading
import http.server
import socketserver
import json
import time
import queue
from urllib.parse import urlparse, urljoin, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
import re # For basic keyword extraction

# --- Thread-Safe Data Structures (provided) ---

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
            # Prevent duplicate entries for the same URL_info under the same keyword.
            # This is a simple de-duplication, more advanced would involve sorting
            # or managing a set of url_info per keyword.
            if url_info not in self._index[keyword]:
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


# --- Localhost API Structural Design (provided) ---

class VibeCrawlerHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Custom HTTP Server designed to run exclusively on localhost (5.4 Execution Environment).
    It uses `socketserver.ThreadingMixIn` to handle incoming requests concurrently,
    demonstrating "Concurrency Management" (2. Project Goals).
    This server holds references to the shared `ThreadSafeVisitedSet` and `ThreadSafeIndexMap`,
    making them accessible to request handlers.
    """
    daemon_threads = True # Allows server threads to exit when the main program exits cleanly.

    def __init__(self, server_address, RequestHandlerClass, visited_set, index_map, frontier_queue=None, crawler_is_running_event=None):
        super().__init__(server_address, RequestHandlerClass)
        self.visited_set = visited_set
        self.index_map = index_map
        # The frontier_queue is included for dashboard metrics ("Current Queue Depth")
        # as per "System Visibility & UI (Dashboard)" requirements.
        self.frontier_queue = frontier_queue # Assumes a thread-safe queue instance will be passed.
        self.crawler_is_running_event = crawler_is_running_event # An event to indicate crawler status

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
        metrics['throttling_status'] = 'Active (Crawler respects crawl_delay)'

        # Crawler status
        metrics['crawler_status'] = 'Running' if (self.server.crawler_is_running_event and self.server.crawler_is_running_event.is_set()) else 'Idle/Stopped'

        self._set_headers(200)
        self.wfile.write(json.dumps({'dashboard_metrics': metrics}).encode('utf-8'))


# --- Crawler Implementation ---

class LinkAndTextExtractor(HTMLParser):
    """
    A custom HTML parser to extract links (hrefs from <a> tags) and visible text.
    """
    def __init__(self):
        super().__init__()
        self.links = []
        self.text_content = []
        self._recording_text = False # Simple state for text extraction

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    self.links.append(value)
        # Consider common tags that contain visible text
        if tag in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span', 'li', 'td', 'th', 'title']:
            self._recording_text = True

    def handle_endtag(self, tag):
        if tag in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span', 'li', 'td', 'th', 'title']:
            self._recording_text = False
            # Add a space to separate text blocks
            if self.text_content and self.text_content[-1] != ' ':
                self.text_content.append(' ')


    def handle_data(self, data):
        if self._recording_text:
            stripped_data = data.strip()
            if stripped_data:
                self.text_content.append(stripped_data)

    def get_links(self) -> list[str]:
        return self.links

    def get_text(self) -> str:
        return ' '.join(self.text_content)

    def reset(self):
        super().reset()
        self.links = []
        self.text_content = []
        self._recording_text = False

class Crawler:
    """
    The core recursive crawler logic, managing the frontier, visited URLs, and indexing.
    Implements backpressure and depth limits.
    """
    USER_AGENT = 'VibeCrawler/1.0 (Python native crawler; contact: example@example.com)'
    # Basic list of common stop words for simple keyword filtering
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he', 'in',
        'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'were', 'will', 'with'
    }

    def __init__(self, visited_set: ThreadSafeVisitedSet, index_map: ThreadSafeIndexMap,
                 frontier_queue: queue.Queue, max_depth: int, crawl_delay_seconds: float = 0.5):
        self.visited_set = visited_set
        self.index_map = index_map
        self.frontier_queue = frontier_queue # Stores (url, depth, origin_url) tuples
        self.max_depth = max_depth
        self.crawl_delay_seconds = crawl_delay_seconds
        self._workers = []
        self._running = threading.Event() # Event to signal crawler is active/inactive
        self._active_workers = threading.Semaphore(0) # Track active worker count for graceful shutdown

    def _normalize_url(self, base_url: str, link: str) -> str | None:
        """
        Normalizes a URL, resolving relative paths and filtering out unwanted schemes.
        Returns a cleaned absolute URL or None if invalid.
        """
        # Resolve relative URLs
        absolute_url = urljoin(base_url, link)
        
        # Parse the URL to examine components
        parsed = urlparse(absolute_url)

        # Filter out non-http/https schemes
        if parsed.scheme not in ['http', 'https']:
            return None
        
        # Remove fragment identifiers (e.g., #section) as they don't represent unique pages for crawling
        clean_url = parsed._replace(fragment="").geturl()

        return clean_url

    def _extract_keywords(self, text: str) -> list[str]:
        """
        Extracts simple keywords from text content.
        Converts to lowercase, splits by non-alphanumeric, filters stop words.
        """
        # Split by non-alphanumeric characters, convert to lowercase
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter out stop words and single-character words (unless they are numbers)
        keywords = [
            word for word in words
            if word not in self.STOP_WORDS and (len(word) > 1 or word.isdigit())
        ]
        return keywords

    def _fetch_and_parse(self, url: str) -> tuple[str | None, list[str], str]:
        """
        Fetches the HTML content of a URL and parses it for links and text.
        Returns (html_content, links, text) or (None, [], "") on error.
        """
        try:
            req = Request(url, headers={'User-Agent': self.USER_AGENT})
            with urlopen(req, timeout=10) as response:
                content_type = response.info().get_content_type()
                if not content_type or not content_type.startswith('text/html'):
                    # print(f"Skipping non-HTML content for {url}: {content_type}")
                    return None, [], ""

                html_bytes = response.read()
                # Attempt to decode, falling back to a common encoding if original fails
                try:
                    html_content = html_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        html_content = html_bytes.decode('latin-1')
                    except UnicodeDecodeError:
                        print(f"Failed to decode HTML for {url}")
                        return None, [], ""
                
                parser = LinkAndTextExtractor()
                parser.feed(html_content)
                links = parser.get_links()
                text = parser.get_text()
                parser.close()
                return html_content, links, text

        except HTTPError as e:
            # print(f"HTTP Error {e.code} for {url}: {e.reason}")
            pass
        except URLError as e:
            # print(f"URL Error for {url}: {e.reason}")
            pass
        except Exception as e:
            # print(f"Generic error fetching {url}: {e}")
            pass
        return None, [], ""

    def _process_page(self, current_url: str, html_content: str, extracted_links: list[str],
                      page_text: str, depth: int, origin_url: str):
        """
        Processes the content of a crawled page: adds keywords to index and
        new URLs to the frontier.
        """
        # Add keywords to the index
        keywords = self._extract_keywords(page_text)
        for keyword in keywords:
            self.index_map.add(keyword, current_url, origin_url, depth)

        # Add new links to frontier if within depth limit
        if depth < self.max_depth:
            for link in extracted_links:
                normalized_link = self._normalize_url(current_url, link)
                if normalized_link and self.visited_set.add(normalized_link):
                    # print(f"  Adding to frontier: {normalized_link} (Depth: {depth + 1})")
                    self.frontier_queue.put((normalized_link, depth + 1, current_url))

    def worker_thread(self):
        """
        Worker function for crawler threads. Continuously fetches URLs from the frontier
        and processes them.
        """
        self._active_workers.release() # Indicate this worker is active
        # print(f"Crawler worker {threading.get_ident()} started.")

        while self._running.is_set():
            try:
                # Use a timeout to periodically check if the crawler should stop
                url_info = self.frontier_queue.get(timeout=1)
                current_url, depth, origin_url = url_info
                
                # print(f"Worker {threading.get_ident()} crawling: {current_url} (Depth: {depth})")

                html_content, links, text = self._fetch_and_parse(current_url)
                if html_content:
                    self._process_page(current_url, html_content, links, text, depth, origin_url)
                
                self.frontier_queue.task_done()
                time.sleep(self.crawl_delay_seconds) # Apply backpressure
            except queue.Empty:
                # If queue is empty, worker can check if it should shut down or wait
                if not self._running.is_set():
                    break # Exit loop if signal to stop is received
                # Optionally, could sleep longer if queue is empty to reduce busy-waiting
                time.sleep(self.crawl_delay_seconds * 2)
            except Exception as e:
                # print(f"Crawler worker error: {e}")
                self.frontier_queue.task_done() # Mark task as done even if it failed
        
        # print(f"Crawler worker {threading.get_ident()} stopped.")
        self._active_workers.acquire() # Indicate this worker is no longer active


    def start(self, seed_urls: list[str], num_workers: int = 5):
        """
        Starts the crawling process with initial seed URLs and specified number of workers.
        """
        self._running.set() # Set the running flag
        self._workers = []

        # Add initial seed URLs to the frontier
        for seed_url in seed_urls:
            normalized_seed = self._normalize_url("", seed_url) # No base URL needed for seed
            if normalized_seed and self.visited_set.add(normalized_seed):
                self.frontier_queue.put((normalized_seed, 0, normalized_seed)) # Depth 0, origin is self

        for i in range(num_workers):
            worker = threading.Thread(target=self.worker_thread, daemon=True)
            self._workers.append(worker)
            worker.start()
        
        print(f"Started {num_workers} crawler workers.")

    def stop(self):
        """
        Signals crawler workers to stop and waits for them to finish current tasks.
        """
        self._running.clear() # Clear the running flag
        print("Signaling crawler workers to stop...")

        # Wait for all workers to release their semaphore
        for _ in range(len(self._workers)):
            # acquire with a timeout to prevent infinite block if worker got stuck
            if not self._active_workers.acquire(timeout=5):
                print("Warning: A crawler worker might be stuck or slow to shut down.")
        
        # Optionally wait for the queue to be empty, but workers should handle tasks_done
        self.frontier_queue.join() 
        print("Crawler workers stopped and queue processed.")


# --- Example Usage and Server Setup ---
if __name__ == "__main__":
    # 1. Initialize the thread-safe data structures
    visited_urls_set = ThreadSafeVisitedSet()
    inverted_index_map = ThreadSafeIndexMap()
    frontier_queue_instance = queue.Queue() # Using native queue.Queue for frontier (is thread-safe)
    crawler_running_event = threading.Event() # To signal crawler status to the dashboard

    # 2. Crawler Configuration
    seed_urls = [
        "https://www.google.com/search?q=python+programming",
        "https://www.bing.com/search?q=backend+engineering",
        "https://example.com" # A simpler site for testing
    ]
    MAX_CRAWL_DEPTH = 2  # Max depth to crawl (0 for seed only, 1 for seed + its links, etc.)
    NUM_CRAWLER_WORKERS = 3
    CRAWL_DELAY = 0.5 # Seconds between requests per worker (backpressure)

    crawler = Crawler(visited_urls_set, inverted_index_map,
                      frontier_queue_instance, MAX_CRAWL_DEPTH, CRAWL_DELAY)

    # 3. Start the Crawler in a separate thread
    # The crawler's internal threads manage the crawling. This thread just starts the main orchestrator.
    crawler_main_thread = threading.Thread(target=crawler.start, args=(seed_urls, NUM_CRAWLER_WORKERS))
    crawler_main_thread.daemon = True # Allow main program to exit even if crawler_main_thread is running
    crawler_running_event.set() # Indicate crawler is starting
    crawler_main_thread.start()
    print("Crawler started in background.")

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
                                   visited_urls_set, inverted_index_map,
                                   frontier_queue_instance, crawler_running_event)

    # Run the server in a separate thread to keep the main script responsive
    # and allow for a clean shutdown. Daemon thread ensures it doesn't prevent exit.
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    try:
        # Keep the main thread alive indefinitely to allow the server_thread and crawler to run.
        # Use a non-busy wait for efficiency.
        while True:
            # Periodically print stats to console for live feedback
            time.sleep(5)
            print(f"\n--- Live Metrics ---")
            print(f"Visited URLs: {visited_urls_set.size()}")
            print(f"Indexed Keywords: {inverted_index_map.size()}")
            print(f"Indexed Entries: {inverted_index_map.total_entries()}")
            print(f"Frontier Queue Depth: {frontier_queue_instance.qsize()}")
            
            # Check if crawler workers are still active (queue might be empty but workers still running)
            if frontier_queue_instance.empty() and visited_urls_set.size() > 0:
                 # Small delay to ensure all `task_done` are called and workers truly idle
                time.sleep(2) 
                if frontier_queue_instance.empty():
                    print("Crawler frontier is empty. Stopping crawler.")
                    crawler_running_event.clear() # Indicate crawler is stopping/idle
                    crawler.stop()
                    break # Exit main loop if crawler is done

    except KeyboardInterrupt:
        print("\n--- Stopping VibeCrawler Server and Crawler ---")
        crawler_running_event.clear() # Signal crawler to stop
        crawler.stop() # Ensure crawler threads are gracefully shut down
        server.shutdown() # Shuts down the server, stopping the serve_forever loop.
        server.server_close() # Closes the server socket.
        print("Server and Crawler gracefully stopped.")